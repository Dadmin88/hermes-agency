"""Task, Message, Artifact, and Part data models — A2A compatible."""

from __future__ import annotations

import asyncio
import enum
import json
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

MAX_MESSAGE_TEXT_SIZE = 1 * 1024 * 1024
MAX_PART_PAYLOAD_SIZE = 10 * 1024 * 1024
MAX_METADATA_KEY_LENGTH = 256
MAX_METADATA_VALUE_LENGTH = 4 * 1024
MAX_METADATA_ENTRIES = 128
MAX_PARTS_PER_MESSAGE = 256
MAX_PARTS_PER_ARTIFACT = 256


def _require_mapping(data: Any, model_name: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{model_name}.from_dict expected a dictionary")
    return data


def _validate_metadata(metadata: Any, field_name: str = "metadata") -> dict[str, str] | None:
    if metadata is None:
        return None
    if not isinstance(metadata, Mapping):
        raise ValueError(f"{field_name} must be a dictionary of string keys and values")
    if len(metadata) > MAX_METADATA_ENTRIES:
        raise ValueError(f"{field_name} exceeds maximum count of {MAX_METADATA_ENTRIES}")
    validated: dict[str, str] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{field_name} keys must be non-empty strings")
        if len(key) > MAX_METADATA_KEY_LENGTH:
            raise ValueError(
                f"{field_name} key exceeds maximum length of {MAX_METADATA_KEY_LENGTH} characters"
            )
        if not isinstance(value, str):
            raise ValueError(f"{field_name} values must be strings")
        if len(value) > MAX_METADATA_VALUE_LENGTH:
            raise ValueError(
                f"{field_name} value exceeds maximum length of "
                f"{MAX_METADATA_VALUE_LENGTH} characters"
            )
        validated[key] = value
    return validated


def _validate_text(text: Any) -> str | None:
    if text is None:
        return None
    if not isinstance(text, str):
        raise ValueError("Part text must be a string")
    if len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_SIZE:
        raise ValueError(f"Part text exceeds maximum size of {MAX_MESSAGE_TEXT_SIZE} bytes")
    return text


def _validate_data(data: Any) -> dict[str, Any] | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("Part data must be a dictionary")
    try:
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Part data must be JSON-serializable") from exc
    if len(encoded) > MAX_PART_PAYLOAD_SIZE:
        raise ValueError(f"Part data exceeds maximum size of {MAX_PART_PAYLOAD_SIZE} bytes")
    return data


def _validate_url(url: Any) -> str:
    if not isinstance(url, str) or not url:
        raise ValueError("Part url must be a non-empty string")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Part url must be an absolute http or https URL")
    return url


def _validate_raw(raw: Any) -> bytes | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw_bytes = bytes.fromhex(raw)
        except ValueError as exc:
            raise ValueError("Part raw must be valid hex when provided as a string") from exc
    elif isinstance(raw, bytes | bytearray):
        raw_bytes = bytes(raw)
    else:
        raise ValueError("Part raw must be bytes or a hex string")
    if len(raw_bytes) > MAX_PART_PAYLOAD_SIZE:
        raise ValueError(f"Part raw exceeds maximum size of {MAX_PART_PAYLOAD_SIZE} bytes")
    return raw_bytes


def _validate_parts(raw_parts: Any, model_name: str, max_parts: int) -> list[Part]:
    if raw_parts is None:
        return []
    if not isinstance(raw_parts, list):
        raise ValueError(f"{model_name} parts must be a list")
    if len(raw_parts) > max_parts:
        raise ValueError(f"{model_name} parts exceeds maximum count of {max_parts}")
    return [Part.from_dict(part) for part in raw_parts]


class TaskStatus(enum.Enum):
    """A2A task lifecycle states."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
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

    @classmethod
    def from_value(cls, value: str) -> TaskStatus:
        try:
            return cls(value)
        except ValueError as exc:
            allowed = ", ".join(status.value for status in cls)
            raise ValueError(f"TaskStatus must be one of: {allowed}") from exc


@dataclass
class Part:
    """The smallest content unit in a message or artifact."""

    text: str | None = None
    data: dict[str, Any] | None = None
    url: str | None = None
    raw: bytes | None = None
    media_type: str | None = None
    metadata: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.text is not None:
            d["text"] = self.text
        if self.data is not None:
            d["data"] = self.data
        if self.url is not None:
            d["url"] = self.url
        if self.raw is not None:
            d["raw"] = self.raw.hex()
        if self.media_type:
            d["media_type"] = self.media_type
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Part:
        data = _require_mapping(data, "Part")
        media_type = data.get("media_type")
        if media_type is not None and not isinstance(media_type, str):
            raise ValueError("Part media_type must be a string")
        return cls(
            text=_validate_text(data.get("text")),
            data=_validate_data(data.get("data")),
            url=_validate_url(data["url"]) if "url" in data else None,
            raw=_validate_raw(data.get("raw")),
            media_type=media_type,
            metadata=_validate_metadata(data.get("metadata")),
        )


@dataclass
class Message:
    """A communication turn between agents."""

    role: str  # "user" or "agent"
    parts: list[Part] = field(default_factory=list)
    message_id: str = ""
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "parts": [p.to_dict() for p in self.parts],
            "message_id": self.message_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        data = _require_mapping(data, "Message")
        role = data.get("role")
        if role not in {"user", "agent"}:
            raise ValueError("Message role must be 'user' or 'agent'")
        parts = _validate_parts(data.get("parts", []), "Message", MAX_PARTS_PER_MESSAGE)
        message_id = data.get("message_id", "")
        if not isinstance(message_id, str):
            raise ValueError("Message message_id must be a string")
        return cls(
            role=role,
            parts=parts,
            message_id=message_id,
        )


@dataclass
class Artifact:
    """A concrete output generated by an agent."""

    artifact_id: str = ""
    name: str = ""
    parts: list[Part] = field(default_factory=list)
    metadata: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "parts": [p.to_dict() for p in self.parts],
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Artifact:
        data = _require_mapping(data, "Artifact")
        parts = _validate_parts(data.get("parts", []), "Artifact", MAX_PARTS_PER_ARTIFACT)
        artifact_id = data.get("artifact_id", "")
        if not isinstance(artifact_id, str):
            raise ValueError("Artifact artifact_id must be a string")
        name = data.get("name", "")
        if not isinstance(name, str):
            raise ValueError("Artifact name must be a string")
        return cls(
            artifact_id=artifact_id,
            name=name,
            parts=parts,
            metadata=_validate_metadata(data.get("metadata"), "Artifact metadata"),
        )


@dataclass
class Task:
    """Represents a complete A2A task with all state."""

    task_id: str
    context_id: str = ""
    status: TaskStatus = TaskStatus.SUBMITTED
    messages: list[Message] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    target_skill_id: str = ""
    originator_peer_id: str = ""
    metadata: dict[str, str] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskHandle:
    """Handle for tracking a remote task's progress.

    Returned by Node.send_task(). Allows waiting for completion,
    checking status, and canceling.
    """

    def __init__(self, task: Task, cancel_fn: Callable[[], Coroutine[Any, Any, None]]) -> None:
        self._task = task
        self._cancel_fn = cancel_fn
        self._done_event = asyncio.Event()
        if task.status.is_terminal:
            self._done_event.set()

    @property
    def task_id(self) -> str:
        return self._task.task_id

    @property
    def status(self) -> TaskStatus:
        return self._task.status

    @property
    def artifacts(self) -> list[Artifact]:
        return self._task.artifacts

    def _update(self, status: TaskStatus, artifacts: list[Artifact] | None = None) -> None:
        """Called internally when a status update is received from the daemon."""
        self._task.status = status
        if artifacts:
            self._task.artifacts = artifacts
        if status.is_terminal:
            self._done_event.set()

    async def wait(self, timeout: float | None = None) -> Task:
        """Wait for the task to reach a terminal state.

        Args:
            timeout: Maximum seconds to wait. None means wait forever.

        Returns:
            The completed Task.

        Raises:
            TaskTimeoutError: If timeout is exceeded.
            TaskFailedError: If the task failed.
            TaskCanceledError: If the task was canceled.
            TaskRejectedError: If the task was rejected.
        """
        from agentanycast.exceptions import (
            TaskCanceledError,
            TaskFailedError,
            TaskRejectedError,
            TaskTimeoutError,
        )

        try:
            await asyncio.wait_for(self._done_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TaskTimeoutError(f"Task {self.task_id} timed out after {timeout}s")

        if self._task.status == TaskStatus.FAILED:
            raise TaskFailedError(f"Task {self.task_id} failed")
        if self._task.status == TaskStatus.CANCELED:
            raise TaskCanceledError(f"Task {self.task_id} was canceled")
        if self._task.status == TaskStatus.REJECTED:
            raise TaskRejectedError(f"Task {self.task_id} was rejected")

        return self._task

    async def cancel(self) -> None:
        """Request cancellation of this task."""
        await self._cancel_fn()


class IncomingTask:
    """A task received from a remote agent for local processing.

    Provides methods to update status, complete, or fail the task.
    """

    def __init__(
        self,
        task: Task,
        sender_card: Any | None,
        update_fn: Callable[
            [str, TaskStatus, list[Artifact] | None, str | None],
            Coroutine[Any, Any, None],
        ],
    ) -> None:
        self._task = task
        self.sender_card = sender_card
        self._update_fn = update_fn

    @property
    def task_id(self) -> str:
        return self._task.task_id

    @property
    def peer_id(self) -> str:
        return self._task.originator_peer_id

    @property
    def messages(self) -> list[Message]:
        return self._task.messages

    @property
    def target_skill_id(self) -> str:
        return self._task.target_skill_id

    async def update_status(self, status: str) -> None:
        """Update the task status (e.g., 'working')."""
        ts = TaskStatus.from_value(status)
        await self._update_fn(self.task_id, ts, None, None)

    async def complete(
        self,
        artifacts: list[dict[str, Any]] | list[Artifact] | None = None,
    ) -> None:
        """Mark the task as completed with optional artifacts."""
        parsed: list[Artifact] = []
        if artifacts:
            for a in artifacts:
                if isinstance(a, Artifact):
                    parsed.append(a)
                else:
                    parsed.append(Artifact.from_dict(a))
        await self._update_fn(self.task_id, TaskStatus.COMPLETED, parsed, None)

    async def fail(self, error: str) -> None:
        """Mark the task as failed."""
        await self._update_fn(self.task_id, TaskStatus.FAILED, None, error)

    async def request_input(self, message: dict[str, Any] | Message | None = None) -> None:
        """Request additional input from the client.

        Args:
            message: Optional message describing what input is needed.
        """
        msg_text: str | None = None
        if message is not None:
            if isinstance(message, Message):
                texts = [p.text for p in message.parts if p.text]
                msg_text = " ".join(texts) if texts else None
            elif isinstance(message, dict):
                parts = message.get("parts", [])
                texts = [p.get("text", "") for p in parts if p.get("text")]
                msg_text = " ".join(texts) if texts else None
        await self._update_fn(self.task_id, TaskStatus.INPUT_REQUIRED, None, msg_text)
