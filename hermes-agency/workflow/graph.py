"""Pure graph and state validation helpers."""

from __future__ import annotations

from collections.abc import Iterable

from .errors import ArtifactIdentityError, GraphValidationError
from .events import event_digest
from .models import (
    GateKind,
    GateStatus,
    RevisionStatus,
    WorkflowGate,
    WorkflowRevision,
    WorkflowState,
)

_EXCEPTIONAL = {GateKind.ARCHIVE_REJECTION, GateKind.OPERATOR_ESCALATION}


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


def validate_state(state: WorkflowState) -> None:
    revisions = state.revisions
    revision_ids = [revision.revision_id for revision in revisions]
    if len(revision_ids) != len(set(revision_ids)):
        raise GraphValidationError("revision IDs must be unique", workflow_id=state.run.workflow_id)
    if state.run.active_revision and state.run.active_revision not in set(revision_ids):
        raise GraphValidationError(
            "active revision does not exist", workflow_id=state.run.workflow_id
        )
    for revision in revisions:
        if revision.workflow_id != state.run.workflow_id:
            raise GraphValidationError(
                "revision belongs to another workflow", revision_id=revision.revision_id
            )
        validate_workflow_graph(revision.gates)
        active_controlling_gate(revision)
        for gate in revision.gates:
            if gate.revision_id != revision.revision_id:
                raise GraphValidationError("gate belongs to another revision", gate_id=gate.gate_id)
            if gate.artifact_identity and gate.artifact_identity.frozen:
                if not gate.artifact_identity.hashes:
                    raise ArtifactIdentityError(
                        "frozen artifact requires hashes", gate_id=gate.gate_id
                    )
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
    }:
        if reviewer and gate.author_agent and reviewer == gate.author_agent:
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
