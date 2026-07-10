"""KeryxNode — Python SDK entry point for Hermes Agency profiles."""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import grpc

from keryx.card import AgentCard
from keryx.client import DaemonClient
from keryx.config import KeryxConfig, grpc_target, load_config
from keryx.models import TaskArtifact, TaskResult, TaskState
from keryx.task import (
    IncomingTask,
    Message,
    Part,
    Task,
    TaskHandle,
    TaskStatus as LegacyTaskStatus,
)

_PROTO_ROOT = Path(__file__).resolve().parent / "proto"
if str(_PROTO_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROTO_ROOT))

from hermes.keryx.v1 import common_pb2, daemon_pb2, daemon_pb2_grpc, task_pb2  # noqa: E402

logger = logging.getLogger(__name__)

TaskHandler = Callable[[IncomingTask], Awaitable[None]]


class KeryxNode:
    """Async gRPC wrapper around the Keryx daemon.

    The Phase 15A API is the direct daemon lifecycle surface used by Hermes
    Agency profiles: ``connect()``, ``submit()/claim()/heartbeat()/complete()/
    fail()/cancel()``, and query helpers for status/doctor/peers/skills.

    The older AgentAnycast-compatible helpers (``start()``, ``send_task()``,
    ``register_skills()``) are retained so existing SDK callers keep working
    while Agency migrates to the native Keryx lifecycle methods.
    """

    def __init__(
        self,
        card: AgentCard | None = None,
        *,
        config: KeryxConfig | None = None,
        config_path: str | Path | None = None,
        relay_endpoint: str | None = None,
        relay: str | None = None,
        daemon_endpoint: str | None = None,
        daemon_addr: str | None = None,
        registry_endpoint: str | None = None,
        worker_id: str | None = None,
        home: str | Path | None = None,
        daemon_bin: str | Path | None = None,
        status_callback: Callable[[str], None] | None = None,
        channel: grpc.aio.Channel | None = None,
        daemon_stub: Any | None = None,
        client_factory: Callable[..., DaemonClient] | type[DaemonClient] | None = None,
        **_ignored: Any,
    ) -> None:
        loaded_config = config or load_config(config_path)
        if daemon_endpoint or daemon_addr or registry_endpoint or relay_endpoint or relay or worker_id:
            loaded_config = KeryxConfig(
                daemon_endpoint=daemon_endpoint or daemon_addr or loaded_config.daemon_endpoint,
                registry_endpoint=registry_endpoint or loaded_config.registry_endpoint,
                relay_endpoint=relay_endpoint or relay or loaded_config.relay_endpoint,
                worker_id=worker_id or loaded_config.worker_id,
                default_lease_duration_ms=loaded_config.default_lease_duration_ms,
                request_timeout_ms=loaded_config.request_timeout_ms,
            )

        self._config = loaded_config
        self._card = card
        self._relay = loaded_config.relay_endpoint
        self._home = Path(home).expanduser() if home is not None else None
        self._daemon_bin = daemon_bin
        self._status_callback = status_callback
        self._daemon_endpoint = loaded_config.daemon_endpoint
        self._registry_endpoint = loaded_config.registry_endpoint
        self._worker_id = loaded_config.worker_id

        self._channel = channel
        self._owns_channel = channel is None
        self._daemon_stub = daemon_stub
        self._connected = daemon_stub is not None

        self._client_factory = client_factory or DaemonClient
        self._client: DaemonClient | None = None
        self._peer_id: str | None = None
        self._running = False
        self._serve_stop = asyncio.Event()
        self._task_handlers: list[TaskHandler] = []

    @property
    def config(self) -> KeryxConfig:
        return self._config

    @property
    def peer_id(self) -> str:
        if not self._peer_id:
            raise RuntimeError("Node not started. Call await node.start() or await node.connect() first.")
        return self._peer_id

    @property
    def card(self) -> AgentCard | None:
        return self._card

    async def connect(self, *, wait_ready: bool = False) -> "KeryxNode":
        """Create the daemon gRPC stub and optionally wait for channel readiness."""

        if self._connected:
            return self
        if self._status_callback:
            self._status_callback("Connecting to Keryx daemon")
        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(grpc_target(self._daemon_endpoint))
            self._owns_channel = True
        if wait_ready and hasattr(self._channel, "channel_ready"):
            await self._channel.channel_ready()
        self._daemon_stub = daemon_pb2_grpc.KeryxDaemonStub(self._channel)
        self._connected = True
        try:
            self._peer_id = await self.local_peer_id()
            if self._card is not None:
                self._card.peer_id = self._peer_id
        except Exception:  # pragma: no cover - daemon may not expose peers during startup
            logger.debug("Unable to discover local peer id during connect", exc_info=True)
        return self

    async def close(self) -> None:
        """Close the SDK-owned gRPC channel."""

        if self._client is not None:
            await self._client.close()
            self._client = None
        if self._channel is not None and self._owns_channel:
            result = self._channel.close()
            if inspect.isawaitable(result):
                await result
        self._channel = None
        self._daemon_stub = None
        self._connected = False
        self._running = False

    async def __aenter__(self) -> "KeryxNode":
        return await self.connect()

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def status(self) -> dict[str, Any]:
        daemon = await self._daemon()
        return _proto_to_dict(await daemon.Status(daemon_pb2.StatusRequest()))

    async def doctor(self) -> dict[str, Any]:
        daemon = await self._daemon()
        return _proto_to_dict(await daemon.Doctor(daemon_pb2.DoctorRequest()))

    async def peers(self) -> list[dict[str, Any]]:
        daemon = await self._daemon()
        response = await daemon.ListPeers(daemon_pb2.ListPeersRequest())
        return [_proto_to_dict(peer) for peer in response.peers]

    async def skills(
        self,
        skill_id: str = "",
        *,
        tags: Sequence[str] | Mapping[str, str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        daemon = await self._daemon()
        response = await daemon.DiscoverSkills(
            daemon_pb2.DiscoverSkillsRequest(
                skill_id=skill_id,
                tags=_tag_list(tags),
                limit=limit,
            )
        )
        return [_proto_to_dict(registration) for registration in response.registrations]

    async def submit(
        self,
        task_id: str | None = None,
        *,
        message: str | Message | Mapping[str, Any] | None = None,
        messages: Sequence[str | Message | Mapping[str, Any]] | None = None,
        metadata: Mapping[str, str] | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> TaskState:
        daemon = await self._daemon()
        resolved_task_id = task_id or str(uuid.uuid4())
        envelope = _task_envelope(
            task_id=resolved_task_id,
            message=message,
            messages=messages,
            metadata=metadata,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        response = await daemon.SubmitTask(daemon_pb2.SubmitTaskRequest(envelope=envelope))
        state = TaskState.from_submit(response)
        if not state.task_id:
            state.task_id = resolved_task_id
        return state

    async def submit_task(self, *args: Any, **kwargs: Any) -> TaskState:
        return await self.submit(*args, **kwargs)

    async def claim(
        self,
        task_id: str,
        *,
        worker_id: str | None = None,
        lease_duration_ms: int | None = None,
    ) -> TaskState:
        daemon = await self._daemon()
        worker = self._resolve_worker_id(worker_id)
        response = await daemon.ClaimTask(
            daemon_pb2.ClaimTaskRequest(
                task_id=common_pb2.TaskId(value=task_id),
                worker_id=common_pb2.AgentId(value=worker),
                lease_duration_ms=(
                    self._config.default_lease_duration_ms
                    if lease_duration_ms is None
                    else lease_duration_ms
                ),
            )
        )
        return TaskState.from_claim(response)

    async def claim_task(self, *args: Any, **kwargs: Any) -> TaskState:
        return await self.claim(*args, **kwargs)

    async def heartbeat(
        self,
        task_id: str,
        lease_id: str,
        *,
        worker_id: str | None = None,
        lease_duration_ms: int | None = None,
    ) -> TaskState:
        daemon = await self._daemon()
        worker = self._resolve_worker_id(worker_id)
        response = await daemon.Heartbeat(
            daemon_pb2.HeartbeatRequest(
                task_id=common_pb2.TaskId(value=task_id),
                lease_id=common_pb2.LeaseId(value=lease_id),
                worker_id=common_pb2.AgentId(value=worker),
                lease_duration_ms=(
                    self._config.default_lease_duration_ms
                    if lease_duration_ms is None
                    else lease_duration_ms
                ),
            )
        )
        return TaskState.from_heartbeat(response, task_id=task_id, worker_id=worker)

    async def heartbeat_task(self, *args: Any, **kwargs: Any) -> TaskState:
        return await self.heartbeat(*args, **kwargs)

    async def complete(
        self,
        task_id: str,
        lease_id: str,
        *,
        worker_id: str | None = None,
        duration_ms: int = 0,
        result_metadata: Mapping[str, str] | None = None,
        output_artifacts: Sequence[TaskArtifact | Mapping[str, Any]] | None = None,
    ) -> TaskResult:
        daemon = await self._daemon()
        response = await daemon.CompleteTask(
            daemon_pb2.CompleteTaskRequest(
                task_id=common_pb2.TaskId(value=task_id),
                lease_id=common_pb2.LeaseId(value=lease_id),
                worker_id=common_pb2.AgentId(value=self._resolve_worker_id(worker_id)),
                duration_ms=duration_ms,
                result_metadata=dict(result_metadata or {}),
                output_artifacts=[_artifact_proto(item) for item in (output_artifacts or [])],
            )
        )
        return TaskResult.from_complete(response)

    async def complete_task(self, *args: Any, **kwargs: Any) -> TaskResult:
        return await self.complete(*args, **kwargs)

    async def fail(
        self,
        task_id: str,
        lease_id: str,
        error_reason: str,
        *,
        worker_id: str | None = None,
        duration_ms: int = 0,
        failure_metadata: Mapping[str, str] | None = None,
    ) -> TaskResult:
        daemon = await self._daemon()
        response = await daemon.FailTask(
            daemon_pb2.FailTaskRequest(
                task_id=common_pb2.TaskId(value=task_id),
                lease_id=common_pb2.LeaseId(value=lease_id),
                worker_id=common_pb2.AgentId(value=self._resolve_worker_id(worker_id)),
                duration_ms=duration_ms,
                error_reason=error_reason,
                failure_metadata=dict(failure_metadata or {}),
            )
        )
        return TaskResult.from_fail(response)

    async def fail_task(self, *args: Any, **kwargs: Any) -> TaskResult:
        return await self.fail(*args, **kwargs)

    async def cancel(
        self,
        task_id: str,
        *,
        reason: str = "",
        metadata: Mapping[str, str] | None = None,
    ) -> TaskResult:
        daemon = await self._daemon()
        response = await daemon.CancelTask(
            daemon_pb2.CancelTaskRequest(
                task_id=common_pb2.TaskId(value=task_id),
                reason=reason,
                metadata=dict(metadata or {}),
            )
        )
        return TaskResult.from_cancel(response)

    async def cancel_task(self, *args: Any, **kwargs: Any) -> TaskResult:
        return await self.cancel(*args, **kwargs)

    # --- AgentAnycast-compatible transition helpers retained from earlier SDK phases. ---

    def on_task(self, handler: TaskHandler | None = None, *, timeout: float | None = None) -> Any:
        def _wrap(fn: TaskHandler) -> TaskHandler:
            if timeout is not None:

                async def _guarded(task: IncomingTask) -> None:
                    await asyncio.wait_for(fn(task), timeout=timeout)

                self._task_handlers.append(_guarded)
                return _guarded

            self._task_handlers.append(fn)
            return fn

        if handler is not None:
            return _wrap(handler)
        return _wrap

    async def start(self) -> None:
        if self._running:
            return
        factory = self._client_factory or DaemonClient
        self._client = factory(
            daemon_endpoint=self._daemon_endpoint,
            registry_endpoint=self._registry_endpoint,
        )
        await self._client.connect()
        self._peer_id = await self._client.local_peer_id()
        if self._card is not None:
            self._card.peer_id = self._peer_id
        self._running = True
        logger.info("KeryxNode started with peer_id=%s", self._peer_id)

    async def stop(self) -> None:
        if not self._running and not self._connected:
            return
        self._serve_stop.set()
        await self.close()
        logger.info("KeryxNode stopped")

    async def serve_forever(self) -> None:
        self._ensure_running()
        self._serve_stop.clear()
        while not self._serve_stop.is_set():
            await asyncio.sleep(0.25)

    async def list_peers(self) -> list[dict[str, Any]]:
        if self._client is not None and self._running:
            return [
                {"peer_id": peer.peer_id, "connected": peer.connected, "local": peer.local}
                for peer in await self._client.list_peers()
            ]
        return await self.peers()

    async def local_peer_id(self) -> str:
        peers = await self.peers()
        for peer in peers:
            if peer.get("local"):
                return str(peer.get("peer_id") or "")
        if peers:
            return str(peers[0].get("peer_id") or "")
        raise RuntimeError("daemon did not report a local peer id")

    async def discover(
        self,
        skill: str,
        *,
        tags: Mapping[str, str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if self._client is not None and self._running:
            tag_list = list(tags.values()) if tags else []
            return await self._client.discover(skill, tags=tag_list, limit=limit)
        return await self.skills(skill, tags=tags, limit=limit)

    async def get_card(self, peer_id: str) -> AgentCard:
        self._ensure_running()
        assert self._client is not None
        return await self._client.get_card(peer_id)

    async def send_task(
        self,
        message: dict[str, Any] | Message,
        *,
        peer_id: str | None = None,
        skill: str | None = None,
        url: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> TaskHandle:
        self._ensure_running()
        assert self._client is not None
        targets = sum(item is not None for item in (peer_id, skill, url))
        if targets != 1:
            raise ValueError("Exactly one of peer_id, skill, or url must be provided")
        resolved_skill = skill
        if skill is not None:
            discovered = await self.discover(skill, limit=1)
            if not discovered:
                raise RuntimeError(f"no agents found for skill {skill}")
            peer_id = discovered[0]["peer_id"]
        if url is not None:
            raise NotImplementedError("HTTP bridge outbound is not implemented in keryx-py yet")
        assert peer_id is not None
        text = _message_text(message)
        task_id = str(uuid.uuid4())
        try:
            response = await self._client.send_task(
                target_peer_id=peer_id,
                task_id=task_id,
                message_text=text,
                metadata=metadata,
            )
        except Exception as exc:
            if resolved_skill is not None and _is_unknown_peer_error(exc):
                raise NotImplementedError(
                    "Keryx discovered a peer for skill "
                    f"{resolved_skill!r} ({peer_id}), but the local daemon cannot route "
                    "tasks to registry-discovered peers yet. Cross-node Keryx task "
                    "delivery requires a relay-backed daemon route / task publisher."
                ) from exc
            raise
        task = Task(task_id=response.task_id.value or task_id, status=LegacyTaskStatus.SUBMITTED)
        return TaskHandle(task=task)

    async def register_skills(
        self,
        card: AgentCard | None = None,
        *,
        capacity: int | None = None,
        current_load: int = 0,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        self._ensure_running()
        assert self._client is not None
        active_card = card or self._card
        if active_card is None:
            raise RuntimeError("register_skills requires an AgentCard")
        accepted = await self._client.register_skills(
            peer_id=self.peer_id,
            name=active_card.name,
            description=active_card.description,
            skills=[(skill.id, skill.description) for skill in active_card.skills],
            ttl_seconds=ttl_seconds,
        )
        return {
            "accepted": accepted,
            "peer_id": self.peer_id,
            "capacity": capacity,
            "current_load": current_load,
        }

    async def deregister_skills(self, card: AgentCard | None = None) -> dict[str, Any]:
        self._ensure_running()
        assert self._client is not None
        active_card = card or self._card
        if active_card is None:
            raise RuntimeError("deregister_skills requires an AgentCard")
        skill_ids = [skill.id for skill in active_card.skills]
        accepted = await self._client.unregister_skills(peer_id=self.peer_id, skill_ids=skill_ids)
        return {"accepted": accepted, "peer_id": self.peer_id}

    async def _daemon(self) -> Any:
        if not self._connected or self._daemon_stub is None:
            await self.connect()
        assert self._daemon_stub is not None
        return self._daemon_stub

    def _resolve_worker_id(self, worker_id: str | None) -> str:
        resolved = worker_id or self._worker_id or self._peer_id
        if not resolved:
            raise ValueError("worker_id is required (or set HERMES_KERYX_WORKER_ID)")
        return resolved

    def _ensure_running(self) -> None:
        if not self._running or self._client is None:
            raise RuntimeError("Node not started. Call await node.start() first.")


def _task_envelope(
    *,
    task_id: str,
    message: str | Message | Mapping[str, Any] | None,
    messages: Sequence[str | Message | Mapping[str, Any]] | None,
    metadata: Mapping[str, str] | None,
    correlation_id: str | None,
    idempotency_key: str | None,
) -> task_pb2.TaskEnvelope:
    envelope = task_pb2.TaskEnvelope(
        task_id=common_pb2.TaskId(value=task_id),
        status=task_pb2.TASK_STATUS_CREATED,
        metadata=dict(metadata or {}),
    )
    if correlation_id:
        envelope.correlation_id.CopyFrom(common_pb2.CorrelationId(value=correlation_id))
    if idempotency_key:
        envelope.idempotency_key.CopyFrom(common_pb2.IdempotencyKey(value=idempotency_key))
    if messages is not None:
        envelope.messages.extend(_task_message(item) for item in messages)
    elif message is not None:
        envelope.messages.append(_task_message(message))
    return envelope


def _task_message(message: str | Message | Mapping[str, Any]) -> task_pb2.TaskMessage:
    if isinstance(message, str):
        return task_pb2.TaskMessage(
            parts=[task_pb2.TaskMessagePart(media_type="text/plain", text=message)]
        )
    if isinstance(message, Message):
        return task_pb2.TaskMessage(
            parts=[
                task_pb2.TaskMessagePart(media_type="text/plain", text=part.text or "")
                for part in message.parts
            ]
        )
    parts = message.get("parts", [])
    metadata = dict(message.get("metadata", {}) or {})
    return task_pb2.TaskMessage(
        parts=[_message_part(part) for part in parts],
        metadata=metadata,
    )


def _message_part(part: Any) -> task_pb2.TaskMessagePart:
    if isinstance(part, Part):
        return task_pb2.TaskMessagePart(media_type="text/plain", text=part.text or "")
    if isinstance(part, str):
        return task_pb2.TaskMessagePart(media_type="text/plain", text=part)
    return task_pb2.TaskMessagePart(
        media_type=str(part.get("media_type") or "text/plain"),
        text=str(part.get("text") or ""),
        raw=part.get("raw") or b"",
        metadata=dict(part.get("metadata", {}) or {}),
    )


def _artifact_proto(item: TaskArtifact | Mapping[str, Any]) -> daemon_pb2.TaskArtifact:
    if isinstance(item, TaskArtifact):
        return item.to_proto()
    return TaskArtifact(
        path=str(item.get("path") or ""),
        media_type=str(item.get("media_type") or "application/octet-stream"),
        metadata=dict(item.get("metadata", {}) or {}),
    ).to_proto()


def _tag_list(tags: Sequence[str] | Mapping[str, str] | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, Mapping):
        return [str(value) for value in tags.values()]
    return [str(value) for value in tags]



def _is_unknown_peer_error(exc: BaseException) -> bool:
    """Return True for Keryx daemon NOT_FOUND unknown-peer routing errors."""

    code = getattr(exc, "code", None)
    details = getattr(exc, "details", None)
    try:
        status_code = code() if callable(code) else code
    except Exception:
        status_code = None
    try:
        detail_text = details() if callable(details) else details
    except Exception:
        detail_text = None
    text = " ".join(str(part) for part in (detail_text, exc) if part)
    return status_code == grpc.StatusCode.NOT_FOUND and "unknown peer" in text.lower()

def _message_text(message: dict[str, Any] | Message) -> str:
    if isinstance(message, dict):
        parts = message.get("parts") or []
        if parts and isinstance(parts[0], dict):
            return str(parts[0].get("text") or "")
        if parts:
            return str(parts[0])
        return ""
    return (message.parts[0].text if message.parts else "") or ""


def _proto_to_dict(message: Any) -> dict[str, Any]:
    if is_dataclass(message) and not isinstance(message, type):
        return asdict(message)
    result: dict[str, Any] = {}
    for field in message.DESCRIPTOR.fields:
        value = getattr(message, field.name)
        if field.is_repeated:
            if field.message_type is not None and field.message_type.GetOptions().map_entry:
                result[field.name] = dict(value)
            else:
                result[field.name] = [_proto_scalar(item) for item in value]
        elif field.message_type is not None:
            if field.has_presence and not message.HasField(field.name):
                result[field.name] = None
            else:
                result[field.name] = _proto_to_dict(value)
        elif field.has_presence and not message.HasField(field.name):
            result[field.name] = None
        else:
            result[field.name] = value
    return result


def _proto_scalar(value: Any) -> Any:
    if hasattr(value, "DESCRIPTOR"):
        return _proto_to_dict(value)
    return value
