"""AgentAnycast-style Node facade backed by the Keryx SDK."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from keryx import _SDK_PACKAGE_PATH, _ensure_sdk_package_path
from keryx.card import AgentCard, Skill
from keryx.task import Artifact, IncomingTask, Message, Part, Task, TaskHandle, TaskStatus

logger = logging.getLogger(__name__)

TaskHandler = Callable[[IncomingTask], Awaitable[None]]


class Node:
    """Drop-in AgentAnycast ``Node`` facade using Keryx transport underneath.

    The real Keryx SDK package also defines ``KeryxNode``.  Because this adapter
    itself is imported as ``keryx``, loading that module by normal import would
    recurse back into this file.  We therefore load the SDK's ``node.py`` from
    the configured SDK checkout under a private module name, then delegate to
    that implementation for daemon, registry, and native task-lifecycle RPCs.
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
        daemon_verify_checksum: bool = True,
        **keryx_kwargs: Any,
    ) -> None:
        """Initialize an AgentAnycast-compatible node backed by Keryx.

        AgentAnycast parameters are accepted for drop-in import compatibility.
        Parameters not currently used by Keryx (``key_path``, ``transport``,
        ``namespace``, ``daemon_verify_checksum``) are retained as attributes and
        forwarded through ``**keryx_kwargs`` where the underlying SDK accepts
        them.
        """

        sdk_cls = _load_sdk_keryx_node()
        self._card = card
        self._relay = relay
        self._key_path = key_path
        self._daemon_addr = daemon_addr
        self._daemon_bin = daemon_path or daemon_bin
        self._home = home
        self._transport = transport
        self._namespace = namespace
        self._status_callback = status_callback
        self._daemon_verify_checksum = daemon_verify_checksum
        self._task_handlers: list[TaskHandler] = []
        self._tasks: dict[str, TaskHandle] = {}

        # Map AgentAnycast's constructor spelling to Keryx's native SDK names.
        self._sdk = sdk_cls(
            card=card,
            relay=relay,
            daemon_addr=daemon_addr,
            daemon_bin=self._daemon_bin,
            home=home,
            status_callback=status_callback,
            key_path=key_path,
            transport=transport,
            namespace=namespace,
            daemon_verify_checksum=daemon_verify_checksum,
            **keryx_kwargs,
        )

    @property
    def peer_id(self) -> str:
        """This node's PeerID (available after ``start()``)."""

        return self._sdk.peer_id

    @property
    def card(self) -> AgentCard:
        """The local AgentCard associated with this node."""

        sdk_card = getattr(self._sdk, "card", None)
        if sdk_card is not None:
            self._card = _coerce_card(sdk_card)
        return self._card

    @property
    def is_running(self) -> bool:
        return bool(getattr(self._sdk, "_running", False))

    @property
    def config(self) -> Any:
        """Expose Keryx's native config object when available."""

        return getattr(self._sdk, "config", None)

    def get_task_handle(self, task_id: str) -> TaskHandle | None:
        """Return a TaskHandle created by this process, if present."""

        return self._tasks.get(task_id)

    async def start(self) -> None:
        """Start/connect the underlying Keryx node and register local skills."""

        await self._sdk.start()
        if getattr(self._sdk, "card", None) is not None:
            self._card = _coerce_card(self._sdk.card)

    async def stop(self) -> None:
        """Stop/close the underlying Keryx SDK node."""

        await self._sdk.stop()

    async def __aenter__(self) -> Node:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()

    async def get_card(self, peer_id: str) -> AgentCard:
        """Fetch and normalize a peer AgentCard via Keryx discovery."""

        card = await self._sdk.get_card(peer_id)
        return _coerce_card(card)

    async def list_peers(self) -> list[dict[str, Any]]:
        """List peers using Keryx's daemon peer endpoint."""

        return [_normalize_peer(peer) for peer in await self._sdk.list_peers()]

    async def connect_peer(
        self, peer_id: str, addresses: list[str] | None = None
    ) -> dict[str, Any]:
        """AgentAnycast-compatible connect call.

        Keryx routing is daemon/relay-driven and currently has no explicit
        connect-peer RPC.  If the underlying SDK grows one, this delegates to it;
        otherwise it returns an existing peer record or a minimal descriptor.
        """

        if hasattr(self._sdk, "connect_peer"):
            result = await self._sdk.connect_peer(peer_id, addresses)
            return _normalize_peer(result)
        for peer in await self.list_peers():
            if peer.get("peer_id") == peer_id:
                return peer
        return {"peer_id": peer_id, "addresses": list(addresses or [])}

    async def discover(
        self,
        skill: str,
        *,
        tags: dict[str, str] | Sequence[str] | None = None,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """Discover Keryx registrations and normalize to AgentAnycast shape."""

        effective_limit = 10 if limit == 0 else limit
        results = await self._sdk.discover(skill, tags=tags, limit=effective_limit)
        return [_normalize_discovery_result(item) for item in results]

    async def send_task(
        self,
        message: dict[str, Any] | Message | str,
        *,
        peer_id: str | None = None,
        skill: str | None = None,
        url: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> TaskHandle:
        """Send an outbound task through Keryx and return a TaskHandle.

        Keryx's current transport returns a delivery-state response rather than
        an AgentAnycast task update stream.  The returned handle therefore tracks
        the submitted Keryx task id and can cancel via Keryx, but it will only
        transition to a terminal state if a future Keryx SDK provides updates or
        the immediate response itself is terminal.
        """

        _ensure_running(self._sdk)
        targets = sum(item is not None for item in (peer_id, skill, url))
        if targets != 1:
            raise ValueError("Exactly one of peer_id, skill, or url must be provided")
        if url is not None:
            raise NotImplementedError("HTTP bridge outbound is not implemented by Keryx transport")
        if skill is not None:
            discovered = await self.discover(skill, limit=1)
            if not discovered:
                raise RuntimeError(f"no agents found for skill {skill}")
            peer_id = str(discovered[0]["peer_id"])
        if peer_id is None:
            raise ValueError("peer_id is required after routing")

        msg = _normalize_message(message)
        text = _message_text(msg)
        task_id = str(uuid.uuid4())
        client = getattr(self._sdk, "_client", None)
        if client is None:
            # Fall back to the Keryx SDK compatibility method if the private
            # client field changes in a future SDK release.
            handle = await self._sdk.send_task(
                msg,
                peer_id=peer_id,
                metadata=metadata,
            )
            task = _coerce_task(getattr(handle, "_task", None), task_id=handle.task_id, message=msg)
        else:
            response = await client.send_task(
                target_peer_id=peer_id,
                task_id=task_id,
                message_text=text,
                metadata=metadata,
            )
            response_task_id = getattr(getattr(response, "task_id", None), "value", "") or task_id
            task = Task(
                task_id=response_task_id,
                status=_status_from_keryx(getattr(response, "status", "")),
                messages=[msg],
                target_skill_id=skill or "",
                originator_peer_id=getattr(self._sdk, "_peer_id", "") or "",
                metadata={
                    **(metadata or {}),
                    **_response_metadata(response),
                },
            )

        async def cancel_fn() -> None:
            await self._sdk.cancel(task.task_id, reason="client requested cancellation")

        task_handle = TaskHandle(task=task, cancel_fn=cancel_fn)
        self._tasks[task.task_id] = task_handle
        return task_handle

    def on_task(
        self,
        handler: TaskHandler | None = None,
        *,
        timeout: float | None = None,
    ) -> TaskHandler | Callable[[TaskHandler], TaskHandler]:
        """Register an AgentAnycast-style task handler."""

        def _wrap(fn: TaskHandler) -> TaskHandler:
            if timeout is not None:

                async def _guarded(task: IncomingTask) -> None:
                    try:
                        await asyncio.wait_for(fn(task), timeout=timeout)
                    except TimeoutError:
                        await task.fail(f"Handler timed out after {timeout}s")

                self._task_handlers.append(_guarded)
                self._sdk.on_task(_guarded)
                return fn

            self._task_handlers.append(fn)
            self._sdk.on_task(fn)
            return fn

        if handler is not None:
            return _wrap(handler)
        return _wrap

    async def serve_forever(self) -> None:
        """Delegate serving to Keryx's compatibility loop."""

        await self._sdk.serve_forever()

    async def register_skills(
        self,
        card: AgentCard | None = None,
        *,
        capacity: int | None = None,
        current_load: int = 0,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        active_card = card or self._card
        return await self._sdk.register_skills(
            active_card,
            capacity=capacity,
            current_load=current_load,
            ttl_seconds=ttl_seconds,
        )

    async def deregister_skills(self, card: AgentCard | None = None) -> dict[str, Any]:
        return await self._sdk.deregister_skills(card or self._card)

    def __getattr__(self, name: str) -> Any:
        """Expose native Keryx lifecycle methods (submit/claim/complete/etc.)."""

        return getattr(self._sdk, name)


KeryxNode = Node


def _load_sdk_keryx_node() -> type[Any]:
    _ensure_sdk_package_path()
    module_name = "_hermes_agency_keryx_sdk_node"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return getattr(cached, "KeryxNode")

    sdk_node_path = _SDK_PACKAGE_PATH / "node.py"
    if not sdk_node_path.exists():
        raise ImportError(
            "Keryx SDK node.py not found. Set HERMES_KERYX_SDK_PACKAGE to the "
            "Keryx SDK package directory. Expected: "
            f"{sdk_node_path}"
        )

    spec = importlib.util.spec_from_file_location(module_name, sdk_node_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load Keryx SDK node from {sdk_node_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, "KeryxNode")


def _ensure_running(sdk_node: Any) -> None:
    if not getattr(sdk_node, "_running", False):
        raise RuntimeError("Node not started. Call await node.start() first.")


def _coerce_card(value: Any) -> AgentCard:
    if isinstance(value, AgentCard):
        return value
    if isinstance(value, Mapping):
        return AgentCard.from_dict(dict(value))
    if hasattr(value, "to_dict"):
        return AgentCard.from_dict(value.to_dict())
    skills = [_coerce_skill(skill) for skill in getattr(value, "skills", [])]
    return AgentCard(
        name=str(getattr(value, "name", "")),
        description=str(getattr(value, "description", "")),
        version=str(getattr(value, "version", "1.0.0")),
        protocol_version=str(getattr(value, "protocol_version", "a2a/0.3")),
        skills=skills,
        peer_id=getattr(value, "peer_id", None),
        did_key=getattr(value, "did_key", None),
    )


def _coerce_skill(value: Any) -> Skill:
    if isinstance(value, Skill):
        return value
    if isinstance(value, str):
        return Skill(id=value)
    if isinstance(value, Mapping):
        data = dict(value)
        if "id" not in data and "skill_id" in data:
            data["id"] = data["skill_id"]
        return Skill.from_dict(data)
    return Skill(
        id=str(getattr(value, "id", getattr(value, "skill_id", ""))),
        description=str(getattr(value, "description", "")),
    )


def _normalize_message(message: dict[str, Any] | Message | str) -> Message:
    if isinstance(message, Message):
        return message
    if isinstance(message, str):
        return Message(role="user", parts=[Part(text=message)])
    return Message.from_dict(message)


def _message_text(message: Message) -> str:
    texts = [part.text for part in message.parts if part.text]
    return "\n".join(texts)


def _coerce_task(value: Any, *, task_id: str, message: Message) -> Task:
    if isinstance(value, Task):
        return value
    return Task(
        task_id=str(getattr(value, "task_id", task_id)),
        status=_status_from_keryx(getattr(value, "status", "submitted")),
        messages=[message],
    )


def _status_from_keryx(value: Any) -> TaskStatus:
    if isinstance(value, TaskStatus):
        return value
    raw = getattr(value, "value", value)
    status = str(raw or "submitted").lower().removeprefix("task_status_")
    mapping = {
        "created": TaskStatus.SUBMITTED,
        "accepted": TaskStatus.SUBMITTED,
        "queued": TaskStatus.SUBMITTED,
        "awaiting_approval": TaskStatus.SUBMITTED,
        "sent": TaskStatus.SUBMITTED,
        "delivered": TaskStatus.SUBMITTED,
        "submitted": TaskStatus.SUBMITTED,
        "leased": TaskStatus.WORKING,
        "running": TaskStatus.WORKING,
        "working": TaskStatus.WORKING,
        "awaiting_input": TaskStatus.INPUT_REQUIRED,
        "input_required": TaskStatus.INPUT_REQUIRED,
        "completed": TaskStatus.COMPLETED,
        "failed": TaskStatus.FAILED,
        "timed_out": TaskStatus.FAILED,
        "dead_lettered": TaskStatus.FAILED,
        "canceled": TaskStatus.CANCELED,
        "cancelled": TaskStatus.CANCELED,
        "rejected": TaskStatus.REJECTED,
    }
    return mapping.get(status, TaskStatus.SUBMITTED)


def _response_metadata(response: Any) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for field in ("routed_to", "delivery_route", "status"):
        value = getattr(response, field, None)
        if value:
            metadata[f"keryx_{field}"] = str(value)
    return metadata


def _normalize_peer(peer: Any) -> dict[str, Any]:
    if isinstance(peer, Mapping):
        data = dict(peer)
    else:
        data = {
            "peer_id": getattr(peer, "peer_id", ""),
            "connected": getattr(peer, "connected", None),
            "local": getattr(peer, "local", None),
        }
    if "addresses" not in data:
        data["addresses"] = list(data.get("addresses") or [])
    return data


def _normalize_discovery_result(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        data = dict(item)
    else:
        data = {
            "peer_id": getattr(item, "peer_id", ""),
            "agent_name": getattr(item, "agent_name", getattr(item, "name", "")),
            "agent_description": getattr(
                item,
                "agent_description",
                getattr(item, "description", ""),
            ),
            "skills": getattr(item, "skills", []),
        }

    normalized_skills: list[dict[str, str]] = []
    for skill in data.get("skills") or []:
        if isinstance(skill, str):
            normalized_skills.append({"skill_id": skill, "description": ""})
        elif isinstance(skill, Mapping):
            normalized_skills.append(
                {
                    "skill_id": str(skill.get("skill_id") or skill.get("id") or ""),
                    "description": str(skill.get("description") or ""),
                }
            )
        else:
            normalized_skills.append(
                {
                    "skill_id": str(getattr(skill, "skill_id", getattr(skill, "id", ""))),
                    "description": str(getattr(skill, "description", "")),
                }
            )
    data["skills"] = normalized_skills
    data.setdefault("agent_name", data.get("name", ""))
    data.setdefault("agent_description", data.get("description", ""))
    return data


__all__ = ["Node", "KeryxNode", "TaskHandler"]
