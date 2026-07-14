from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow import (  # noqa: E402
    ArtifactIdentity,
    ArtifactIdentityError,
    EventConflictError,
    EventType,
    GateKind,
    GateStatus,
    GraphValidationError,
    IllegalTransitionError,
    ReviewerIndependenceError,
    ReviewVerdict,
    RevisionStatus,
    SerializationError,
    VerdictConflictError,
    VerdictDecision,
    WorkflowGate,
    WorkflowState,
    architecture_governance_state,
    event,
    ready_gates,
    restore_state,
    serialize_state,
    transition,
    validate_state,
    validate_workflow_graph,
)

NOW = "2026-07-13T20:00:00Z"


def artifact(
    *, frozen: bool = False, digest: str = "a" * 64, created_by: str = "author"
) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id="architecture",
        references=("docs/architecture.md",),
        hashes={"docs/architecture.md": digest},
        byte_sizes={"docs/architecture.md": 42},
        frozen=frozen,
        frozen_at=NOW if frozen else None,
        created_by=created_by,
    )


def state():
    return architecture_governance_state(
        workflow_id="wf-1",
        revision_id="rev-1",
        objective="ship deterministic governance",
        created_by="author",
        created_at=NOW,
        artifact_identity=artifact(),
    )


def reindex_events(payload):
    payload["event_digests"] = {
        item["event_id"]: hashlib.sha256(
            json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        for item in payload["events"]
    }
    return payload


def gate_id(revision_id: str, kind: GateKind) -> str:
    return f"{revision_id}:{kind.value}"


def start(current, kind: GateKind, actor: str, event_id: str):
    revision = current.run.active_revision
    assert revision
    return transition(
        current,
        event(
            event_id,
            "wf-1",
            EventType.GATE_STARTED,
            actor=actor,
            occurred_at=NOW,
            revision_id=revision,
            gate_id=gate_id(revision, kind),
        ),
    )


def author_complete(current, event_id: str = "author-complete", actor: str | None = None):
    revision = current.run.active_revision
    assert revision
    assigned = actor or current.gate(revision, gate_id(revision, GateKind.AUTHOR)).assigned_agent
    return transition(
        current,
        event(
            event_id,
            "wf-1",
            EventType.GATE_COMPLETED,
            actor=assigned or "",
            occurred_at=NOW,
            revision_id=revision,
            gate_id=gate_id(revision, GateKind.AUTHOR),
            payload={"reference": "docs/architecture.md"},
        ),
    )


def verdict(current, kind: GateKind, reviewer: str, decision: VerdictDecision, event_id: str):
    revision = current.run.active_revision
    assert revision
    identity = current.revision(revision).artifact_identity
    assert identity
    report = ReviewVerdict(
        decision=decision,
        reviewer=reviewer,
        reviewer_role="independent reviewer",
        reviewed_artifact_identity=identity,
        findings=({"id": "finding", "severity": "high"},),
        report_reference=f"reports/{event_id}.json",
        report_hash="b" * 64,
        issued_at=NOW,
    )
    return transition(
        current,
        event(
            event_id,
            "wf-1",
            EventType.REVIEW_VERDICT_ISSUED,
            actor=reviewer,
            occurred_at=NOW,
            revision_id=revision,
            gate_id=gate_id(revision, kind),
            payload={"verdict": report},
        ),
    )


def freeze(current):
    revision = current.run.active_revision
    assert revision
    authored = current.revision(revision).artifact_identity
    assert authored
    frozen = replace(authored, frozen=True, frozen_at=NOW)
    return transition(
        current,
        event(
            "freeze",
            "wf-1",
            EventType.ARTIFACT_FROZEN,
            actor="freezer",
            occurred_at=NOW,
            revision_id=revision,
            gate_id=gate_id(revision, GateKind.FREEZE),
            payload={"artifact_identity": frozen},
        ),
    )


def approved_through_freeze():
    current = start(state(), GateKind.AUTHOR, "author", "author-start")
    current = author_complete(current)
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-start")
    current = verdict(
        current, GateKind.COMPLETENESS_QA, "qa", VerdictDecision.APPROVE, "qa-approve"
    )
    current = start(current, GateKind.FREEZE, "freezer", "freeze-start")
    return freeze(current)


def test_architecture_governance_happy_path():
    current = approved_through_freeze()
    current = start(current, GateKind.FEASIBILITY_REVIEW, "feasibility", "feas-start")
    current = verdict(
        current, GateKind.FEASIBILITY_REVIEW, "feasibility", VerdictDecision.APPROVE, "feas-approve"
    )
    current = start(current, GateKind.SECURITY_REVIEW, "security", "security-start")
    current = verdict(
        current, GateKind.SECURITY_REVIEW, "security", VerdictDecision.APPROVE, "security-approve"
    )
    current = start(current, GateKind.IMPLEMENTATION_APPROVAL, "approver", "implementation-start")
    current = verdict(
        current,
        GateKind.IMPLEMENTATION_APPROVAL,
        "approver",
        VerdictDecision.APPROVE,
        "implementation-approve",
    )
    assert current.run.status.value == "completed"
    assert current.revision("rev-1").status is RevisionStatus.APPROVED


@pytest.mark.parametrize(
    ("dependencies", "message"),
    [(("missing",), "unknown dependencies"), (("b",), "cycle")],
)
def test_graph_validation_rejects_unknown_dependencies_and_cycles(dependencies, message):
    gates = (
        WorkflowGate("a", "r", GateKind.AUTHOR, dependencies=dependencies),
        WorkflowGate("b", "r", GateKind.COMPLETENESS_QA, dependencies=("a",)),
    )
    with pytest.raises(GraphValidationError, match=message):
        validate_workflow_graph(gates)


def test_premature_activation_and_multiple_controlling_gates_are_rejected():
    with pytest.raises(IllegalTransitionError, match="must be ready"):
        start(state(), GateKind.COMPLETENESS_QA, "qa", "too-soon")
    current = start(state(), GateKind.AUTHOR, "author", "author-start")
    revision = current.revision("rev-1")
    author = current.gate("rev-1", gate_id("rev-1", GateKind.AUTHOR))
    qa = current.gate("rev-1", gate_id("rev-1", GateKind.COMPLETENESS_QA))
    broken = replace(
        revision,
        gates=tuple(
            replace(qa, status=GateStatus.RUNNING) if gate == qa else gate
            for gate in revision.gates
        ),
    )
    with pytest.raises(GraphValidationError, match="only one controlling"):
        validate_state(
            WorkflowState(
                run=current.run,
                revisions=(broken,),
                events=current.events,
                event_digests=current.event_digests,
            )
        )
    assert author.status is GateStatus.RUNNING


def test_illegal_transition_error_has_workflow_context_and_records_are_immutable():
    with pytest.raises(IllegalTransitionError) as raised:
        start(state(), GateKind.COMPLETENESS_QA, "qa", "too-soon-context")
    error = raised.value
    assert error.workflow_id == "wf-1"
    assert error.revision_id == "rev-1"
    assert error.gate_id == gate_id("rev-1", GateKind.COMPLETENESS_QA)
    assert error.event_id == "too-soon-context"
    with pytest.raises(AttributeError):
        state().run.status = "rejected"


def test_self_review_and_transport_failure_have_distinct_outcomes():
    current = author_complete(start(state(), GateKind.AUTHOR, "author", "author-start"))
    with pytest.raises(ReviewerIndependenceError):
        start(current, GateKind.COMPLETENESS_QA, "author", "self-start")
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-start")
    current = transition(
        current,
        event(
            "timeout",
            "wf-1",
            EventType.OPERATIONAL_FAILURE_RECORDED,
            actor="system",
            occurred_at=NOW,
            revision_id="rev-1",
            gate_id=gate_id("rev-1", GateKind.COMPLETENESS_QA),
            payload={"kind": "transport", "message": "relay timeout"},
        ),
    )
    qa = current.gate("rev-1", gate_id("rev-1", GateKind.COMPLETENESS_QA))
    assert qa.status is GateStatus.READY
    assert qa.verdict is None
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-retry")
    current = verdict(current, GateKind.COMPLETENESS_QA, "qa", VerdictDecision.REJECT, "qa-reject")
    assert current.revision("rev-1").status is RevisionStatus.REJECTED
    assert (
        current.gate("rev-1", gate_id("rev-1", GateKind.ARCHIVE_REJECTION)).status
        is GateStatus.SUCCEEDED
    )


def test_retry_exhaustion_is_failed_not_rejected():
    current = author_complete(start(state(), GateKind.AUTHOR, "author", "author-start"))
    for attempt in (1, 2):
        current = start(current, GateKind.COMPLETENESS_QA, "qa", f"start-{attempt}")
        current = transition(
            current,
            event(
                f"fail-{attempt}",
                "wf-1",
                EventType.OPERATIONAL_FAILURE_RECORDED,
                actor="system",
                occurred_at=NOW,
                revision_id="rev-1",
                gate_id=gate_id("rev-1", GateKind.COMPLETENESS_QA),
                payload={"kind": "transport"},
            ),
        )
    assert current.revision("rev-1").status is RevisionStatus.FAILED
    assert (
        current.gate("rev-1", gate_id("rev-1", GateKind.COMPLETENESS_QA)).status
        is GateStatus.FAILED
    )
    assert restore_state(serialize_state(current)) == current


def test_artifact_freeze_binds_reports_and_detects_mutation():
    current = approved_through_freeze()
    current = start(current, GateKind.FEASIBILITY_REVIEW, "feasibility", "feas-start")
    with pytest.raises(ArtifactIdentityError):
        mutated = replace(artifact(frozen=True), hashes={"sha256": "c" * 64})
        report = ReviewVerdict(
            VerdictDecision.APPROVE, "feasibility", "reviewer", mutated, (), "report", "b" * 64, NOW
        )
        transition(
            current,
            event(
                "mutated",
                "wf-1",
                EventType.REVIEW_VERDICT_ISSUED,
                actor="feasibility",
                occurred_at=NOW,
                revision_id="rev-1",
                gate_id=gate_id("rev-1", GateKind.FEASIBILITY_REVIEW),
                payload={"verdict": report},
            ),
        )


def test_authoritative_hashed_security_reject_beats_stale_cached_approve_and_conflict_fails_closed():
    current = approved_through_freeze()
    current = start(current, GateKind.FEASIBILITY_REVIEW, "feasibility", "feas-start")
    current = verdict(
        current, GateKind.FEASIBILITY_REVIEW, "feasibility", VerdictDecision.APPROVE, "feas-approve"
    )
    current = transition(
        current,
        event(
            "cached",
            "wf-1",
            EventType.METADATA_OBSERVED,
            actor="kanban",
            occurred_at=NOW,
            payload={"security": "approve"},
        ),
    )
    current = start(current, GateKind.SECURITY_REVIEW, "security", "security-start")
    current = verdict(
        current, GateKind.SECURITY_REVIEW, "security", VerdictDecision.REJECT, "security-reject"
    )
    assert current.run.status.value == "rejected"
    assert current.run.metadata["cached"]["security"] == "approve"
    conflicting = ReviewVerdict(
        VerdictDecision.APPROVE,
        "security",
        "reviewer",
        current.revision("rev-1").artifact_identity,
        (),
        "report",
        "d" * 64,
        NOW,
    )
    with pytest.raises((IllegalTransitionError, VerdictConflictError)):
        transition(
            current,
            event(
                "late-conflict",
                "wf-1",
                EventType.REVIEW_VERDICT_ISSUED,
                actor="security",
                occurred_at=NOW,
                revision_id="rev-1",
                gate_id=gate_id("rev-1", GateKind.SECURITY_REVIEW),
                payload={"verdict": conflicting},
            ),
        )


def test_rejected_revision_immutable_successor_and_operator_escalation_stop_autonomy():
    current = author_complete(start(state(), GateKind.AUTHOR, "author", "author-start"))
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-start")
    current = verdict(current, GateKind.COMPLETENESS_QA, "qa", VerdictDecision.REJECT, "qa-reject")
    with pytest.raises(IllegalTransitionError, match="terminal workflow run"):
        start(current, GateKind.FREEZE, "freezer", "late-freeze")
    current = transition(
        current,
        event(
            "successor",
            "wf-1",
            EventType.SUCCESSOR_REVISION_STARTED,
            actor="author-2",
            occurred_at=NOW,
            revision_id="rev-1",
            payload={
                "revision_id": "rev-2",
                "author": "author-2",
                "artifact_identity": artifact(created_by="author-2"),
                "max_attempts": 2,
            },
        ),
    )
    assert current.revision("rev-2").predecessor_revision_id == "rev-1"
    assert current.revision("rev-1").successor_revision_id is None
    current = transition(
        current,
        event(
            "need-operator",
            "wf-1",
            EventType.OPERATOR_INPUT_REQUIRED,
            actor="system",
            occurred_at=NOW,
            revision_id="rev-2",
            payload={
                "decision_id": "operator-1",
                "requested_fields": ["provider_account", "budget", "policy"],
            },
        ),
    )
    assert current.run.status.value == "needs_operator"
    assert ready_gates(current.revision("rev-2")) == ()
    assert all(gate.status is not GateStatus.RUNNING for gate in current.revision("rev-2").gates)
    assert restore_state(serialize_state(current)) == current


def test_tampered_terminal_status_cannot_restore_or_resume():
    payload = json.loads(serialize_state(state()))
    payload["run"]["status"] = "rejected"
    payload["revisions"][0]["status"] = "rejected"
    with pytest.raises(GraphValidationError, match="rejected revision lacks"):
        restore_state(payload)


def test_restore_rejects_forked_successor_history():
    current = author_complete(start(state(), GateKind.AUTHOR, "author", "author-start"))
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-start")
    current = verdict(current, GateKind.COMPLETENESS_QA, "qa", VerdictDecision.REJECT, "qa-reject")
    current = transition(
        current,
        event(
            "r2",
            "wf-1",
            EventType.SUCCESSOR_REVISION_STARTED,
            actor="author-2",
            occurred_at=NOW,
            revision_id="rev-1",
            payload={
                "revision_id": "rev-2",
                "author": "author-2",
                "artifact_identity": artifact(created_by="author-2"),
            },
        ),
    )
    current = author_complete(
        start(current, GateKind.AUTHOR, "author-2", "r2-author-start"), "r2-author-complete"
    )
    current = start(current, GateKind.COMPLETENESS_QA, "qa-2", "r2-qa-start")
    current = verdict(
        current, GateKind.COMPLETENESS_QA, "qa-2", VerdictDecision.REJECT, "r2-qa-reject"
    )
    current = transition(
        current,
        event(
            "r3",
            "wf-1",
            EventType.SUCCESSOR_REVISION_STARTED,
            actor="author-3",
            occurred_at=NOW,
            revision_id="rev-2",
            payload={
                "revision_id": "rev-3",
                "author": "author-3",
                "artifact_identity": artifact(created_by="author-3"),
            },
        ),
    )
    payload = json.loads(serialize_state(current))
    payload["revisions"][2]["predecessor_revision_id"] = "rev-1"
    with pytest.raises(GraphValidationError, match="only one successor"):
        restore_state(payload)


def test_implementation_approval_cannot_be_self_reviewed_by_artifact_author():
    current = approved_through_freeze()
    current = start(current, GateKind.FEASIBILITY_REVIEW, "feasibility", "feas-start")
    current = verdict(
        current, GateKind.FEASIBILITY_REVIEW, "feasibility", VerdictDecision.APPROVE, "feas-approve"
    )
    current = start(current, GateKind.SECURITY_REVIEW, "security", "security-start")
    current = verdict(
        current, GateKind.SECURITY_REVIEW, "security", VerdictDecision.APPROVE, "security-approve"
    )
    with pytest.raises(ReviewerIndependenceError):
        start(current, GateKind.IMPLEMENTATION_APPROVAL, "author", "implementation-self-review")


def test_restored_approval_revalidates_report_and_reviewer_independence():
    current = approved_through_freeze()
    current = start(current, GateKind.FEASIBILITY_REVIEW, "feasibility", "feas-start")
    current = verdict(
        current, GateKind.FEASIBILITY_REVIEW, "feasibility", VerdictDecision.APPROVE, "feas-approve"
    )
    current = start(current, GateKind.SECURITY_REVIEW, "security", "security-start")
    current = verdict(
        current, GateKind.SECURITY_REVIEW, "security", VerdictDecision.APPROVE, "security-approve"
    )
    current = start(current, GateKind.IMPLEMENTATION_APPROVAL, "approver", "implementation-start")
    current = verdict(
        current,
        GateKind.IMPLEMENTATION_APPROVAL,
        "approver",
        VerdictDecision.APPROVE,
        "implementation-approve",
    )
    payload = json.loads(serialize_state(current))
    approval = next(
        gate
        for gate in payload["revisions"][0]["gates"]
        if gate["kind"] == GateKind.IMPLEMENTATION_APPROVAL.value
    )
    approval["verdict"]["reviewer"] = "author"
    with pytest.raises(GraphValidationError, match="artifact-bound reviewer independence"):
        restore_state(payload)
    approval["author_agent"] = "tampered-author-agent"
    with pytest.raises(GraphValidationError, match="artifact-bound reviewer independence"):
        restore_state(payload)
    approval["author_agent"] = "author"
    approval["verdict"]["reviewer"] = "approver"
    approval["verdict"]["report_hash"] = "not-a-sha256"
    with pytest.raises(GraphValidationError, match="required authoritative fields"):
        restore_state(payload)


def test_restore_rejects_fabricated_unfrozen_terminal_approval_without_events():
    payload = json.loads(serialize_state(state()))
    payload["run"]["status"] = "completed"
    payload["revisions"][0]["status"] = "approved"
    approval = next(
        gate
        for gate in payload["revisions"][0]["gates"]
        if gate["kind"] == GateKind.IMPLEMENTATION_APPROVAL.value
    )
    approval["status"] = GateStatus.SUCCEEDED.value
    approval["verdict"] = {
        "decision": VerdictDecision.APPROVE.value,
        "reviewer": "approver",
        "reviewer_role": "independent reviewer",
        "reviewed_artifact_identity": payload["revisions"][0]["artifact_identity"],
        "findings": [],
        "report_reference": "reports/fake.json",
        "report_hash": "c" * 64,
        "issued_at": NOW,
    }
    with pytest.raises(GraphValidationError, match="persisted downstream review"):
        restore_state(payload)


def test_restore_replay_rejects_materialized_approval_flag_mutation():
    current = approved_through_freeze()
    current = start(current, GateKind.FEASIBILITY_REVIEW, "feasibility", "feas-start")
    current = verdict(
        current, GateKind.FEASIBILITY_REVIEW, "feasibility", VerdictDecision.APPROVE, "feas-approve"
    )
    current = start(current, GateKind.SECURITY_REVIEW, "security", "security-start")
    current = verdict(
        current, GateKind.SECURITY_REVIEW, "security", VerdictDecision.APPROVE, "security-approve"
    )
    current = start(current, GateKind.IMPLEMENTATION_APPROVAL, "approver", "implementation-start")
    current = verdict(
        current,
        GateKind.IMPLEMENTATION_APPROVAL,
        "approver",
        VerdictDecision.APPROVE,
        "implementation-approve",
    )
    assert restore_state(serialize_state(current)) == current
    payload = json.loads(serialize_state(current))
    approval = next(
        gate
        for gate in payload["revisions"][0]["gates"]
        if gate["kind"] == GateKind.IMPLEMENTATION_APPROVAL.value
    )
    approval["controlling"] = False
    with pytest.raises(GraphValidationError, match="non-controlling"):
        restore_state(payload)
    approval["controlling"] = True
    approval["verdict"]["report_reference"] = "reports/tampered.json"
    with pytest.raises(SerializationError, match="does not match deterministic event replay"):
        restore_state(payload)


def test_restore_replay_rejects_materialized_rejection_verdict_mutation():
    current = author_complete(start(state(), GateKind.AUTHOR, "author", "author-start"))
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-start")
    current = verdict(current, GateKind.COMPLETENESS_QA, "qa", VerdictDecision.REJECT, "qa-reject")
    assert restore_state(serialize_state(current)) == current
    payload = json.loads(serialize_state(current))
    rejection = next(
        gate
        for gate in payload["revisions"][0]["gates"]
        if gate["kind"] == GateKind.COMPLETENESS_QA.value
    )
    rejection["verdict"]["reviewer"] = "other-reviewer"
    with pytest.raises(SerializationError, match="does not match deterministic event replay"):
        restore_state(payload)


def test_restored_terminal_rejection_requires_controlling_review_evidence():
    current = author_complete(start(state(), GateKind.AUTHOR, "author", "author-start"))
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-start")
    current = verdict(current, GateKind.COMPLETENESS_QA, "qa", VerdictDecision.REJECT, "qa-reject")
    payload = json.loads(serialize_state(current))
    rejected_gate = next(
        gate
        for gate in payload["revisions"][0]["gates"]
        if gate["kind"] == GateKind.COMPLETENESS_QA.value
    )
    rejected_gate["kind"] = GateKind.AUTHOR.value
    with pytest.raises(GraphValidationError, match="non-review gate"):
        restore_state(payload)


def test_successor_is_single_active_chain_and_cannot_fork_predecessor():
    current = author_complete(start(state(), GateKind.AUTHOR, "author", "author-start"))
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-start")
    current = verdict(current, GateKind.COMPLETENESS_QA, "qa", VerdictDecision.REJECT, "qa-reject")
    current = transition(
        current,
        event(
            "r2",
            "wf-1",
            EventType.SUCCESSOR_REVISION_STARTED,
            actor="author-2",
            occurred_at=NOW,
            revision_id="rev-1",
            payload={
                "revision_id": "rev-2",
                "author": "author-2",
                "artifact_identity": artifact(created_by="author-2"),
            },
        ),
    )
    with pytest.raises(IllegalTransitionError, match="active terminal predecessor"):
        transition(
            current,
            event(
                "r3",
                "wf-1",
                EventType.SUCCESSOR_REVISION_STARTED,
                actor="author-3",
                occurred_at=NOW,
                revision_id="rev-1",
                payload={
                    "revision_id": "rev-3",
                    "author": "author-3",
                    "artifact_identity": artifact(created_by="author-3"),
                },
            ),
        )
    assert [
        revision.revision_id
        for revision in current.revisions
        if revision.status is RevisionStatus.ACTIVE
    ] == ["rev-2"]


def test_controlling_review_requires_identified_reviewer_and_sha256_report():
    current = author_complete(start(state(), GateKind.AUTHOR, "author", "author-start"))
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-start")
    malformed = ReviewVerdict(
        VerdictDecision.APPROVE,
        "",
        "",
        artifact(),
        (),
        "report",
        "not-a-sha256",
        "",
    )
    with pytest.raises(IllegalTransitionError, match="reviewer identity"):
        transition(
            current,
            event(
                "malformed-report",
                "wf-1",
                EventType.REVIEW_VERDICT_ISSUED,
                actor="",
                occurred_at=NOW,
                revision_id="rev-1",
                gate_id=gate_id("rev-1", GateKind.COMPLETENESS_QA),
                payload={"verdict": malformed},
            ),
        )


def test_freeze_rejects_incomplete_artifact_identity():
    current = author_complete(start(state(), GateKind.AUTHOR, "author", "author-start"))
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-start")
    current = verdict(
        current, GateKind.COMPLETENESS_QA, "qa", VerdictDecision.APPROVE, "qa-approve"
    )
    current = start(current, GateKind.FREEZE, "freezer", "freeze-start")
    incomplete = ArtifactIdentity("architecture", (), {"path": "a" * 64}, {}, True, NOW, "author")
    with pytest.raises(IllegalTransitionError, match="complete frozen artifact"):
        transition(
            current,
            event(
                "bad-freeze",
                "wf-1",
                EventType.ARTIFACT_FROZEN,
                actor="freezer",
                occurred_at=NOW,
                revision_id="rev-1",
                gate_id=gate_id("rev-1", GateKind.FREEZE),
                payload={"artifact_identity": incomplete},
            ),
        )


def test_duplicate_events_are_noops_and_changed_duplicate_id_is_error():
    initial = state()
    started = start(initial, GateKind.AUTHOR, "author", "same")
    assert transition(started, started.events[-1]) is started
    changed = event(
        "same",
        "wf-1",
        EventType.GATE_STARTED,
        actor="other",
        occurred_at=NOW,
        revision_id="rev-1",
        gate_id=gate_id("rev-1", GateKind.AUTHOR),
    )
    with pytest.raises(EventConflictError):
        transition(started, changed)


def test_json_round_trip_and_restored_continuation_are_deterministic():
    current = approved_through_freeze()
    serialized = serialize_state(current)
    restored = restore_state(serialized)
    assert serialize_state(restored) == serialized
    next_one = start(current, GateKind.FEASIBILITY_REVIEW, "feasibility", "feas-start")
    next_two = start(restored, GateKind.FEASIBILITY_REVIEW, "feasibility", "feas-start")
    assert serialize_state(next_one) == serialize_state(next_two)


def test_real_world_regression_sequence():
    # Revision 1: self-review fails, transport failure does not become verdict, then reject archives.
    current = author_complete(
        start(state(), GateKind.AUTHOR, "author", "r1-author-start"), "r1-author-complete"
    )
    with pytest.raises(ReviewerIndependenceError):
        start(current, GateKind.COMPLETENESS_QA, "author", "r1-self-review")
    current = start(current, GateKind.COMPLETENESS_QA, "reviewer-1", "r1-review-start")
    current = transition(
        current,
        event(
            "r1-transport",
            "wf-1",
            EventType.OPERATIONAL_FAILURE_RECORDED,
            actor="system",
            occurred_at=NOW,
            revision_id="rev-1",
            gate_id=gate_id("rev-1", GateKind.COMPLETENESS_QA),
            payload={"kind": "transport"},
        ),
    )
    assert current.gate("rev-1", gate_id("rev-1", GateKind.COMPLETENESS_QA)).verdict is None
    current = start(current, GateKind.COMPLETENESS_QA, "reviewer-1", "r1-review-retry")
    current = verdict(
        current, GateKind.COMPLETENESS_QA, "reviewer-1", VerdictDecision.REJECT, "r1-reject"
    )
    # Revision 2: feasibility approves; stale cache says approve; hashed security reject controls.
    current = transition(
        current,
        event(
            "r2",
            "wf-1",
            EventType.SUCCESSOR_REVISION_STARTED,
            actor="author-2",
            occurred_at=NOW,
            revision_id="rev-1",
            payload={
                "revision_id": "rev-2",
                "author": "author-2",
                "artifact_identity": artifact(created_by="author-2"),
            },
        ),
    )
    current = start(current, GateKind.AUTHOR, "author-2", "r2-author-start")
    current = author_complete(current, "r2-author-complete")
    current = start(current, GateKind.COMPLETENESS_QA, "qa-2", "r2-qa-start")
    current = verdict(
        current, GateKind.COMPLETENESS_QA, "qa-2", VerdictDecision.APPROVE, "r2-qa-approve"
    )
    current = start(current, GateKind.FREEZE, "freezer", "r2-freeze-start")
    current = freeze(current)
    current = start(current, GateKind.FEASIBILITY_REVIEW, "feasibility", "r2-feas-start")
    current = verdict(
        current,
        GateKind.FEASIBILITY_REVIEW,
        "feasibility",
        VerdictDecision.APPROVE,
        "r2-feas-approve",
    )
    current = transition(
        current,
        event(
            "r2-cache",
            "wf-1",
            EventType.METADATA_OBSERVED,
            actor="kanban",
            occurred_at=NOW,
            payload={"security": "approve"},
        ),
    )
    current = start(current, GateKind.SECURITY_REVIEW, "security", "r2-security-start")
    current = verdict(
        current, GateKind.SECURITY_REVIEW, "security", VerdictDecision.REJECT, "r2-security-reject"
    )
    assert current.revision("rev-2").status is RevisionStatus.REJECTED
    # Revision 3 is a replacement; an operator-owned prerequisite on it ends work without new gates.
    current = transition(
        current,
        event(
            "r3",
            "wf-1",
            EventType.SUCCESSOR_REVISION_STARTED,
            actor="author-3",
            occurred_at=NOW,
            revision_id="rev-2",
            payload={
                "revision_id": "rev-3",
                "author": "author-3",
                "artifact_identity": artifact(created_by="author-3"),
            },
        ),
    )
    current = transition(
        current,
        event(
            "operator-needed",
            "wf-1",
            EventType.OPERATOR_INPUT_REQUIRED,
            actor="system",
            occurred_at=NOW,
            revision_id="rev-3",
            payload={
                "decision_id": "operator-prereqs",
                "requested_fields": [
                    "provider_accounts",
                    "credentials",
                    "publication_identity",
                    "budget",
                    "policy",
                ],
            },
        ),
    )
    assert current.run.status.value == "needs_operator"
    assert all(
        gate.status in {GateStatus.SKIPPED, GateStatus.SUCCEEDED, GateStatus.PENDING}
        for gate in current.revision("rev-3").gates
    )
    assert transition(current, current.events[-1]) is current
    assert restore_state(serialize_state(current)) == current


def test_creation_event_is_first_and_normal_transitions_reject_new_creation_events():
    initial = state()
    creation = initial.events[0]
    assert creation.event_type is EventType.WORKFLOW_CREATED
    assert creation.gate_id is None
    assert creation.actor == initial.run.created_by
    assert creation.occurred_at == initial.run.created_at
    assert transition(initial, creation) is initial
    with pytest.raises(IllegalTransitionError, match="only valid as genesis"):
        transition(
            initial,
            event(
                "another-creation",
                "wf-1",
                EventType.WORKFLOW_CREATED,
                actor="author",
                occurred_at=NOW,
                revision_id="rev-1",
                payload=dict(creation.payload),
            ),
        )


def test_restore_requires_one_first_well_formed_creation_event():
    payload = json.loads(serialize_state(state()))
    payload["events"] = []
    payload["event_digests"] = {}
    with pytest.raises(SerializationError, match="exactly one first creation"):
        restore_state(payload)

    payload = json.loads(serialize_state(state()))
    duplicate = dict(payload["events"][0])
    duplicate["event_id"] = "workflow-created:wf-1:rev-1-copy"
    payload["events"].append(duplicate)
    reindex_events(payload)
    with pytest.raises(SerializationError, match="exactly one first creation"):
        restore_state(payload)

    payload = json.loads(serialize_state(start(state(), GateKind.AUTHOR, "author", "author-start")))
    payload["events"][:2] = reversed(payload["events"][:2])
    reindex_events(payload)
    with pytest.raises(SerializationError, match="exactly one first creation"):
        restore_state(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda creation: creation["payload"].update({"unknown": "injected"}),
        lambda creation: creation.update({"gate_id": "rev-1:author"}),
        lambda creation: creation.update({"actor": "other"}),
        lambda creation: creation.update({"occurred_at": "2026-07-13T20:01:00Z"}),
        lambda creation: creation["payload"].update({"max_attempts": 99}),
        lambda creation: creation["payload"]["artifact_identity"].update({"frozen": True}),
        lambda creation: creation["payload"]["artifact_identity"].update({"created_by": "other"}),
    ],
)
def test_restore_rejects_malformed_creation_event_fields(mutate):
    payload = json.loads(serialize_state(state()))
    mutate(payload["events"][0])
    reindex_events(payload)
    with pytest.raises(SerializationError):
        restore_state(payload)


