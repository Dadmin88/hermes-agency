"""Typed failures raised by the deterministic workflow engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(eq=False)
class WorkflowError(Exception):
    """A diagnosable workflow rule violation."""

    message: str
    code: str = "workflow_error"
    workflow_id: str | None = None
    revision_id: str | None = None
    gate_id: str | None = None
    event_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        context = {
            key: value
            for key, value in {
                "workflow_id": self.workflow_id,
                "revision_id": self.revision_id,
                "gate_id": self.gate_id,
                "event_id": self.event_id,
            }.items()
            if value is not None
        }
        return f"{self.code}: {self.message}" + (f" ({context})" if context else "")


class IllegalTransitionError(WorkflowError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="illegal_transition", **kwargs)


class GraphValidationError(WorkflowError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="invalid_graph", **kwargs)


class EventConflictError(WorkflowError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="event_conflict", **kwargs)


class ReviewerIndependenceError(WorkflowError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="reviewer_independence", **kwargs)


class ArtifactIdentityError(WorkflowError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="artifact_identity", **kwargs)


class VerdictConflictError(WorkflowError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="verdict_conflict", **kwargs)


class SerializationError(WorkflowError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="serialization", **kwargs)
