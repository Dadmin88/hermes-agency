"""Lifecycle manager for a per-profile AgentAnycast node.

Phase 3 owns the runtime lifecycle:

- create an AgentAnycast ``Node`` from the generated profile AgentCard
- use ``$HERMES_HOME/.agentanycast`` as the per-profile daemon home by default
- start the SDK node and store its peer ID / DID
- keep ``serve_forever()`` running as a background task for incoming events
- stop the node cleanly on explicit stop, session hooks, or process exit

The SDK uses asyncio gRPC channels, so this manager owns a dedicated background
asyncio loop. Tool calls and plugin hooks are synchronous in Hermes; routing all
node operations through one loop avoids creating a node on an ``asyncio.run``
loop that closes immediately after startup.
"""

from __future__ import annotations

import asyncio
import atexit
import threading
import time
from collections import deque
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from .card_builder import build_card, card_to_dict
from .config import AgentAnycastConfig, get_config


@dataclass
class NodeState:
    """Serializable state for the active profile's AgentAnycast node."""

    started: bool = False
    peer_id: str | None = None
    last_peer_id: str | None = None
    did_key: str | None = None
    error: str | None = None
    config: AgentAnycastConfig = field(default_factory=get_config)
    card_name: str | None = None
    skill_count: int = 0
    serve_task_running: bool = False
    started_at: float | None = None
    stopped_at: float | None = None
    last_status: str | None = None
    incoming_task_count: int = 0
    incoming_queue_size: int = 0
    incoming_processing_count: int = 0
    incoming_completed_count: int = 0
    incoming_failed_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "peer_id": self.peer_id,
            "last_peer_id": self.last_peer_id,
            "did_key": self.did_key,
            "error": self.error,
            "config": self.config.as_dict(),
            "card_name": self.card_name,
            "skill_count": self.skill_count,
            "serve_task_running": self.serve_task_running,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "last_status": self.last_status,
            "incoming_task_count": self.incoming_task_count,
            "incoming_queue_size": self.incoming_queue_size,
            "incoming_processing_count": self.incoming_processing_count,
            "incoming_completed_count": self.incoming_completed_count,
            "incoming_failed_count": self.incoming_failed_count,
        }


@dataclass
class IncomingTaskRecord:
    """Serializable local queue/registry record for an incoming A2A task."""

    task_id: str
    sender_peer_id: str
    sender_card: dict[str, Any] | None
    target_skill_id: str
    message_text: str
    status: str = "received"
    result_text: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "sender_peer_id": self.sender_peer_id,
            "sender_card": self.sender_card,
            "target_skill_id": self.target_skill_id,
            "message_text": self.message_text,
            "status": self.status,
            "result_text": self.result_text,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


