"""Pure, copy-on-write transition reducer for workflow governance."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from .errors import (
    ArtifactIdentityError,
    EventConflictError,
    IllegalTransitionError,
    VerdictConflictError,
)
from .events import event_digest
from .graph import (
    active_controlling_gate,
    ready_gates,
    validate_artifact_identity,
    validate_frozen_artifact_identity,
    validate_reviewer_independence,
    validate_state,
)
from .models import (
    ArtifactIdentity,
    EventType,
    GateKind,
    GateStatus,
    OperatorDecision,
    ReviewVerdict,
    RevisionStatus,
    VerdictDecision,
    WorkflowEvent,
    WorkflowGate,
    WorkflowRevision,
    WorkflowRun,
    WorkflowState,
    WorkflowStatus,
    thaw,
)
from .templates import architecture_governance_revision

_REVIEW_KINDS = {
    GateKind.COMPLETENESS_QA,
    GateKind.FEASIBILITY_REVIEW,
    GateKind.SECURITY_REVIEW,
    GateKind.IMPLEMENTATION_APPROVAL,
}
_TECHNICAL_KINDS = {
    GateKind.AUTHOR,
    GateKind.COMPLETENESS_QA,
    GateKind.FREEZE,
    GateKind.FEASIBILITY_REVIEW,
    GateKind.SECURITY_REVIEW,
    GateKind.IMPLEMENTATION_APPROVAL,
}


def _error(
    state: WorkflowState, event: WorkflowEvent, message: str, **details: Any
) -> IllegalTransitionError:
    return IllegalTransitionError(
        message,
        workflow_id=state.run.workflow_id,
        revision_id=event.revision_id,
        gate_id=event.gate_id,
        event_id=event.event_id,
        details=details,
    )


def _revision(state: WorkflowState, event: WorkflowEvent) -> WorkflowRevision:
    if not event.revision_id:
        raise _error(state, event, "event requires a revision ID")
    try:
        return state.revision(event.revision_id)
    except KeyError as exc:
        raise _error(state, event, "unknown revision") from exc


def _gate(state: WorkflowState, event: WorkflowEvent) -> tuple[WorkflowRevision, WorkflowGate]:
    revision = _revision(state, event)
    if not event.gate_id:
        raise _error(state, event, "event requires a gate ID")
    try:
        return revision, state.gate(revision.revision_id, event.gate_id)
    except KeyError as exc:
        raise _error(state, event, "unknown gate") from exc


def _replace_gate(revision: WorkflowRevision, replacement: WorkflowGate) -> WorkflowRevision:
    return replace(
        revision,
        gates=tuple(
            replacement if gate.gate_id == replacement.gate_id else gate for gate in revision.gates
        ),
    )


def _replace_revision(
    state: WorkflowState,
    replacement: WorkflowRevision,
    *,
    run: WorkflowRun | None = None,
    decisions=(),
) -> WorkflowState:
    return replace(
        state,
        run=run or state.run,
        revisions=tuple(
            replacement if item.revision_id == replacement.revision_id else item
            for item in state.revisions
        ),
        operator_decisions=tuple(decisions) if decisions else state.operator_decisions,
    )


def _append(state: WorkflowState, event: WorkflowEvent) -> WorkflowState:
    digests = dict(state.event_digests)
    digests[event.event_id] = event_digest(event)
    return replace(state, events=state.events + (event,), event_digests=digests)


def _ready(revision: WorkflowRevision) -> WorkflowRevision:
    current = {gate.gate_id: gate for gate in revision.gates}
    for gate in ready_gates(revision):
        if gate.status is GateStatus.PENDING:
            current[gate.gate_id] = replace(gate, status=GateStatus.READY)
    return replace(revision, gates=tuple(current[gate.gate_id] for gate in revision.gates))


def _terminal_reject(
    state: WorkflowState,
    revision: WorkflowRevision,
    gate: WorkflowGate,
    verdict: ReviewVerdict,
    event: WorkflowEvent,
) -> WorkflowState:
    gates = []
    for item in revision.gates:
        if item.gate_id == gate.gate_id:
            gates.append(
                replace(
                    item,
                    status=GateStatus.REJECTED,
                    verdict=verdict,
                    completed_at=event.occurred_at,
                )
            )
        elif item.kind is GateKind.ARCHIVE_REJECTION:
            gates.append(replace(item, status=GateStatus.SUCCEEDED, completed_at=event.occurred_at))
        elif item.kind in _TECHNICAL_KINDS and item.status not in {
            GateStatus.SUCCEEDED,
            GateStatus.REJECTED,
        }:
            gates.append(replace(item, status=GateStatus.SKIPPED, completed_at=event.occurred_at))
        else:
            gates.append(item)
    replacement = replace(
        revision,
        status=RevisionStatus.REJECTED,
        gates=tuple(gates),
        completed_at=event.occurred_at,
        terminal_reason=f"{gate.kind.value}: rejected",
    )
    run = replace(state.run, status=WorkflowStatus.REJECTED, updated_at=event.occurred_at)
    return _replace_revision(state, replacement, run=run)


def _operational_failure(
    state: WorkflowState, revision: WorkflowRevision, gate: WorkflowGate, event: WorkflowEvent
) -> WorkflowState:
    if gate.status is not GateStatus.RUNNING:
        raise _error(state, event, "operational failure requires a running gate")
    error = {
        "kind": str(event.payload.get("kind") or "operational_failure"),
        "message": str(event.payload.get("message") or ""),
    }
    if gate.attempt < gate.max_attempts:
        revision = _replace_gate(
            revision,
            replace(gate, status=GateStatus.READY, error=error, completed_at=event.occurred_at),
        )
        return _replace_revision(
            state, revision, run=replace(state.run, updated_at=event.occurred_at)
        )
    replacement = _replace_gate(
        revision,
        replace(gate, status=GateStatus.FAILED, error=error, completed_at=event.occurred_at),
    )
    replacement = replace(
        replacement,
        status=RevisionStatus.FAILED,
        completed_at=event.occurred_at,
        terminal_reason="operational attempts exhausted",
    )
    run = replace(state.run, status=WorkflowStatus.FAILED, updated_at=event.occurred_at)
    return _replace_revision(state, replacement, run=run)


def _operator_escalation(
    state: WorkflowState, revision: WorkflowRevision, event: WorkflowEvent
) -> WorkflowState:
    if revision.status is not RevisionStatus.ACTIVE:
        raise _error(state, event, "operator escalation requires an active revision")
    fields = tuple(str(item) for item in event.payload.get("requested_fields") or ())
    decision_id = str(event.payload.get("decision_id") or "")
    if not decision_id or not fields:
        raise _error(state, event, "operator escalation requires decision_id and requested_fields")
    gates = []
    for gate in revision.gates:
        if gate.kind is GateKind.OPERATOR_ESCALATION:
            gates.append(replace(gate, status=GateStatus.SUCCEEDED, completed_at=event.occurred_at))
        elif gate.kind in _TECHNICAL_KINDS and gate.status in {
            GateStatus.PENDING,
            GateStatus.READY,
            GateStatus.RUNNING,
        }:
            gates.append(replace(gate, status=GateStatus.SKIPPED, completed_at=event.occurred_at))
        else:
            gates.append(gate)
    replacement = replace(
        revision,
        status=RevisionStatus.NEEDS_OPERATOR,
        gates=tuple(gates),
        completed_at=event.occurred_at,
        terminal_reason="operator input required",
    )
    run = replace(state.run, status=WorkflowStatus.NEEDS_OPERATOR, updated_at=event.occurred_at)
    decision = OperatorDecision(
        decision_id=decision_id, requested_fields=fields, requested_at=event.occurred_at
    )
    return _replace_revision(
        state, replacement, run=run, decisions=state.operator_decisions + (decision,)
    )


def _verdict_from_event(state: WorkflowState, event: WorkflowEvent) -> ReviewVerdict:
    raw = event.payload.get("verdict")
    if isinstance(raw, ReviewVerdict):
        verdict = raw
    else:
        from .serialization import verdict_from_dict

        raw_dict = thaw(raw)
        verdict = verdict_from_dict(raw_dict if isinstance(raw_dict, dict) else None)
    if (
        verdict is None
        or not verdict.reviewer
        or not verdict.reviewer_role
        or not verdict.report_reference
        or not verdict.issued_at
        or not re.fullmatch(r"[0-9a-fA-F]{64}", verdict.report_hash)
    ):
        raise _error(
            state,
            event,
            "review verdict requires reviewer identity, role, issued time, and SHA-256 report",
        )
    if verdict.reviewer != event.actor:
        raise _error(state, event, "event actor must equal verdict reviewer")
    return verdict


def _issue_verdict(
    state: WorkflowState, revision: WorkflowRevision, gate: WorkflowGate, event: WorkflowEvent
) -> WorkflowState:
    verdict = _verdict_from_event(state, event)
    if gate.verdict and gate.verdict != verdict:
        raise VerdictConflictError(
            "conflicting authoritative review verdict",
            workflow_id=state.run.workflow_id,
            revision_id=revision.revision_id,
            gate_id=gate.gate_id,
            event_id=event.event_id,
        )
    if gate.status is not GateStatus.RUNNING:
        raise _error(state, event, "review verdict requires a running gate")
    if gate.kind not in _REVIEW_KINDS:
        raise _error(state, event, "gate does not accept review verdicts")
    validate_reviewer_independence(gate, verdict.reviewer)
    expected = revision.artifact_identity
    if gate.kind in {
        GateKind.FEASIBILITY_REVIEW,
        GateKind.SECURITY_REVIEW,
        GateKind.IMPLEMENTATION_APPROVAL,
    }:
        if expected is None or not expected.frozen:
            raise _error(state, event, "review requires a frozen revision artifact")
    if expected is None:
        raise _error(state, event, "revision has no artifact identity")
    validate_artifact_identity(expected, verdict.reviewed_artifact_identity)
    if verdict.decision is VerdictDecision.REJECT and gate.controlling:
        return _terminal_reject(state, revision, gate, verdict, event)
    revision = _replace_gate(
        revision,
        replace(gate, status=GateStatus.SUCCEEDED, verdict=verdict, completed_at=event.occurred_at),
    )
    revision = _ready(revision)
    run = replace(state.run, updated_at=event.occurred_at)
    if gate.kind is GateKind.IMPLEMENTATION_APPROVAL:
        revision = replace(
            revision,
            status=RevisionStatus.APPROVED,
            completed_at=event.occurred_at,
            terminal_reason="implementation approved",
        )
        run = replace(run, status=WorkflowStatus.COMPLETED)
    return _replace_revision(state, revision, run=run)


def _freeze(
    state: WorkflowState, revision: WorkflowRevision, gate: WorkflowGate, event: WorkflowEvent
) -> WorkflowState:
    if gate.kind is not GateKind.FREEZE or gate.status is not GateStatus.RUNNING:
        raise _error(state, event, "artifact freeze requires running freeze gate")
    raw = event.payload.get("artifact_identity")
    from .serialization import artifact_from_dict

    raw_dict = thaw(raw)
    identity = (
        raw
        if isinstance(raw, ArtifactIdentity)
        else artifact_from_dict(raw_dict if isinstance(raw_dict, dict) else None)
    )
    if identity is None:
        raise _error(state, event, "freeze requires a frozen artifact identity")
    try:
        validate_frozen_artifact_identity(identity)
    except ArtifactIdentityError as exc:
        raise _error(state, event, "freeze requires complete frozen artifact identity") from exc
    previous = revision.artifact_identity
    if previous is None:
        raise _error(state, event, "revision has no authored artifact")
    expected = replace(previous, frozen=True, frozen_at=identity.frozen_at)
    validate_artifact_identity(expected, identity)
    revision = _replace_gate(
        revision,
        replace(
            gate,
            status=GateStatus.SUCCEEDED,
            artifact_identity=identity,
            completed_at=event.occurred_at,
        ),
    )
    revision = replace(revision, artifact_identity=identity)
    revision = _ready(revision)
    return _replace_revision(state, revision, run=replace(state.run, updated_at=event.occurred_at))


def _successor(
    state: WorkflowState, predecessor: WorkflowRevision, event: WorkflowEvent
) -> WorkflowState:
    if predecessor.status not in {RevisionStatus.REJECTED, RevisionStatus.FAILED}:
        raise _error(state, event, "successor requires rejected or failed predecessor")
    if state.run.active_revision != predecessor.revision_id:
        raise _error(state, event, "successor requires the active terminal predecessor")
    if any(item.predecessor_revision_id == predecessor.revision_id for item in state.revisions):
        raise _error(state, event, "predecessor already has a successor revision")
    revision_id = str(event.payload.get("revision_id") or "")
    author = str(event.payload.get("author") or "")
    raw = event.payload.get("artifact_identity")
    from .serialization import artifact_from_dict

    raw_dict = thaw(raw)
    identity = (
        raw
        if isinstance(raw, ArtifactIdentity)
        else artifact_from_dict(raw_dict if isinstance(raw_dict, dict) else None)
    )
    if not revision_id or not author or identity is None:
        raise _error(state, event, "successor requires revision_id, author, and artifact_identity")
    if any(item.revision_id == revision_id for item in state.revisions):
        raise _error(state, event, "successor revision ID already exists")
    revision = architecture_governance_revision(
        workflow_id=state.run.workflow_id,
        revision_id=revision_id,
        revision_number=max(item.revision_number for item in state.revisions) + 1,
        created_at=event.occurred_at,
        author=author,
        artifact_identity=identity,
        max_attempts=int(event.payload.get("max_attempts", 2)),
        predecessor_revision_id=predecessor.revision_id,
    )
    run = replace(
        state.run,
        status=WorkflowStatus.ACTIVE,
        active_revision=revision_id,
        updated_at=event.occurred_at,
    )
    return replace(state, run=run, revisions=state.revisions + (revision,))


def transition(current_state: WorkflowState, event: WorkflowEvent) -> WorkflowState:
    """Reduce exactly one recognized event without I/O, clocks, or mutable state."""
    validate_state(current_state)
    digest = event_digest(event)
    known = current_state.event_digests.get(event.event_id)
    if known is not None:
        if known == digest:
            return current_state
        raise EventConflictError(
            "event ID was replayed with different contents",
            workflow_id=current_state.run.workflow_id,
            event_id=event.event_id,
        )
    if event.workflow_id != current_state.run.workflow_id:
        raise _error(current_state, event, "event belongs to another workflow")
    if event.event_type is EventType.WORKFLOW_CREATED:
        raise _error(current_state, event, "workflow creation event is only valid as genesis")
    if event.event_type is EventType.SUCCESSOR_REVISION_STARTED:
        next_state = _successor(current_state, _revision(current_state, event), event)
    elif event.event_type is EventType.OPERATOR_INPUT_REQUIRED:
        next_state = _operator_escalation(current_state, _revision(current_state, event), event)
    elif event.event_type is EventType.METADATA_OBSERVED:
        metadata = dict(current_state.run.metadata)
        metadata.setdefault("cached", {}).update(dict(event.payload))
        next_state = replace(
            current_state,
            run=replace(current_state.run, metadata=metadata, updated_at=event.occurred_at),
        )
    else:
        revision, gate = _gate(current_state, event)
        if current_state.run.status is not WorkflowStatus.ACTIVE:
            raise _error(current_state, event, "cannot change a terminal workflow run")
        if current_state.run.active_revision != revision.revision_id:
            raise _error(current_state, event, "event does not target the active revision")
        if revision.status is not RevisionStatus.ACTIVE:
            raise _error(current_state, event, "cannot change terminal revision")
        if event.event_type is EventType.GATE_STARTED:
            if not event.actor:
                raise _error(current_state, event, "gate start requires an identified actor")
            if gate.status is not GateStatus.READY:
                raise _error(
                    current_state,
                    event,
                    "gate must be ready before start",
                    status=gate.status.value,
                )
            if active_controlling_gate(revision):
                raise _error(current_state, event, "another controlling gate is already running")
            if any(
                current_state.gate(revision.revision_id, dep).status is not GateStatus.SUCCEEDED
                for dep in gate.dependencies
            ):
                raise _error(current_state, event, "gate dependencies have not succeeded")
            if gate.kind in _REVIEW_KINDS:
                validate_reviewer_independence(gate, event.actor)
            next_state = _replace_revision(
                current_state,
                _replace_gate(
                    revision,
                    replace(
                        gate,
                        status=GateStatus.RUNNING,
                        assigned_agent=event.actor,
                        attempt=gate.attempt + 1,
                        started_at=event.occurred_at,
                    ),
                ),
                run=replace(current_state.run, updated_at=event.occurred_at),
            )
        elif event.event_type is EventType.GATE_COMPLETED:
            if gate.kind is not GateKind.AUTHOR or gate.status is not GateStatus.RUNNING:
                raise _error(
                    current_state, event, "generic completion may only complete running author gate"
                )
            if event.actor != gate.assigned_agent:
                raise _error(current_state, event, "only assigned author may complete author gate")
            revision = _replace_gate(
                revision,
                replace(
                    gate,
                    status=GateStatus.SUCCEEDED,
                    result=dict(event.payload),
                    completed_at=event.occurred_at,
                ),
            )
            next_state = _replace_revision(
                current_state,
                _ready(revision),
                run=replace(current_state.run, updated_at=event.occurred_at),
            )
        elif event.event_type is EventType.ARTIFACT_FROZEN:
            next_state = _freeze(current_state, revision, gate, event)
        elif event.event_type is EventType.REVIEW_VERDICT_ISSUED:
            next_state = _issue_verdict(current_state, revision, gate, event)
        elif event.event_type is EventType.OPERATIONAL_FAILURE_RECORDED:
            next_state = _operational_failure(current_state, revision, gate, event)
        else:
            raise _error(current_state, event, "unrecognized event type")
    next_state = _append(next_state, event)
    validate_state(next_state)
    return next_state


def start_successor_revision(current_state: WorkflowState, event: WorkflowEvent) -> WorkflowState:
    if event.event_type is not EventType.SUCCESSOR_REVISION_STARTED:
        raise IllegalTransitionError("expected successor revision event", event_id=event.event_id)
    return transition(current_state, event)
