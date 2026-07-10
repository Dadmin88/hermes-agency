"""Task models used by the Keryx node client."""

from __future__ import annotations

import asyncio
import enum
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any


class TaskStatus(enum.Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELED,
            TaskStatus.REJECTED,
        )


@dataclass
class Part:
    text: str | None = None
    raw: bytes = b""
    media_type: str = "text/plain"
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Part:
        if not isinstance(data, dict):
            raise ValueError("Part.from_dict expected a dictionary")
        text = data.get("text")
        if text is not None and not isinstance(text, str):
            raise ValueError("Part text must be a string")
        raw = data.get("raw") or b""
        if not isinstance(raw, bytes):
            raise ValueError("Part raw content must be bytes")
        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("Part metadata must be a dictionary")
        return cls(
            text=text,
            raw=raw,
            media_type=str(data.get("media_type") or "text/plain"),
            metadata={str(key): str(value) for key, value in metadata.items()},
        )


@dataclass
class Message:
    role: str = "user"
    parts: list[Part] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class Artifact:
    artifact_id: str = ""
    name: str = ""
    parts: list[Part] = field(default_factory=list)


@dataclass
class Task:
    task_id: str
    context_id: str = ""
    status: TaskStatus = TaskStatus.SUBMITTED
    messages: list[Message] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    target_skill_id: str = ""
    originator_peer_id: str = ""
    metadata: dict[str, str] | None = None


class TaskHandle:
    def __init__(
        self,
        task: Task,
        cancel_fn: Callable[[], Coroutine[Any, Any, None]] | None = None,
        refresh_fn: Callable[[], Coroutine[Any, Any, Task]] | None = None,
        *,
        poll_interval: float = 0.1,
        max_poll_interval: float = 1.0,
    ) -> None:
        self._task = task
        self._cancel_fn = cancel_fn
        self._refresh_fn = refresh_fn
        self._poll_interval = max(0.01, poll_interval)
        self._max_poll_interval = max(self._poll_interval, max_poll_interval)
        self._done = asyncio.Event()
        if task.status.is_terminal:
            self._done.set()

    @property
    def task_id(self) -> str:
        return self._task.task_id

    @property
    def status(self) -> TaskStatus:
        return self._task.status

    async def refresh(self) -> Task:
        if self._refresh_fn is not None and not self._task.status.is_terminal:
            self._task = await self._refresh_fn()
            if self._task.status.is_terminal:
                self._done.set()
        return self._task

    async def wait(self, timeout: float | None = None) -> Task:
        if self._refresh_fn is None:
            await asyncio.wait_for(self._done.wait(), timeout=timeout)
            return self._task

        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        delay = self._poll_interval
        while True:
            await self.refresh()
            if self._task.status.is_terminal:
                return self._task
            if deadline is not None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError
                await asyncio.sleep(min(delay, remaining))
            else:
                await asyncio.sleep(delay)
            delay = min(self._max_poll_interval, delay * 1.5)

    async def cancel(self) -> None:
        if self._cancel_fn is not None:
            await self._cancel_fn()
        await self.refresh()


class IncomingTask:
    def __init__(
        self,
        task: Task,
        sender_card: Any | None,
        update_fn: Callable[[str, TaskStatus, list[Artifact] | None, str | None], Coroutine[Any, Any, None]],
        *,
        lease_id: str = "",
        worker_id: str = "",
        sender_peer_id: str = "",
    ) -> None:
        self._task = task
        self.sender_card = sender_card
        self._update_fn = update_fn
        self._lease_id = lease_id
        self._worker_id = worker_id
        self._sender_peer_id = sender_peer_id
        self._terminal = asyncio.Event()
        self._terminal_lock = asyncio.Lock()

    @property
    def task_id(self) -> str:
        return self._task.task_id

    @property
    def context_id(self) -> str:
        return self._task.context_id

    @property
    def messages(self) -> list[Message]:
        return self._task.messages

    @property
    def metadata(self) -> dict[str, str]:
        return dict(self._task.metadata or {})

    @property
    def target_skill_id(self) -> str:
        return self._task.target_skill_id

    @property
    def peer_id(self) -> str:
        return self._sender_peer_id or self._task.originator_peer_id

    @property
    def lease_id(self) -> str:
        return self._lease_id

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def status(self) -> TaskStatus:
        return self._task.status

    @property
    def is_terminal(self) -> bool:
        return self._terminal.is_set()

    async def wait_terminal(self) -> TaskStatus:
        await self._terminal.wait()
        return self._task.status

    async def update_status(self, status: str | TaskStatus) -> None:
        resolved = status if isinstance(status, TaskStatus) else TaskStatus(str(status).lower())
        if resolved in (TaskStatus.SUBMITTED, TaskStatus.WORKING):
            self._task.status = resolved
            return
        if resolved == TaskStatus.COMPLETED:
            await self.complete()
            return
        await self.fail(f"task marked {resolved.value}")

    async def complete(self, artifacts: list[Artifact] | None = None) -> None:
        async with self._terminal_lock:
            if self._terminal.is_set():
                return
            await self._update_fn(self.task_id, TaskStatus.COMPLETED, artifacts, None)
            self._task.status = TaskStatus.COMPLETED
            self._task.artifacts = list(artifacts or [])
            self._terminal.set()

    async def fail(self, error: str) -> None:
        async with self._terminal_lock:
            if self._terminal.is_set():
                return
            await self._update_fn(self.task_id, TaskStatus.FAILED, None, error)
            self._task.status = TaskStatus.FAILED
            self._terminal.set()