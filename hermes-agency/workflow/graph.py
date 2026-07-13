"""Pure graph and state validation helpers."""

from __future__ import annotations

from collections.abc import Iterable

from .errors import ArtifactIdentityError, GraphValidationError
from .events import event_digest
from .models import (
    GateKind,
    GateStatus,
    RevisionStatus,
    VerdictDecision,
    WorkflowGate,
    WorkflowRevision,
    WorkflowState,
    WorkflowStatus,
)

_EXCEPTIONAL = {GateKind.ARCHIVE_REJECTION, GateKind.OPERATOR_ESCALATION}
_RUN_STATUS_FOR_REVISION = {
    RevisionStatus.APPROVED: WorkflowStatus.COMPLETED,
    RevisionStatus.REJECTED: WorkflowStatus.REJECTED,
    RevisionStatus.FAILED: WorkflowStatus.FAILED,
    RevisionStatus.NEEDS_OPERATOR: WorkflowStatus.NEEDS_OPERATOR,
}


def validate_frozen_artifact_identity(identity) -> None:
    """Require a reviewable frozen identity rather than a hash-shaped stub."""
    if not identity.frozen or not identity.frozen_at:
        raise ArtifactIdentityError("artifact identity is not frozen")
    if not identity.references or not identity.hashes or not identity.byte_sizes:
        raise ArtifactIdentityError(
            "frozen artifact requires references, hashes, and byte sizes",
            details={"artifact_id": identity.artifact_id},
        )
    if set(identity.references) != set(identity.hashes) or set(identity.references) != set(
        identity.byte_sizes
    ):
        raise ArtifactIdentityError(
            "frozen artifact references, hashes, and byte sizes must bind the same paths",
            details={"artifact_id": identity.artifact_id},
        )
    if any(not value for value in identity.hashes.values()) or any(
        not isinstance(value, int) or value < 0 for value in identity.byte_sizes.values()
    ):
        raise ArtifactIdentityError(
            "frozen artifact hashes and byte sizes must be complete",
            details={"artifact_id": identity.artifact_id},
        )


def validate_workflow_graph(gates: Iterable[WorkflowGate]) -> None:
    gates = tuple(gates)
    ids = [gate.gate_id for gate in gates]
    if len(ids) != len(set(ids)):
        raise GraphValidationError("gate IDs must be unique", details={"gate_ids": ids})
    known = set(ids)
    for gate in gates:
        unknown = sorted(set(gate.dependencies) - known)
        if unknown:
            raise GraphValidationError(
                "gate has unknown dependencies", gate_id=gate.gate_id, details={"unknown": unknown}
            )
    visiting: set[str] = set()
    visited: set[str] = set()
    graph = {gate.gate_id: gate.dependencies for gate in gates}

    def visit(gate_id: str) -> None:
        if gate_id in visiting:
            raise GraphValidationError("workflow graph contains a cycle", gate_id=gate_id)
        if gate_id not in visited:
            visiting.add(gate_id)
            for dependency in graph[gate_id]:
                visit(dependency)
            visiting.remove(gate_id)
            visited.add(gate_id)

    for gate_id in ids:
        visit(gate_id)


def ready_gates(revision: WorkflowRevision) -> tuple[WorkflowGate, ...]:
    """Return ordinary gates whose dependencies have succeeded, in template order."""
    if revision.status is not RevisionStatus.ACTIVE:
        return ()
    statuses = {gate.gate_id: gate.status for gate in revision.gates}
    return tuple(
        gate
        for gate in revision.gates
        if gate.kind not in _EXCEPTIONAL
        and gate.status in {GateStatus.PENDING, GateStatus.READY}
        and all(statuses[dependency] is GateStatus.SUCCEEDED for dependency in gate.dependencies)
    )


def active_controlling_gate(revision: WorkflowRevision) -> WorkflowGate | None:
    running = [
        gate for gate in revision.gates if gate.controlling and gate.status is GateStatus.RUNNING
    ]
    if len(running) > 1:
        raise GraphValidationError(
            "only one controlling gate may run",
            revision_id=revision.revision_id,
            details={"running_gate_ids": [gate.gate_id for gate in running]},
        )
    return running[0] if running else None


def validate_terminal_revision_evidence(revision: WorkflowRevision) -> None:
    """Terminal status must be supported by terminal gate evidence, not JSON fields."""
    by_kind = {gate.kind: gate for gate in revision.gates}
    verdicts = [gate.verdict for gate in revision.gates if gate.verdict is not None]
    if revision.status is RevisionStatus.REJECTED:
        archive = by_kind[GateKind.ARCHIVE_REJECTION]
        if archive.status is not GateStatus.SUCCEEDED or not any(
            verdict.decision is VerdictDecision.REJECT for verdict in verdicts
        ):
            raise GraphValidationError(
                "rejected revision lacks authoritative rejected-verdict archive evidence",
                revision_id=revision.revision_id,
            )
    elif revision.status is RevisionStatus.FAILED and not any(
        gate.status is GateStatus.FAILED for gate in revision.gates
    ):
        raise GraphValidationError(
            "failed revision lacks failed-gate evidence", revision_id=revision.revision_id
        )
    elif revision.status is RevisionStatus.APPROVED:
        approval = by_kind[GateKind.IMPLEMENTATION_APPROVAL]
        if approval.status is not GateStatus.SUCCEEDED or (
            approval.verdict is None or approval.verdict.decision is not VerdictDecision.APPROVE
        ):
            raise GraphValidationError(
                "approved revision lacks implementation approval evidence",
                revision_id=revision.revision_id,
            )
    elif revision.status is RevisionStatus.NEEDS_OPERATOR:
        escalation = by_kind[GateKind.OPERATOR_ESCALATION]
        if escalation.status is not GateStatus.SUCCEEDED:
            raise GraphValidationError(
                "operator-blocked revision lacks escalation evidence",
                revision_id=revision.revision_id,
            )


