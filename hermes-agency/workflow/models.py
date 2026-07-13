"""Immutable, serializable domain records for deterministic workflow governance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Any


def freeze(value: Any) -> Any:
    """Recursively freeze JSON-like input so callers cannot mutate state in place."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        raise TypeError("sets are not supported in deterministic workflow state")
    return value


def thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


class WorkflowStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    NEEDS_OPERATOR = "needs_operator"


class RevisionStatus(StrEnum):
    ACTIVE = "active"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    NEEDS_OPERATOR = "needs_operator"
    SUPERSEDED = "superseded"


class GateKind(StrEnum):
    AUTHOR = "author"
    COMPLETENESS_QA = "completeness_qa"
    FREEZE = "freeze"
    FEASIBILITY_REVIEW = "feasibility_review"
    SECURITY_REVIEW = "security_review"
    IMPLEMENTATION_APPROVAL = "implementation_approval"
    ARCHIVE_REJECTION = "archive_rejection"
    OPERATOR_ESCALATION = "operator_escalation"


class GateStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    SKIPPED = "skipped"


class VerdictDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class OperatorDecisionStatus(StrEnum):
    REQUESTED = "requested"
    RESOLVED = "resolved"


class EventType(StrEnum):
    GATE_STARTED = "gate_started"
    GATE_COMPLETED = "gate_completed"
    ARTIFACT_FROZEN = "artifact_frozen"
    REVIEW_VERDICT_ISSUED = "review_verdict_issued"
    OPERATIONAL_FAILURE_RECORDED = "operational_failure_recorded"
    OPERATOR_INPUT_REQUIRED = "operator_input_required"
    SUCCESSOR_REVISION_STARTED = "successor_revision_started"
    METADATA_OBSERVED = "metadata_observed"


@dataclass(frozen=True)
class ArtifactIdentity:
    artifact_id: str
    references: tuple[str, ...] = ()
    hashes: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    byte_sizes: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    frozen: bool = False
    frozen_at: str | None = None
    created_by: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "references", tuple(self.references))
        object.__setattr__(self, "hashes", freeze(self.hashes))
        object.__setattr__(self, "byte_sizes", freeze(self.byte_sizes))


@dataclass(frozen=True)
class ReviewVerdict:
    decision: VerdictDecision
    reviewer: str
    reviewer_role: str
    reviewed_artifact_identity: ArtifactIdentity
    findings: tuple[Any, ...] = ()
    report_reference: str = ""
    report_hash: str = ""
    issued_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision", VerdictDecision(self.decision))
        object.__setattr__(self, "findings", tuple(freeze(item) for item in self.findings))


@dataclass(frozen=True)
class OperatorDecision:
    decision_id: str
    requested_fields: tuple[str, ...]
    supplied_values: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    requested_at: str = ""
    resolved_at: str | None = None
    status: OperatorDecisionStatus = OperatorDecisionStatus.REQUESTED

    def __post_init__(self) -> None:
        object.__setattr__(self, "requested_fields", tuple(self.requested_fields))
        object.__setattr__(self, "supplied_values", freeze(self.supplied_values))
        object.__setattr__(self, "status", OperatorDecisionStatus(self.status))


@dataclass(frozen=True)
class WorkflowGate:
    gate_id: str
    revision_id: str
    kind: GateKind
    status: GateStatus = GateStatus.PENDING
    dependencies: tuple[str, ...] = ()
    assigned_agent: str | None = None
    author_agent: str | None = None
    attempt: int = 0
    max_attempts: int = 1
    controlling: bool = True
    verdict: ReviewVerdict | None = None
    artifact_identity: ArtifactIdentity | None = None
    result: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    error: Mapping[str, Any] | None = None
    started_at: str | None = None
    completed_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", GateKind(self.kind))
        object.__setattr__(self, "status", GateStatus(self.status))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "result", freeze(self.result))
        object.__setattr__(self, "error", freeze(self.error) if self.error is not None else None)


@dataclass(frozen=True)
class WorkflowRevision:
    revision_id: str
    workflow_id: str
    revision_number: int
    status: RevisionStatus = RevisionStatus.ACTIVE
    predecessor_revision_id: str | None = None
    successor_revision_id: str | None = None
    artifact_identity: ArtifactIdentity | None = None
    gates: tuple[WorkflowGate, ...] = ()
    created_at: str = ""
    completed_at: str | None = None
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", RevisionStatus(self.status))
        object.__setattr__(self, "gates", tuple(self.gates))


@dataclass(frozen=True)
class WorkflowRun:
    workflow_id: str
    workflow_type: str
    objective: str
    status: WorkflowStatus = WorkflowStatus.ACTIVE
    active_revision: str | None = None
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", WorkflowStatus(self.status))
        object.__setattr__(self, "metadata", freeze(self.metadata))


@dataclass(frozen=True)
class WorkflowEvent:
    event_id: str
    workflow_id: str
    revision_id: str | None
    gate_id: str | None
    event_type: EventType
    actor: str
    payload: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    occurred_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", EventType(self.event_type))
        object.__setattr__(self, "payload", freeze(self.payload))


@dataclass(frozen=True)
class WorkflowState:
    run: WorkflowRun
    revisions: tuple[WorkflowRevision, ...]
    events: tuple[WorkflowEvent, ...] = ()
    event_digests: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    operator_decisions: tuple[OperatorDecision, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "revisions", tuple(self.revisions))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "event_digests", freeze(self.event_digests))
        object.__setattr__(self, "operator_decisions", tuple(self.operator_decisions))

    def revision(self, revision_id: str) -> WorkflowRevision:
        for revision in self.revisions:
            if revision.revision_id == revision_id:
                return revision
        raise KeyError(revision_id)

    def gate(self, revision_id: str, gate_id: str) -> WorkflowGate:
        for gate in self.revision(revision_id).gates:
            if gate.gate_id == gate_id:
                return gate
        raise KeyError(gate_id)
