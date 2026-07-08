"""Dataclasses mirroring Keryx daemon task proto responses."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROTO_ROOT = Path(__file__).resolve().parent / "proto"
if str(_PROTO_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROTO_ROOT))

from hermes.keryx.v1 import common_pb2, daemon_pb2  # noqa: E402


@dataclass(slots=True)
class TaskArtifact:
    """Artifact descriptor used by CompleteTask RPCs."""

    path: str
    media_type: str = "application/octet-stream"
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_proto(cls, artifact: daemon_pb2.TaskArtifact) -> "TaskArtifact":
        return cls(
            path=artifact.path,
            media_type=artifact.media_type,
            metadata=dict(artifact.metadata),
        )

    def to_proto(self) -> daemon_pb2.TaskArtifact:
        return daemon_pb2.TaskArtifact(
            path=self.path,
            media_type=self.media_type,
            metadata=self.metadata,
        )


@dataclass(slots=True)
class TaskState:
    """State returned by SubmitTask, ClaimTask, and Heartbeat RPCs."""

    task_id: str
    status: str = ""
    lease_id: str = ""
    worker_id: str = ""
    leased_at_ms: int = 0
    expires_at_ms: int = 0
    retry_count: int = 0
    dead_lettered: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_submit(cls, response: daemon_pb2.SubmitTaskResponse) -> "TaskState":
        return cls(
            task_id=_id_value(response.task_id),
            status=response.status,
        )

    @classmethod
    def from_claim(cls, response: daemon_pb2.ClaimTaskResponse) -> "TaskState":
        return cls(
            task_id=_id_value(response.task_id),
            status=response.status,
            lease_id=_id_value(response.lease_id),
            worker_id=_id_value(response.worker_id),
            leased_at_ms=response.leased_at_ms,
            expires_at_ms=response.expires_at_ms,
            retry_count=response.retry_count,
            dead_lettered=response.dead_lettered,
        )

    @classmethod
    def from_heartbeat(
        cls,
        response: daemon_pb2.HeartbeatResponse,
        *,
        task_id: str,
        worker_id: str,
    ) -> "TaskState":
        return cls(
            task_id=task_id,
            lease_id=_id_value(response.lease_id),
            worker_id=worker_id,
            expires_at_ms=response.expires_at_ms,
        )


@dataclass(slots=True)
class TaskResult:
    """Terminal or post-action result returned by lifecycle RPCs."""

    task_id: str
    status: str = ""
    duration_ms: int = 0
    result_metadata: dict[str, str] = field(default_factory=dict)
    output_artifacts: list[TaskArtifact] = field(default_factory=list)
    error_reason: str = ""
    failure_metadata: dict[str, str] = field(default_factory=dict)
    retry_count: int = 0
    dead_lettered: bool = False
    canceled: bool = False
    reason: str = ""

    @classmethod
    def from_complete(cls, response: daemon_pb2.CompleteTaskResponse) -> "TaskResult":
        return cls(
            task_id=_id_value(response.task_id),
            status=response.status,
            duration_ms=response.duration_ms,
            result_metadata=dict(response.result_metadata),
            output_artifacts=[TaskArtifact.from_proto(item) for item in response.output_artifacts],
        )

    @classmethod
    def from_fail(cls, response: daemon_pb2.FailTaskResponse) -> "TaskResult":
        return cls(
            task_id=_id_value(response.task_id),
            status=response.status,
            duration_ms=response.duration_ms,
            error_reason=response.error_reason,
            failure_metadata=dict(response.failure_metadata),
            retry_count=response.retry_count,
            dead_lettered=response.dead_lettered,
        )

    @classmethod
    def from_cancel(cls, response: daemon_pb2.CancelTaskResponse) -> "TaskResult":
        return cls(
            task_id=_id_value(response.task_id),
            status=response.status,
            canceled=response.canceled,
            reason=response.reason,
        )


def _id_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(
        value,
        (
            common_pb2.TaskId,
            common_pb2.LeaseId,
            common_pb2.AgentId,
            common_pb2.NodeId,
            common_pb2.CorrelationId,
            common_pb2.IdempotencyKey,
        ),
    ):
        return value.value
    return getattr(value, "value", "")
