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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Part:
        if not isinstance(data, dict):
            raise ValueError("Part.from_dict expected a dictionary")
        text = data.get("text")
        if text is not None and not isinstance(text, str):
            raise ValueError("Part text must be a string")
        return cls(text=text)


@dataclass
class Message:
    role: str = "user"
    parts: list[Part] = field(default_factory=list)


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
    def __init__(self, task: Task, cancel_fn: Callable[[], Coroutine[Any, Any, None]] | None = None) -> None:
        self._task = task
        self._cancel_fn = cancel_fn
        self._done = asyncio.Event()
        if task.status.is_terminal:
            self._done.set()

    @property
    def task_id(self) -> str:
        return self._task.task_id

    @property
    def status(self) -> TaskStatus:
        return self._task.status

    async def wait(self, timeout: float | None = None) -> Task:
        await asyncio.wait_for(self._done.wait(), timeout=timeout)
        return self._task

    async def cancel(self) -> None:
        if self._cancel_fn is not None:
            await self._cancel_fn()


class IncomingTask:
    def __init__(
        self,
        task: Task,
        sender_card: Any | None,
        update_fn: Callable[[str, TaskStatus, list[Artifact] | None, str | None], Coroutine[Any, Any, None]],
    ) -> None:
        self._task = task
        self.sender_card = sender_card
        self._update_fn = update_fn

    @property
    def task_id(self) -> str:
        return self._task.task_id

    async def complete(self, artifacts: list[Artifact] | None = None) -> None:
        await self._update_fn(self.task_id, TaskStatus.COMPLETED, artifacts, None)

    async def fail(self, error: str) -> None:
        await self._update_fn(self.task_id, TaskStatus.FAILED, None, error)