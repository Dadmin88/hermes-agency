"""Built-in deterministic workflow templates."""

from __future__ import annotations

from .events import event, event_digest
from .graph import validate_workflow_graph
from .models import (
    ArtifactIdentity,
    EventType,
    GateKind,
    GateStatus,
    RevisionStatus,
    WorkflowGate,
    WorkflowRevision,
    WorkflowRun,
    WorkflowState,
    WorkflowStatus,
)

ARCHITECTURE_GOVERNANCE = "architecture-governance"
_CANONICAL_MAX_ATTEMPTS = 2


def _creation_event_id(workflow_id: str, revision_id: str) -> str:
    return f"workflow-created:{workflow_id}:{revision_id}"


_ORDER = (
    GateKind.AUTHOR,
    GateKind.COMPLETENESS_QA,
    GateKind.FREEZE,
    GateKind.FEASIBILITY_REVIEW,
    GateKind.SECURITY_REVIEW,
    GateKind.IMPLEMENTATION_APPROVAL,
)


def architecture_governance_revision(
    *,
    workflow_id: str,
    revision_id: str,
    revision_number: int,
    created_at: str,
    author: str,
    artifact_identity: ArtifactIdentity,
    max_attempts: int = 2,
    predecessor_revision_id: str | None = None,
) -> WorkflowRevision:
    """Create the fixed graph without generating IDs or timestamps."""
    if max_attempts != _CANONICAL_MAX_ATTEMPTS:
        raise ValueError("architecture-governance retry policy is fixed at two attempts")
    gates: list[WorkflowGate] = []
    previous: str | None = None
    for kind in _ORDER:
        gate_id = f"{revision_id}:{kind.value}"
        gates.append(
            WorkflowGate(
                gate_id=gate_id,
                revision_id=revision_id,
                kind=kind,
                status=GateStatus.READY if kind is GateKind.AUTHOR else GateStatus.PENDING,
                dependencies=(previous,) if previous else (),
                author_agent=author,
                max_attempts=max_attempts,
                artifact_identity=artifact_identity if kind is GateKind.AUTHOR else None,
            )
        )
        previous = gate_id
    gates.extend(
        (
            WorkflowGate(
                gate_id=f"{revision_id}:{GateKind.ARCHIVE_REJECTION.value}",
                revision_id=revision_id,
                kind=GateKind.ARCHIVE_REJECTION,
                controlling=False,
            ),
            WorkflowGate(
                gate_id=f"{revision_id}:{GateKind.OPERATOR_ESCALATION.value}",
                revision_id=revision_id,
                kind=GateKind.OPERATOR_ESCALATION,
                controlling=False,
            ),
        )
    )
    validate_workflow_graph(gates)
    return WorkflowRevision(
        revision_id=revision_id,
        workflow_id=workflow_id,
        revision_number=revision_number,
        predecessor_revision_id=predecessor_revision_id,
        artifact_identity=artifact_identity,
        gates=tuple(gates),
        created_at=created_at,
    )


def architecture_governance_state(
    *,
    workflow_id: str,
    revision_id: str,
    objective: str,
    created_by: str,
    created_at: str,
    artifact_identity: ArtifactIdentity,
    max_attempts: int = 2,
) -> WorkflowState:
    if max_attempts != _CANONICAL_MAX_ATTEMPTS:
        raise ValueError("architecture-governance retry policy is fixed at two attempts")
    if artifact_identity.frozen or artifact_identity.frozen_at:
        raise ValueError("workflow creation requires an unfrozen artifact identity")
    if artifact_identity.created_by != created_by:
        raise ValueError("workflow creation artifact identity must be created by the author")
    revision = architecture_governance_revision(
        workflow_id=workflow_id,
        revision_id=revision_id,
        revision_number=1,
        created_at=created_at,
        author=created_by,
        artifact_identity=artifact_identity,
        max_attempts=max_attempts,
    )
    creation = event(
        _creation_event_id(workflow_id, revision_id),
        workflow_id,
        EventType.WORKFLOW_CREATED,
        actor=created_by,
        occurred_at=created_at,
        revision_id=revision_id,
        payload={
            "workflow_id": workflow_id,
            "workflow_type": ARCHITECTURE_GOVERNANCE,
            "revision_id": revision_id,
            "revision_number": 1,
            "objective": objective,
            "author": created_by,
            "created_at": created_at,
            "artifact_identity": artifact_identity,
            "max_attempts": _CANONICAL_MAX_ATTEMPTS,
        },
    )
    return WorkflowState(
        run=WorkflowRun(
            workflow_id=workflow_id,
            workflow_type=ARCHITECTURE_GOVERNANCE,
            objective=objective,
            active_revision=revision_id,
            created_by=created_by,
            created_at=created_at,
            updated_at=created_at,
        ),
        revisions=(revision,),
        events=(creation,),
        event_digests={creation.event_id: event_digest(creation)},
    )


def is_architecture_governance(state: WorkflowState) -> bool:
    return state.run.workflow_type == ARCHITECTURE_GOVERNANCE


def technical_kinds() -> set[GateKind]:
    return set(_ORDER)


def terminal_revision_statuses() -> set[RevisionStatus]:
    return {
        RevisionStatus.APPROVED,
        RevisionStatus.REJECTED,
        RevisionStatus.FAILED,
        RevisionStatus.NEEDS_OPERATOR,
        RevisionStatus.SUPERSEDED,
    }


def terminal_workflow_statuses() -> set[WorkflowStatus]:
    return {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.REJECTED,
        WorkflowStatus.FAILED,
        WorkflowStatus.NEEDS_OPERATOR,
    }