def test_restore_rejects_snapshot_only_policy_and_genesis_identity_tampering():
    payload = json.loads(serialize_state(state()))
    for gate in payload["revisions"][0]["gates"]:
        if gate["kind"] not in {
            GateKind.ARCHIVE_REJECTION.value,
            GateKind.OPERATOR_ESCALATION.value,
        }:
            gate["max_attempts"] = 99
    with pytest.raises(SerializationError, match="does not match deterministic event replay"):
        restore_state(payload)

    payload = json.loads(serialize_state(state()))
    identity = payload["revisions"][0]["artifact_identity"]
    identity["hashes"]["docs/architecture.md"] = "f" * 64
    author = next(gate for gate in payload["revisions"][0]["gates"] if gate["kind"] == "author")
    author["artifact_identity"] = identity
    with pytest.raises(SerializationError, match="does not match deterministic event replay"):
        restore_state(payload)


def test_restore_rejects_genesis_only_and_coherent_snapshot_revision_tampering():
    payload = json.loads(serialize_state(state()))
    creation = payload["events"][0]
    creation["actor"] = "other"
    creation["payload"]["author"] = "other"
    creation["payload"]["artifact_identity"]["created_by"] = "other"
    reindex_events(payload)
    with pytest.raises(SerializationError, match="creation event does not match materialized run"):
        restore_state(payload)

    payload = json.loads(serialize_state(state()))
    payload["run"]["active_revision"] = "rev-injected"
    revision = payload["revisions"][0]
    revision["revision_id"] = "rev-injected"
    for gate in revision["gates"]:
        gate["revision_id"] = "rev-injected"
        gate["gate_id"] = gate["gate_id"].replace("rev-1", "rev-injected")
        gate["dependencies"] = [
            item.replace("rev-1", "rev-injected") for item in gate["dependencies"]
        ]
    with pytest.raises(SerializationError, match="does not match deterministic event replay"):
        restore_state(payload)