def validate_state(state: WorkflowState) -> None:
    revisions = state.revisions
    revision_ids = [revision.revision_id for revision in revisions]
    if len(revision_ids) != len(set(revision_ids)):
        raise GraphValidationError("revision IDs must be unique", workflow_id=state.run.workflow_id)
    predecessor_ids = [
        revision.predecessor_revision_id
        for revision in revisions
        if revision.predecessor_revision_id is not None
    ]
    if len(predecessor_ids) != len(set(predecessor_ids)):
        raise GraphValidationError(
            "a predecessor revision may have only one successor",
            workflow_id=state.run.workflow_id,
            details={"predecessor_revision_ids": predecessor_ids},
        )
    if any(predecessor_id not in set(revision_ids) for predecessor_id in predecessor_ids):
        raise GraphValidationError(
            "successor references an unknown predecessor", workflow_id=state.run.workflow_id
        )
    if state.run.active_revision and state.run.active_revision not in set(revision_ids):
        raise GraphValidationError(
            "active revision does not exist", workflow_id=state.run.workflow_id
        )
    active_revisions = [
        revision for revision in revisions if revision.status is RevisionStatus.ACTIVE
    ]
    if len(active_revisions) > 1:
        raise GraphValidationError(
            "workflow may have only one active revision",
            workflow_id=state.run.workflow_id,
            details={
                "active_revision_ids": [revision.revision_id for revision in active_revisions]
            },
        )
    if state.run.status is WorkflowStatus.ACTIVE:
        if (
            len(active_revisions) != 1
            or state.run.active_revision != active_revisions[0].revision_id
        ):
            raise GraphValidationError(
                "active workflow run must point to its sole active revision",
                workflow_id=state.run.workflow_id,
            )
    elif active_revisions:
        raise GraphValidationError(
            "terminal workflow run cannot contain an active revision",
            workflow_id=state.run.workflow_id,
        )
    elif state.run.active_revision:
        terminal = next(
            revision for revision in revisions if revision.revision_id == state.run.active_revision
        )
        expected_status = _RUN_STATUS_FOR_REVISION.get(terminal.status)
        if expected_status is None or state.run.status is not expected_status:
            raise GraphValidationError(
                "workflow run status must match active terminal revision",
                workflow_id=state.run.workflow_id,
                revision_id=terminal.revision_id,
            )
    for revision in revisions:
        if revision.workflow_id != state.run.workflow_id:
            raise GraphValidationError(
                "revision belongs to another workflow", revision_id=revision.revision_id
            )
        validate_workflow_graph(revision.gates)
        active_controlling_gate(revision)
        if revision.status is not RevisionStatus.ACTIVE:
            validate_terminal_revision_evidence(revision)
        for gate in revision.gates:
            if gate.revision_id != revision.revision_id:
                raise GraphValidationError("gate belongs to another revision", gate_id=gate.gate_id)
            if gate.artifact_identity and gate.artifact_identity.frozen:
                validate_frozen_artifact_identity(gate.artifact_identity)
        if revision.artifact_identity and revision.artifact_identity.frozen:
            validate_frozen_artifact_identity(revision.artifact_identity)
        if revision.status is not RevisionStatus.ACTIVE and active_controlling_gate(revision):
            raise GraphValidationError(
                "terminal revision has running controlling gate", revision_id=revision.revision_id
            )
    event_ids = [event.event_id for event in state.events]
    if len(event_ids) != len(set(event_ids)):
        raise GraphValidationError(
            "event ledger contains duplicate event IDs", workflow_id=state.run.workflow_id
        )
    if set(event_ids) != set(state.event_digests):
        raise GraphValidationError(
            "event ledger and digest index disagree", workflow_id=state.run.workflow_id
        )
    for event in state.events:
        if event.workflow_id != state.run.workflow_id:
            raise GraphValidationError("event belongs to another workflow", event_id=event.event_id)
        if state.event_digests[event.event_id] != event_digest(event):
            raise GraphValidationError(
                "event digest does not match canonical event", event_id=event.event_id
            )


def validate_reviewer_independence(gate: WorkflowGate, reviewer: str) -> None:
    if gate.kind in {
        GateKind.COMPLETENESS_QA,
        GateKind.FEASIBILITY_REVIEW,
        GateKind.SECURITY_REVIEW,
        GateKind.IMPLEMENTATION_APPROVAL,
    }:
        if not reviewer:
            from .errors import ReviewerIndependenceError

            raise ReviewerIndependenceError(
                "controlling review requires an identified reviewer",
                revision_id=gate.revision_id,
                gate_id=gate.gate_id,
            )
        if not gate.author_agent:
            from .errors import ReviewerIndependenceError

            raise ReviewerIndependenceError(
                "controlling review requires an identified artifact author",
                revision_id=gate.revision_id,
                gate_id=gate.gate_id,
            )
        if reviewer == gate.author_agent:
            from .errors import ReviewerIndependenceError

            raise ReviewerIndependenceError(
                "artifact author cannot perform controlling review",
                revision_id=gate.revision_id,
                gate_id=gate.gate_id,
                details={"reviewer": reviewer, "author": gate.author_agent},
            )


def validate_artifact_identity(expected, observed) -> None:
    if expected != observed:
        raise ArtifactIdentityError(
            "artifact identity does not match exact frozen identity",
            details={"expected": expected.artifact_id, "observed": observed.artifact_id},
        )
