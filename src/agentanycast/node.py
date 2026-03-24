"""Node — the core entry point for AgentAnycast SDK."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agentanycast._generated.agentanycast.v1 import (
    a2a_models_pb2,
    agent_card_pb2,
)
from agentanycast._grpc_client import GrpcClient
from agentanycast.card import AgentCard
from agentanycast.daemon import DaemonManager
from agentanycast.task import (
    Artifact,
    IncomingTask,
    Message,
    Part,
    Task,
    TaskHandle,
    TaskStatus,
)

logger = logging.getLogger(__name__)

# ── OpenTelemetry integration (optional) ─────────────────────
# OTel is entirely optional.  When the ``opentelemetry-api`` package is
# installed the helpers below automatically propagate W3C TraceContext
# through task metadata so that distributed traces span the full
# SDK → daemon → remote path.  When it is *not* installed, the helpers
# are transparent no-ops.

try:
    from opentelemetry import context as otel_context
    from opentelemetry import trace as otel_trace

    _HAS_OTEL = True
except ImportError:
    otel_context = None  # type: ignore[assignment]
    otel_trace = None  # type: ignore[assignment]
    _HAS_OTEL = False


def _inject_trace_context(
    metadata: dict[str, str] | None,
) -> dict[str, str] | None:
    """Inject W3C TraceContext headers into *metadata* if OTel is available.

    When ``opentelemetry-api`` is installed and a span is currently recording,
    the ``traceparent`` (and optionally ``tracestate``) values are added to
    *metadata*.  If *metadata* is ``None`` **and** there is an active span, a
    new dict is created.

    If OTel is not installed the function returns *metadata* unchanged.
    """
    if not _HAS_OTEL:
        return metadata

    span = otel_trace.get_current_span()  # type: ignore[union-attr]
    if span is None or not span.is_recording():
        return metadata

    ctx = span.get_span_context()
    if ctx is None or not ctx.is_valid:
        return metadata

    # Build W3C traceparent: version-trace_id-span_id-trace_flags
    trace_id = format(ctx.trace_id, "032x")
    span_id = format(ctx.span_id, "016x")
    trace_flags = format(ctx.trace_flags, "02x")
    traceparent = f"00-{trace_id}-{span_id}-{trace_flags}"

    if metadata is None:
        metadata = {}

    metadata["traceparent"] = traceparent

    # Propagate tracestate if present.
    if ctx.trace_state:
        ts_str = ",".join(f"{k}={v}" for k, v in ctx.trace_state.items())
        if ts_str:
            metadata["tracestate"] = ts_str

    return metadata


@contextmanager
def _extract_trace_context(metadata: dict[str, str] | None) -> Iterator[None]:
    """Context manager that activates an OTel span from *metadata*.

    If OTel is available and *metadata* contains a ``traceparent`` key the
    function parses the W3C TraceContext header, creates a non-recording
    ``SpanContext``, wraps it in a ``NonRecordingSpan``, and activates it
    via ``opentelemetry.context``.  Downstream code that creates new spans
    will automatically be linked to the remote trace.

    When OTel is not installed or no ``traceparent`` is present the context
    manager is a no-op.
    """
    if not _HAS_OTEL or not metadata or "traceparent" not in metadata:
        yield
        return

    traceparent = metadata["traceparent"]
    parts = traceparent.split("-")
    if len(parts) != 4:
        yield
        return

    try:
        _version, trace_id_hex, span_id_hex, flags_hex = parts
        trace_id = int(trace_id_hex, 16)
        span_id = int(span_id_hex, 16)
        trace_flags = otel_trace.TraceFlags(int(flags_hex, 16))  # type: ignore[union-attr]
    except (ValueError, TypeError):
        yield
        return

    # Reconstruct tracestate if available.
    trace_state = otel_trace.TraceState()  # type: ignore[union-attr]
    if "tracestate" in metadata:
        try:
            pairs = [
                tuple(kv.split("=", 1)) for kv in metadata["tracestate"].split(",") if "=" in kv
            ]
            for k, v in pairs:
                trace_state = trace_state.add(k.strip(), v.strip())  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass

    remote_ctx = otel_trace.SpanContext(  # type: ignore[union-attr]
        trace_id=trace_id,
        span_id=span_id,
        is_remote=True,
        trace_flags=trace_flags,
        trace_state=trace_state,
    )
    remote_span = otel_trace.NonRecordingSpan(remote_ctx)  # type: ignore[union-attr]

    ctx = otel_trace.set_span_in_context(remote_span)  # type: ignore[union-attr]
    token = otel_context.attach(ctx)  # type: ignore[union-attr]
    try:
        yield
    finally:
        otel_context.detach(token)  # type: ignore[union-attr]


# Type alias for the on_task handler signature
TaskHandler = Callable[[IncomingTask], Coroutine[Any, Any, None]]

# Maps between proto TaskStatus and Python TaskStatus
_PROTO_STATUS_MAP = {
    a2a_models_pb2.TASK_STATUS_SUBMITTED: TaskStatus.SUBMITTED,
    a2a_models_pb2.TASK_STATUS_WORKING: TaskStatus.WORKING,
    a2a_models_pb2.TASK_STATUS_INPUT_REQUIRED: TaskStatus.INPUT_REQUIRED,
    a2a_models_pb2.TASK_STATUS_COMPLETED: TaskStatus.COMPLETED,
    a2a_models_pb2.TASK_STATUS_FAILED: TaskStatus.FAILED,
    a2a_models_pb2.TASK_STATUS_CANCELED: TaskStatus.CANCELED,
    a2a_models_pb2.TASK_STATUS_REJECTED: TaskStatus.REJECTED,
}

_STATUS_TO_PROTO_MAP = {
    TaskStatus.SUBMITTED: a2a_models_pb2.TASK_STATUS_SUBMITTED,
    TaskStatus.WORKING: a2a_models_pb2.TASK_STATUS_WORKING,
    TaskStatus.INPUT_REQUIRED: a2a_models_pb2.TASK_STATUS_INPUT_REQUIRED,
    TaskStatus.COMPLETED: a2a_models_pb2.TASK_STATUS_COMPLETED,
    TaskStatus.FAILED: a2a_models_pb2.TASK_STATUS_FAILED,
    TaskStatus.CANCELED: a2a_models_pb2.TASK_STATUS_CANCELED,
    TaskStatus.REJECTED: a2a_models_pb2.TASK_STATUS_REJECTED,
}


def _proto_status_to_python(s: int) -> TaskStatus:
    return _PROTO_STATUS_MAP.get(s, TaskStatus.SUBMITTED)


def _python_status_to_proto(s: TaskStatus) -> int:
    return int(_STATUS_TO_PROTO_MAP.get(s, a2a_models_pb2.TASK_STATUS_UNSPECIFIED))


def _card_to_proto(card: AgentCard) -> agent_card_pb2.AgentCard:
    """Convert Python AgentCard to protobuf AgentCard."""
    skills = [
        agent_card_pb2.Skill(
            id=s.id,
            description=s.description,
            input_schema=s.input_schema or "",
            output_schema=s.output_schema or "",
        )
        for s in card.skills
    ]
    return agent_card_pb2.AgentCard(
        name=card.name,
        description=card.description,
        version=card.version,
        protocol_version=card.protocol_version,
        skills=skills,
    )


def _proto_card_to_python(pb_card: agent_card_pb2.AgentCard) -> AgentCard:
    """Convert protobuf AgentCard to Python AgentCard."""
    from agentanycast.card import Skill

    skills = [
        Skill(
            id=s.id,
            description=s.description,
            input_schema=s.input_schema or None,
            output_schema=s.output_schema or None,
        )
        for s in pb_card.skills
    ]

    p2p = pb_card.p2p_extension
    return AgentCard(
        name=pb_card.name,
        description=pb_card.description,
        version=pb_card.version,
        protocol_version=pb_card.protocol_version,
        skills=skills,
        peer_id=(p2p.peer_id or None) if p2p else None,
        supported_transports=list(p2p.supported_transports) if p2p else [],
        relay_addresses=list(p2p.relay_addresses) if p2p else [],
        did_key=p2p.did_key if p2p and p2p.did_key else None,
        did_web=getattr(p2p, "did_web", None) if p2p else None,
        did_dns=getattr(p2p, "did_dns", None) if p2p else None,
        verifiable_credentials=list(getattr(p2p, "verifiable_credentials", [])) if p2p else [],
    )


def _message_to_proto(msg: Message) -> a2a_models_pb2.Message:
    """Convert Python Message to protobuf Message."""
    pb_parts = []
    for p in msg.parts:
        pb_part = a2a_models_pb2.Part()
        if p.text is not None:
            pb_part.text_part.CopyFrom(a2a_models_pb2.TextPart(text=p.text))
        elif p.url is not None:
            pb_part.url_part.CopyFrom(a2a_models_pb2.UrlPart(url=p.url))
        elif p.raw is not None:
            pb_part.raw_part.CopyFrom(a2a_models_pb2.RawPart(data=p.raw))
        if p.media_type:
            pb_part.media_type = p.media_type
        if p.metadata:
            pb_part.metadata.update(p.metadata)
        pb_parts.append(pb_part)

    role = a2a_models_pb2.MESSAGE_ROLE_USER
    if msg.role == "agent":
        role = a2a_models_pb2.MESSAGE_ROLE_AGENT

    return a2a_models_pb2.Message(
        message_id=msg.message_id,
        role=role,
        parts=pb_parts,
    )


def _proto_message_to_python(pb_msg: a2a_models_pb2.Message) -> Message:
    """Convert protobuf Message to Python Message."""
    parts = []
    for pb_part in pb_msg.parts:
        p = Part()
        if pb_part.HasField("text_part"):
            p.text = pb_part.text_part.text
        elif pb_part.HasField("url_part"):
            p.url = pb_part.url_part.url
        elif pb_part.HasField("raw_part"):
            p.raw = pb_part.raw_part.data
        if pb_part.media_type:
            p.media_type = pb_part.media_type
        if pb_part.metadata:
            p.metadata = dict(pb_part.metadata)
        parts.append(p)

    role = "user" if pb_msg.role == a2a_models_pb2.MESSAGE_ROLE_USER else "agent"
    return Message(role=role, parts=parts, message_id=pb_msg.message_id)


def _proto_artifact_to_python(pb_art: a2a_models_pb2.Artifact) -> Artifact:
    """Convert protobuf Artifact to Python Artifact."""
    parts = []
    for pb_part in pb_art.parts:
        p = Part()
        if pb_part.HasField("text_part"):
            p.text = pb_part.text_part.text
        elif pb_part.HasField("url_part"):
            p.url = pb_part.url_part.url
        elif pb_part.HasField("raw_part"):
            p.raw = pb_part.raw_part.data
        parts.append(p)

    return Artifact(
        artifact_id=pb_art.artifact_id,
        name=pb_art.name,
        parts=parts,
    )


def _artifact_to_proto(art: Artifact) -> a2a_models_pb2.Artifact:
    """Convert Python Artifact to protobuf Artifact."""
    pb_parts = []
    for p in art.parts:
        pb_part = a2a_models_pb2.Part()
        if p.text is not None:
            pb_part.text_part.CopyFrom(a2a_models_pb2.TextPart(text=p.text))
        elif p.url is not None:
            pb_part.url_part.CopyFrom(a2a_models_pb2.UrlPart(url=p.url))
        elif p.raw is not None:
            pb_part.raw_part.CopyFrom(a2a_models_pb2.RawPart(data=p.raw))
        pb_parts.append(pb_part)

    return a2a_models_pb2.Artifact(
        artifact_id=art.artifact_id,
        name=art.name,
        parts=pb_parts,
    )


def _proto_task_to_python(pb_task: a2a_models_pb2.Task) -> Task:
    """Convert protobuf Task to Python Task."""
    messages = [_proto_message_to_python(m) for m in pb_task.messages]
    artifacts = [_proto_artifact_to_python(a) for a in pb_task.artifacts]

    return Task(
        task_id=pb_task.task_id,
        context_id=pb_task.context_id,
        status=_proto_status_to_python(pb_task.status),
        messages=messages,
        artifacts=artifacts,
        target_skill_id=pb_task.target_skill_id,
        originator_peer_id=pb_task.originator_peer_id,
    )


class Node:
    """AgentAnycast P2P node — the main interface for A2A communication.

    Manages the connection to the local Go daemon via gRPC and provides
    a Pythonic async API for sending/receiving A2A Tasks.

    Usage:
        async with Node(card=my_card) as node:
            task = await node.send_task(peer_id, message)
            result = await task.wait()
    """

    def __init__(
        self,
        card: AgentCard,
        relay: str | None = None,
        key_path: str | Path | None = None,
        daemon_addr: str | None = None,
        daemon_bin: str | Path | None = None,
        daemon_path: str | Path | None = None,
        home: str | Path | None = None,
        transport: str | None = None,
        namespace: str | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the Node.

        Args:
            card: Your agent's AgentCard describing its identity and skills.
            relay: Relay server multiaddr for cross-network communication.
                Set to ``None`` for LAN-only (mDNS) mode.
            key_path: Path to the libp2p identity key file. Defaults to
                ``~/.agentanycast/key`` inside *home*.
            daemon_addr: Connect to an already-running daemon at this gRPC
                address instead of launching a new one.
            daemon_bin: Deprecated — use *daemon_path* instead.
            daemon_path: Path to a local ``agentanycastd`` binary. When
                ``None``, the SDK downloads a matching release automatically.
            home: Data directory for daemon state (key, socket, store). Use
                different values to run multiple nodes on the same machine.
                Defaults to ``~/.agentanycast``.
            transport: Transport specification for the daemon (e.g.,
                ``"nats://broker:4222"``, ``"auto"``, ``"libp2p"``).
                When ``None``, defaults to libp2p.
            namespace: Namespace for multi-tenant isolation. When ``None``,
                defaults to ``"default"``.
            status_callback: Optional callback for progress messages (e.g.,
                daemon download, startup). Useful for CLI tools.
        """
        self._card = card
        self._relay = relay
        self._key_path = key_path
        self._daemon_addr = daemon_addr
        self._home = home
        self._transport = transport
        self._namespace = namespace
        self._status_callback = status_callback
        # daemon_path takes precedence over daemon_bin for user convenience
        self._daemon_bin = daemon_path or daemon_bin

        self._daemon: DaemonManager | None = None
        self._grpc: GrpcClient | None = None
        self._peer_id: str | None = None
        self._running = False
        self._task_handlers: list[TaskHandler] = []
        self._serve_task: asyncio.Task[None] | None = None

        # In-memory task tracking for TaskHandle updates
        self._tasks: dict[str, TaskHandle] = {}
        # Track background asyncio tasks to prevent garbage collection
        self._background_tasks: set[asyncio.Task[None]] = set()

    @property
    def peer_id(self) -> str:
        """This node's PeerID (available after start)."""
        if not self._peer_id:
            raise RuntimeError("Node not started. Call await node.start() first.")
        return self._peer_id

    @property
    def card(self) -> AgentCard:
        """The AgentCard associated with this node."""
        return self._card

    @property
    def is_running(self) -> bool:
        return self._running

    def get_task_handle(self, task_id: str) -> TaskHandle | None:
        """Look up a TaskHandle by ID from the current session.

        Returns ``None`` if the task was not sent in this session.
        """
        return self._tasks.get(task_id)

    async def start(self) -> None:
        """Start the node: launch daemon, connect gRPC, set agent card."""
        if self._running:
            return

        # Start or connect to daemon
        if self._daemon_addr:
            logger.info("Connecting to existing daemon at %s", self._daemon_addr)
        else:
            self._daemon = DaemonManager(
                daemon_bin=self._daemon_bin,
                key_path=self._key_path,
                relay=self._relay,
                home=self._home,
                transport=self._transport,
                namespace=self._namespace,
                status_callback=self._status_callback,
            )
            await self._daemon.start()
            self._daemon_addr = self._daemon.grpc_address

        # Establish gRPC channel
        self._grpc = GrpcClient(self._daemon_addr)
        await self._grpc.connect()

        # Set agent card on daemon
        pb_card = _card_to_proto(self._card)
        await self._grpc.set_agent_card(pb_card)

        # Get our PeerID from the daemon
        node_info = await self._grpc.get_node_info()
        self._peer_id = node_info.peer_id

        self._running = True
        logger.info("Node started. Peer ID: %s", self._peer_id)

    async def stop(self) -> None:
        """Stop the node and clean up resources."""
        if not self._running:
            return

        # Cancel serve task if running
        if self._serve_task and not self._serve_task.done():
            self._serve_task.cancel()
            try:
                await self._serve_task
            except asyncio.CancelledError:
                pass

        # Cancel all tracked background tasks
        bg_tasks = list(self._background_tasks)
        for bg in bg_tasks:
            bg.cancel()
        if bg_tasks:
            await asyncio.gather(*bg_tasks, return_exceptions=True)
            self._background_tasks.clear()

        # Close gRPC channel
        if self._grpc:
            await self._grpc.close()
            self._grpc = None

        if self._daemon:
            await self._daemon.stop()

        self._running = False
        logger.info("Node stopped.")

    async def __aenter__(self) -> Node:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    # ── Client Mode: Send Tasks ───────────────────────────────

    async def get_card(self, peer_id: str) -> AgentCard:
        """Get the Agent Card of a connected peer.

        Args:
            peer_id: The PeerID of the remote agent.

        Returns:
            The remote agent's AgentCard.

        Raises:
            PeerNotFoundError: If the peer is not connected.
            CardNotAvailableError: If the peer hasn't shared a card.
        """
        self._ensure_running()
        assert self._grpc is not None
        pb_card = await self._grpc.get_peer_card(peer_id)
        return _proto_card_to_python(pb_card)

    async def send_task(
        self,
        message: dict[str, Any] | Message,
        *,
        peer_id: str | None = None,
        skill: str | None = None,
        url: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> TaskHandle:
        """Send an A2A Task to a remote agent.

        Exactly one of ``peer_id``, ``skill``, or ``url`` must be provided:
        - ``peer_id``: Send directly to a known PeerID.
        - ``skill``: Anycast — route by capability to any matching agent.
        - ``url``: HTTP Bridge — call an external HTTP A2A agent.

        Args:
            message: The message to send (dict or Message object).
            peer_id: Target PeerID for direct addressing.
            skill: Target skill ID for capability-based routing (v0.2).
            url: Target URL for HTTP bridge outbound (v0.2).
            metadata: Optional key-value metadata for the task.

        Returns:
            A TaskHandle for tracking the task's progress.

        Raises:
            SkillNotFoundError: No agents found for the given skill.
            BridgeConnectionError: HTTP bridge outbound failed.
        """
        self._ensure_running()
        assert self._grpc is not None

        targets = sum(x is not None for x in (peer_id, skill, url))
        if targets != 1:
            raise ValueError("Exactly one of peer_id, skill, or url must be provided")

        # Inject OTel trace context into metadata (no-op when OTel is absent).
        metadata = _inject_trace_context(metadata)

        # Normalize message
        if isinstance(message, dict):
            msg = Message(
                role=message.get("role", "user"),
                parts=[Part.from_dict(p) for p in message.get("parts", [])],
            )
        else:
            msg = message

        # Convert to proto and send via gRPC
        pb_msg = _message_to_proto(msg)
        pb_task = await self._grpc.send_task(
            message=pb_msg,
            peer_id=peer_id,
            skill_id=skill,
            url=url,
            metadata=metadata,
        )

        # Convert to Python Task
        task = _proto_task_to_python(pb_task)

        # Create cancel function
        grpc_client = self._grpc

        async def cancel_fn() -> None:
            assert grpc_client is not None
            await grpc_client.cancel_task(task.task_id)

        handle = TaskHandle(task=task, cancel_fn=cancel_fn)
        self._tasks[task.task_id] = handle

        # Start background task to receive updates for this task
        bg = asyncio.create_task(self._watch_task_updates(task.task_id, handle))
        self._background_tasks.add(bg)
        bg.add_done_callback(self._background_tasks.discard)

        target_desc = peer_id or skill or url
        logger.info("Task sent: %s -> %s", task.task_id, target_desc)
        return handle

    async def discover(
        self,
        skill: str,
        *,
        tags: dict[str, str] | None = None,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """Discover agents that offer a specific skill.

        Queries the Relay's Skill Registry for agents matching the given
        skill ID. Optionally filter by tags.

        Args:
            skill: The skill ID to search for.
            tags: Optional tag filters (AND semantics).
            limit: Maximum number of results (0 = server default).

        Returns:
            List of agent info dicts with peer_id, agent_name,
            agent_description, and skills.

        Raises:
            SkillNotFoundError: Discovery service unavailable.
        """
        self._ensure_running()
        assert self._grpc is not None

        resp = await self._grpc.discover(skill, tags=tags, limit=limit)
        return [
            {
                "peer_id": agent.peer_id,
                "agent_name": agent.agent_name,
                "agent_description": agent.agent_description,
                "skills": [
                    {"skill_id": s.skill_id, "description": s.description} for s in agent.skills
                ],
            }
            for agent in resp.agents
        ]

    async def connect_peer(
        self, peer_id: str, addresses: list[str] | None = None
    ) -> dict[str, Any]:
        """Connect to a remote peer by PeerID.

        Args:
            peer_id: The PeerID to connect to.
            addresses: Optional multiaddrs to try.

        Returns:
            Peer info dict.
        """
        self._ensure_running()
        assert self._grpc is not None
        pi = await self._grpc.connect_peer(peer_id, addresses)
        return {"peer_id": pi.peer_id}

    async def list_peers(self) -> list[dict[str, Any]]:
        """List all currently connected peers.

        Returns:
            List of peer info dicts with peer_id, addresses.
        """
        self._ensure_running()
        assert self._grpc is not None
        peers = await self._grpc.list_peers()
        return [
            {
                "peer_id": p.peer_id,
                "addresses": list(p.addresses),
            }
            for p in peers
        ]

    # ── Server Mode: Receive Tasks ────────────────────────────

    def on_task(
        self,
        handler: TaskHandler | None = None,
        *,
        timeout: float | None = None,
    ) -> TaskHandler | Callable[[TaskHandler], TaskHandler]:
        """Register a task handler, optionally with a timeout.

        Can be used as a plain decorator or with arguments:

            @node.on_task
            async def handle(task: IncomingTask):
                await task.complete(artifacts=[...])

            @node.on_task(timeout=30)
            async def handle(task: IncomingTask):
                await task.complete(artifacts=[...])

        Args:
            handler: The handler function (when used as ``@node.on_task``).
            timeout: Maximum seconds the handler may run before the task
                is automatically failed with a timeout error. ``None``
                means no timeout (default).
        """

        def _wrap(fn: TaskHandler) -> TaskHandler:
            if timeout is not None:

                async def _guarded(task: IncomingTask) -> None:
                    try:
                        await asyncio.wait_for(fn(task), timeout=timeout)
                    except asyncio.TimeoutError:
                        logger.error(
                            "Task handler timed out after %ss for task %s",
                            timeout,
                            task.task_id,
                        )
                        await task.fail(f"Handler timed out after {timeout}s")

                self._task_handlers.append(_guarded)
            else:
                self._task_handlers.append(fn)
            return fn

        if handler is not None:
            # Used as @node.on_task (no parentheses).
            return _wrap(handler)
        # Used as @node.on_task(timeout=30).
        return _wrap

    async def serve_forever(self) -> None:
        """Run the node, processing incoming tasks until interrupted.

        This starts listening for incoming A2A Tasks via gRPC streaming
        and dispatches them to registered handlers.
        """
        self._ensure_running()
        assert self._grpc is not None
        logger.info("Serving forever. Waiting for incoming tasks...")

        try:
            async for event in self._grpc.subscribe_incoming_tasks():
                pb_task = event.task
                if pb_task is None:
                    continue

                task = _proto_task_to_python(pb_task)
                sender_card = None
                if event.sender_card and event.sender_card.name:
                    sender_card = _proto_card_to_python(event.sender_card)

                # Create update function that calls back to daemon via gRPC
                grpc_ref = self._grpc

                async def _make_update_fn(tid: str) -> Callable[..., Coroutine[Any, Any, None]]:
                    async def update_fn(
                        task_id: str,
                        status: TaskStatus,
                        artifacts: list[Artifact] | None,
                        error: str | None,
                    ) -> None:
                        assert grpc_ref is not None
                        if status == TaskStatus.COMPLETED:
                            pb_artifacts = (
                                [_artifact_to_proto(a) for a in artifacts] if artifacts else []
                            )
                            await grpc_ref.complete_task(task_id, pb_artifacts)
                        elif status == TaskStatus.FAILED:
                            await grpc_ref.fail_task(task_id, error or "unknown error")
                        else:
                            proto_status = _python_status_to_proto(status)
                            await grpc_ref.update_task_status(task_id, proto_status)

                    return update_fn

                update_fn = await _make_update_fn(task.task_id)

                incoming = IncomingTask(
                    task=task,
                    sender_card=sender_card,
                    update_fn=update_fn,
                )

                # Dispatch to all registered handlers.
                # When OTel is available and the task carries a traceparent in
                # its metadata, the handler runs inside a context linked to
                # the remote trace so that new spans are automatically parented.
                with _extract_trace_context(task.metadata):
                    for handler in self._task_handlers:
                        bg = asyncio.create_task(handler(incoming))
                        self._background_tasks.add(bg)
                        bg.add_done_callback(self._background_tasks.discard)

        except asyncio.CancelledError:
            pass

    # ── Internal ──────────────────────────────────────────────

    async def _watch_task_updates(self, task_id: str, handle: TaskHandle) -> None:
        """Background coroutine that watches for task status updates via gRPC streaming."""
        assert self._grpc is not None
        try:
            async for event in self._grpc.subscribe_task_updates(task_id):
                status = _proto_status_to_python(event.status)
                artifacts = (
                    [_proto_artifact_to_python(a) for a in event.artifacts]
                    if event.artifacts
                    else None
                )
                handle._update(status, artifacts)

                if status.is_terminal:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("task update stream ended: %s", e)

    def _ensure_running(self) -> None:
        if not self._running:
            raise RuntimeError("Node not started. Call await node.start() first.")