def test_restore_rejects_successor_snapshot_topology_or_policy_injection():
    current = author_complete(start(state(), GateKind.AUTHOR, "author", "author-start"))
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-start")
    current = verdict(current, GateKind.COMPLETENESS_QA, "qa", VerdictDecision.REJECT, "qa-reject")
    current = transition(
        current,
        event(
            "r2",
            "wf-1",
            EventType.SUCCESSOR_REVISION_STARTED,
            actor="author-2",
            occurred_at=NOW,
            revision_id="rev-1",
            payload={
                "revision_id": "rev-2",
                "author": "author-2",
                "artifact_identity": artifact(created_by="author-2"),
            },
        ),
    )
    payload = json.loads(serialize_state(current))
    payload["revisions"][1]["gates"][0]["max_attempts"] = 99
    payload["revisions"][1]["gates"][1]["dependencies"] = []
    with pytest.raises(SerializationError, match="does not match deterministic event replay"):
        restore_state(payload)


def artifact_nodes(value):
    """Return all serialized artifact identities in a hostile state payload."""
    nodes = []
    if isinstance(value, dict):
        if set(value) == {
            "artifact_id",
            "references",
            "hashes",
            "byte_sizes",
            "frozen",
            "frozen_at",
            "created_by",
        }:
            nodes.append(value)
        for item in value.values():
            nodes.extend(artifact_nodes(item))
    elif isinstance(value, list):
        for item in value:
            nodes.extend(artifact_nodes(item))
    return nodes