class NodeManager:
    """Singleton wrapper around a profile-scoped AgentAnycast Node."""

    def __init__(self) -> None:
        self._node: Any | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._incoming_queue: asyncio.Queue[Any] | None = None
        self._incoming_worker_task: asyncio.Task[None] | None = None
        self._incoming_records: dict[str, IncomingTaskRecord] = {}
        self._incoming_order: deque[str] = deque()
        self._task_handles: dict[str, Any] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._thread_ready = threading.Event()
        self._thread_lock = threading.RLock()
        self._start_future: Any | None = None
        self.state = NodeState()
        atexit.register(self._atexit_stop)

    # ------------------------------------------------------------------
    # Dedicated event loop plumbing
    # ------------------------------------------------------------------

    def _loop_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._thread_lock:
            self._loop = loop
            self._thread_ready.set()
        try:
            loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._thread_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            self._thread_ready.clear()
            self._thread = threading.Thread(
                target=self._loop_main,
                name="agentanycast-node-loop",
                daemon=True,
            )
            self._thread.start()

        if not self._thread_ready.wait(timeout=10):
            raise RuntimeError("Timed out starting AgentAnycast lifecycle loop")
        assert self._loop is not None
        return self._loop

    def _submit(self, coro: Coroutine[Any, Any, Any], timeout: float = 120) -> Any:
        loop = self._ensure_loop()
        if threading.current_thread() is self._thread:
            raise RuntimeError("Cannot synchronously wait on the AgentAnycast loop thread")
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    def _stop_loop_if_idle(self) -> None:
        with self._thread_lock:
            loop = self._loop
            thread = self._thread
            if loop is None or self.state.started:
                return
            loop.call_soon_threadsafe(loop.stop)

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10)
        with self._thread_lock:
            self._loop = None
            self._thread = None
            self._thread_ready.clear()

    # ------------------------------------------------------------------
    # Lifecycle implementation (runs on the dedicated event loop)
    # ------------------------------------------------------------------

    def _status_callback(self, message: str) -> None:
        self.state.last_status = message

    def _record_card_state(self, card: Any) -> None:
        data = card_to_dict(card)
        self.state.card_name = data.get("name")
        self.state.skill_count = len(data.get("skills") or [])

    @staticmethod
    def _serialize_part(part: Any) -> dict[str, Any]:
        if hasattr(part, "to_dict"):
            return part.to_dict()
        if isinstance(part, dict):
            return part
        return {"text": str(part)}

    @classmethod
    def _serialize_artifact(cls, artifact: Any) -> dict[str, Any]:
        if hasattr(artifact, "to_dict"):
            return artifact.to_dict()
        if isinstance(artifact, dict):
            return artifact
        return {"name": str(artifact), "parts": []}

    @classmethod
    def _artifact_text(cls, artifact: Any) -> str:
        data = cls._serialize_artifact(artifact)
        texts: list[str] = []
        for part in data.get("parts") or []:
            part_data = cls._serialize_part(part)
            text = part_data.get("text")
            if text:
                texts.append(str(text))
        return "\n".join(texts)

    @classmethod
    def _serialize_task(cls, task: Any) -> dict[str, Any]:
        status = getattr(task, "status", "")
        status_value = getattr(status, "value", str(status))
        artifacts = [cls._serialize_artifact(item) for item in getattr(task, "artifacts", [])]
        return {
            "task_id": getattr(task, "task_id", ""),
            "context_id": getattr(task, "context_id", ""),
            "status": status_value,
            "target_skill_id": getattr(task, "target_skill_id", ""),
            "originator_peer_id": getattr(task, "originator_peer_id", ""),
            "artifacts": artifacts,
            "artifact_text": "\n".join(
                text for text in (cls._artifact_text(item) for item in artifacts) if text
            ),
            "metadata": getattr(task, "metadata", None) or {},
        }

    @classmethod
    def _serialize_handle(cls, handle: Any) -> dict[str, Any]:
        task = getattr(handle, "_task", None)
        if task is not None:
            return cls._serialize_task(task)
        status = getattr(handle, "status", "")
        return {
            "task_id": getattr(handle, "task_id", ""),
            "status": getattr(status, "value", str(status)),
            "artifacts": [cls._serialize_artifact(item) for item in getattr(handle, "artifacts", [])],
        }

    async def _ensure_started_impl(self) -> None:
        if self._node is None or not self.state.started:
            await self._start_impl()
        if self._node is None or not self.state.started:
            raise RuntimeError(self.state.error or "AgentAnycast node did not start")

    @staticmethod
    def _message_text_from_incoming(task: Any) -> str:
        texts: list[str] = []
        for message in getattr(task, "messages", []) or []:
            for part in getattr(message, "parts", []) or []:
                text = getattr(part, "text", None)
                if text:
                    texts.append(str(text))
        return "\n".join(texts)

    def _sender_card_to_dict(self, task: Any) -> dict[str, Any] | None:
        sender_card = getattr(task, "sender_card", None)
        if sender_card is None:
            return None
        try:
            return card_to_dict(sender_card)
        except Exception:
            return {"name": getattr(sender_card, "name", ""), "description": getattr(sender_card, "description", "")}

    def _refresh_incoming_state(self) -> None:
        queue_size = self._incoming_queue.qsize() if self._incoming_queue is not None else 0
        records = list(self._incoming_records.values())
        self.state.incoming_task_count = len(records)
        self.state.incoming_queue_size = queue_size
        self.state.incoming_processing_count = sum(1 for item in records if item.status == "processing")
        self.state.incoming_completed_count = sum(1 for item in records if item.status == "completed")
        self.state.incoming_failed_count = sum(1 for item in records if item.status == "failed")

    def _remember_incoming_record(self, record: IncomingTaskRecord) -> None:
        cfg = get_config()
        self._incoming_records[record.task_id] = record
        self._incoming_order.append(record.task_id)
        while len(self._incoming_order) > cfg.incoming_queue_limit:
            old_task_id = self._incoming_order.popleft()
            self._incoming_records.pop(old_task_id, None)
        self._refresh_incoming_state()

    async def _handle_incoming_task(self, task: Any) -> None:
        """Queue an incoming remote task and mark it working immediately."""

        record = IncomingTaskRecord(
            task_id=task.task_id,
            sender_peer_id=getattr(task, "peer_id", ""),
            sender_card=self._sender_card_to_dict(task),
            target_skill_id=getattr(task, "target_skill_id", ""),
            message_text=self._message_text_from_incoming(task),
        )
        self._remember_incoming_record(record)
        try:
            await task.update_status("working")
            record.status = "queued"
            record.updated_at = time.time()
            if self._incoming_queue is None:
                raise RuntimeError("Incoming queue is not initialized")
            await self._incoming_queue.put((task, record.task_id))
            self._refresh_incoming_state()
        except Exception as exc:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
            record.updated_at = time.time()
            record.completed_at = time.time()
            self._refresh_incoming_state()
            try:
                await task.fail(record.error)
            except Exception:
                pass

    def _safe_stub_response(self, record: IncomingTaskRecord) -> str:
        cfg = get_config()
        trusted = not cfg.trusted_peers or record.sender_peer_id in cfg.trusted_peers
        return (
            f"AgentAnycast safe stub on profile '{self.state.card_name or 'unknown'}' "
            f"received task {record.task_id} from {record.sender_peer_id or 'unknown peer'}.\n"
            f"Target skill: {record.target_skill_id or '(none)'}\n"
            f"Message:\n{record.message_text or '(empty)'}\n\n"
            "No Hermes tools, terminal commands, file edits, or live conversation injection were executed. "
            f"allow_remote_tasks={cfg.allow_remote_tasks}; trusted_peer={trusted}."
        )

    async def _incoming_worker(self) -> None:
        """Process queued incoming tasks with a deterministic safe stub."""

        assert self._incoming_queue is not None
        while True:
            task, task_id = await self._incoming_queue.get()
            record = self._incoming_records.get(task_id)
            try:
                if record is None:
                    continue
                record.status = "processing"
                record.updated_at = time.time()
                self._refresh_incoming_state()
                response = self._safe_stub_response(record)
                await task.complete(
                    artifacts=[
                        {
                            "artifact_id": f"safe-stub-{record.task_id}",
                            "name": "agentanycast-safe-stub-response",
                            "parts": [{"text": response}],
                        }
                    ]
                )
                record.status = "completed"
                record.result_text = response
                record.updated_at = time.time()
                record.completed_at = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if record is not None:
                    record.status = "failed"
                    record.error = f"{type(exc).__name__}: {exc}"
                    record.updated_at = time.time()
                    record.completed_at = time.time()
                try:
                    await task.fail(record.error if record is not None else f"{type(exc).__name__}: {exc}")
                except Exception:
                    pass
            finally:
                self._incoming_queue.task_done()
                self._refresh_incoming_state()

    async def _start_impl(self) -> NodeState:
        if self._node is not None and self.state.started:
            return self.state

        cfg = get_config()
        self.state.config = cfg
        self.state.error = None
        self.state.last_status = None

        if cfg.home:
            cfg.home.mkdir(parents=True, exist_ok=True)

        try:
            from agentanycast import Node

            card = build_card()
            self._record_card_state(card)
            node = Node(
                card=card,
                relay=cfg.relay,
                home=cfg.home,
                status_callback=self._status_callback,
            )
            node.on_task(self._handle_incoming_task)
            await node.start()

            self._node = node
            self.state.started = True
            self.state.peer_id = node.peer_id
            self.state.last_peer_id = node.peer_id
            self.state.did_key = self._peer_id_to_did_key(node.peer_id)
            self.state.started_at = time.time()
            self.state.stopped_at = None
            self.state.error = None

            self._incoming_queue = asyncio.Queue()
            self._incoming_worker_task = asyncio.create_task(self._incoming_worker())
            self._serve_task = asyncio.create_task(node.serve_forever())
            self._serve_task.add_done_callback(self._serve_done)
            self.state.serve_task_running = True
        except Exception as exc:
            self._node = None
            self._serve_task = None
            self.state.started = False
            self.state.peer_id = None
            self.state.serve_task_running = False
            self.state.error = f"{type(exc).__name__}: {exc}"
        return self.state

    async def _stop_impl(self) -> NodeState:
        try:
            if self._serve_task is not None and not self._serve_task.done():
                self._serve_task.cancel()
                await asyncio.gather(self._serve_task, return_exceptions=True)

            if self._incoming_worker_task is not None and not self._incoming_worker_task.done():
                self._incoming_worker_task.cancel()
                await asyncio.gather(self._incoming_worker_task, return_exceptions=True)

            if self._node is not None:
                await self._node.stop()
        except Exception as exc:
            self.state.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._serve_task = None
            self._incoming_worker_task = None
            self._incoming_queue = None
            self._node = None
            self._task_handles.clear()
            self.state.started = False
            self.state.peer_id = None
            self.state.serve_task_running = False
            self.state.stopped_at = time.time()
            self._refresh_incoming_state()
        return self.state

    async def _list_peers_impl(self) -> list[dict[str, Any]]:
        if self._node is None or not self.state.started:
            return []
        return await self._node.list_peers()

    async def _discover_impl(
        self,
        skill: str,
        tags: dict[str, str] | None = None,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        await self._ensure_started_impl()
        assert self._node is not None
        return await self._node.discover(
            skill=skill,
            tags={str(k): str(v) for k, v in (tags or {}).items()} or None,
            limit=limit,
        )

    async def _send_task_impl(
        self,
        message: str,
        *,
        peer_id: str | None = None,
        skill: str | None = None,
        wait_seconds: float = 0,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_started_impl()
        assert self._node is not None

        targets = sum(bool(item) for item in (peer_id, skill))
        if targets != 1:
            raise ValueError("Exactly one of peer_id or skill is required")

        payload = {"role": "user", "parts": [{"text": message}]}
        clean_metadata = {str(k): str(v) for k, v in (metadata or {}).items()} or None
        handle = await self._node.send_task(
            message=payload,
            peer_id=peer_id,
            skill=skill,
            metadata=clean_metadata,
        )
        self._task_handles[handle.task_id] = handle

        wait_error: str | None = None
        if wait_seconds and wait_seconds > 0:
            try:
                await handle.wait(timeout=wait_seconds)
            except Exception as exc:
                # Timeout or remote failure should not erase the task handle;
                # callers can still poll a2a_status for the latest state.
                wait_error = f"{type(exc).__name__}: {exc}"

        data = self._serialize_handle(handle)
        if wait_error:
            data["wait_error"] = wait_error
        return data

    async def _task_status_impl(self, task_id: str) -> dict[str, Any] | None:
        handle = self._task_handles.get(task_id)
        if handle is None:
            return None
        return self._serialize_handle(handle)

    async def _incoming_tasks_impl(self, limit: int = 20) -> list[dict[str, Any]]:
        self._refresh_incoming_state()
        task_ids = list(self._incoming_order)[-max(1, limit):]
        return [
            self._incoming_records[task_id].as_dict()
            for task_id in reversed(task_ids)
            if task_id in self._incoming_records
        ]

    def _serve_done(self, task: asyncio.Task[None]) -> None:
        self.state.serve_task_running = False
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            self.state.error = f"serve_forever failed: {type(exc).__name__}: {exc}"

    @staticmethod
    def _peer_id_to_did_key(peer_id: str) -> str | None:
        try:
            from agentanycast import peer_id_to_did_key

            return peer_id_to_did_key(peer_id)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public synchronous surface for Hermes tools/hooks
    # ------------------------------------------------------------------

    def start_sync(self, timeout: float = 120) -> NodeState:
        return self._submit(self._start_impl(), timeout=timeout)

    def stop_sync(self, timeout: float = 60) -> NodeState:
        try:
            return self._submit(self._stop_impl(), timeout=timeout)
        finally:
            self._stop_loop_if_idle()

    def list_peers_sync(self, timeout: float = 30) -> list[dict[str, Any]]:
        if not self.state.started:
            return []
        return self._submit(self._list_peers_impl(), timeout=timeout)

    def discover_sync(
        self,
        skill: str,
        tags: dict[str, str] | None = None,
        limit: int = 0,
        timeout: float = 60,
    ) -> list[dict[str, Any]]:
        return self._submit(self._discover_impl(skill, tags=tags, limit=limit), timeout=timeout)

    def send_task_sync(
        self,
        message: str,
        *,
        peer_id: str | None = None,
        skill: str | None = None,
        wait_seconds: float = 0,
        metadata: dict[str, str] | None = None,
        timeout: float = 120,
    ) -> dict[str, Any]:
        effective_timeout = max(timeout, wait_seconds + 30 if wait_seconds else timeout)
        return self._submit(
            self._send_task_impl(
                message,
                peer_id=peer_id,
                skill=skill,
                wait_seconds=wait_seconds,
                metadata=metadata,
            ),
            timeout=effective_timeout,
        )

    def task_status_sync(self, task_id: str, timeout: float = 30) -> dict[str, Any] | None:
        return self._submit(self._task_status_impl(task_id), timeout=timeout)

    def incoming_tasks_sync(self, limit: int = 20, timeout: float = 30) -> list[dict[str, Any]]:
        if self._loop is None or not self._loop.is_running():
            self._refresh_incoming_state()
            task_ids = list(self._incoming_order)[-max(1, limit):]
            return [
                self._incoming_records[task_id].as_dict()
                for task_id in reversed(task_ids)
                if task_id in self._incoming_records
            ]
        return self._submit(self._incoming_tasks_impl(limit=limit), timeout=timeout)

    def start_background(self) -> None:
        """Kick off startup without blocking the caller.

        Used by plugin lifecycle hooks. If startup fails, ``state.error`` is
        populated by ``_background_start_done``.
        """

        if self.state.started or self._start_future is not None:
            return
        loop = self._ensure_loop()
        self._start_future = asyncio.run_coroutine_threadsafe(self._start_impl(), loop)
        self._start_future.add_done_callback(self._background_start_done)

    def stop_background(self) -> None:
        if not self.state.started and self._node is None:
            return
        try:
            self.stop_sync(timeout=60)
        except Exception as exc:
            self.state.error = f"{type(exc).__name__}: {exc}"

    def _background_start_done(self, future: Any) -> None:
        self._start_future = None
        try:
            future.result()
        except Exception as exc:
            self.state.error = f"{type(exc).__name__}: {exc}"

    def info(self) -> dict[str, Any]:
        self.state.config = get_config()
        if self._serve_task is not None:
            self.state.serve_task_running = not self._serve_task.done()
        self._refresh_incoming_state()
        return self.state.as_dict()

    def auto_start_if_configured(self) -> None:
        cfg = get_config()
        self.state.config = cfg
        if cfg.enabled and cfg.auto_start:
            self.start_background()

    def _atexit_stop(self) -> None:
        self.stop_background()


manager = NodeManager()


def start_node() -> NodeState:
    """Start the active Hermes profile's AgentAnycast node synchronously."""

    return manager.start_sync()


def stop_node() -> NodeState:
    """Stop the active Hermes profile's AgentAnycast node synchronously."""

    return manager.stop_sync()