@pytest.mark.parametrize(
    "mutate",
    [
        lambda identity: identity.update({"hashes": ["not-a-mapping"]}),
        lambda identity: identity["hashes"].update({"docs/architecture.md": 7}),
        lambda identity: identity.update({"byte_sizes": [42]}),
        lambda identity: identity["byte_sizes"].update({"docs/architecture.md": -1}),
        lambda identity: identity["byte_sizes"].update({"docs/architecture.md": True}),
        lambda identity: identity.update({"references": "docs/architecture.md"}),
        lambda identity: identity.update({"frozen": "false"}),
        lambda identity: identity.update({"frozen": 0}),
        lambda identity: identity.update({"frozen": 1}),
        lambda identity: identity.pop("hashes"),
        lambda identity: identity.update({"injected": "field"}),
    ],
)
def test_restore_strictly_rejects_coherent_hostile_artifact_identity(mutate):
    payload = json.loads(serialize_state(state()))
    # Mutate event, snapshot, and digest coherently: raw parsing must reject it.
    for identity in artifact_nodes(payload):
        mutate(identity)
    reindex_events(payload)
    with pytest.raises(SerializationError, match="artifact"):
        restore_state(payload)


@pytest.mark.parametrize(
    "field,value",
    [("frozen", True), ("frozen_at", NOW), ("created_by", "other")],
)
def test_restore_rejects_coherent_invalid_genesis_identity_semantics(field, value):
    payload = json.loads(serialize_state(state()))
    for identity in artifact_nodes(payload):
        identity[field] = value
    reindex_events(payload)
    with pytest.raises(SerializationError):
        restore_state(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_id", 1),
        ("event_id", True),
        ("workflow_id", 1),
        ("revision_id", True),
        ("actor", 1),
        ("occurred_at", True),
    ],
)
def test_restore_rejects_non_string_event_envelope_fields(field, value):
    payload = json.loads(serialize_state(state()))
    payload["events"][0][field] = value
    reindex_events(payload)
    with pytest.raises(SerializationError, match="event"):
        restore_state(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision_number", True),
        ("revision_number", 1.0),
        ("max_attempts", True),
        ("max_attempts", 1),
    ],
)
def test_restore_rejects_noncanonical_genesis_policy_fields(field, value):
    payload = json.loads(serialize_state(state()))
    payload["events"][0]["payload"][field] = value
    reindex_events(payload)
    with pytest.raises(SerializationError):
        restore_state(payload)


def test_restore_rejects_malformed_artifacts_in_freeze_and_verdict_events():
    frozen_payload = json.loads(serialize_state(approved_through_freeze()))
    freeze_event = next(
        item
        for item in frozen_payload["events"]
        if item["event_type"] == EventType.ARTIFACT_FROZEN.value
    )
    freeze_event["payload"]["artifact_identity"] = []
    reindex_events(frozen_payload)
    with pytest.raises(SerializationError, match="artifact"):
        restore_state(frozen_payload)

    review_state = start(
        approved_through_freeze(), GateKind.FEASIBILITY_REVIEW, "feasibility", "feas-start"
    )
    review_state = verdict(
        review_state,
        GateKind.FEASIBILITY_REVIEW,
        "feasibility",
        VerdictDecision.APPROVE,
        "feas-approve",
    )
    review_payload = json.loads(serialize_state(review_state))
    review_event = next(
        item
        for item in review_payload["events"]
        if item["event_type"] == EventType.REVIEW_VERDICT_ISSUED.value
    )
    review_event["payload"]["verdict"]["reviewed_artifact_identity"]["byte_sizes"] = {
        "docs/architecture.md": False
    }
    reindex_events(review_payload)
    with pytest.raises(SerializationError, match="artifact"):
        restore_state(review_payload)


def test_restore_rejects_malformed_artifact_in_successor_event():
    current = author_complete(start(state(), GateKind.AUTHOR, "author", "author-start"))
    current = start(current, GateKind.COMPLETENESS_QA, "qa", "qa-start")
    current = verdict(current, GateKind.COMPLETENESS_QA, "qa", VerdictDecision.REJECT, "qa-reject")
    current = transition(
        current,
        event(
            "r2",
            "wf-1",
            EventType.SUCCESSOR_REVISION_STARTED,
            actor="author-2",
            occurred_at=NOW,
            revision_id="rev-1",
            payload={
                "revision_id": "rev-2",
                "author": "author-2",
                "artifact_identity": artifact(created_by="author-2"),
            },
        ),
    )
    payload = json.loads(serialize_state(current))
    successor = next(
        item
        for item in payload["events"]
        if item["event_type"] == EventType.SUCCESSOR_REVISION_STARTED.value
    )
    successor["payload"]["artifact_identity"]["references"] = "not-a-list"
    reindex_events(payload)
    with pytest.raises(SerializationError, match="artifact"):
        restore_state(payload)
