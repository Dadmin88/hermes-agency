"""Canonical JSON serialization for complete workflow state."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .errors import SerializationError
from .events import event_digest, jsonable
from .graph import validate_state
from .models import (
    ArtifactIdentity,
    EventType,
    GateKind,
    GateStatus,
    OperatorDecision,
    OperatorDecisionStatus,
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


def artifact_to_dict(value: ArtifactIdentity | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "artifact_id": value.artifact_id,
        "references": list(value.references),
        "hashes": thaw(value.hashes),
        "byte_sizes": thaw(value.byte_sizes),
        "frozen": value.frozen,
        "frozen_at": value.frozen_at,
        "created_by": value.created_by,
    }


def artifact_from_dict(data: dict[str, Any] | None) -> ArtifactIdentity | None:
    if data is None:
        return None
    return ArtifactIdentity(
        artifact_id=str(data["artifact_id"]),
        references=tuple(data.get("references") or ()),
        hashes=data.get("hashes") or {},
        byte_sizes=data.get("byte_sizes") or {},
        frozen=bool(data.get("frozen", False)),
        frozen_at=data.get("frozen_at"),
        created_by=str(data.get("created_by") or ""),
    )


def verdict_to_dict(value: ReviewVerdict | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "decision": value.decision.value,
        "reviewer": value.reviewer,
        "reviewer_role": value.reviewer_role,
        "reviewed_artifact_identity": artifact_to_dict(value.reviewed_artifact_identity),
        "findings": thaw(value.findings),
        "report_reference": value.report_reference,
        "report_hash": value.report_hash,
        "issued_at": value.issued_at,
    }


def verdict_from_dict(data: dict[str, Any] | None) -> ReviewVerdict | None:
    if data is None:
        return None
    identity = artifact_from_dict(data.get("reviewed_artifact_identity"))
    if identity is None:
        raise SerializationError("review verdict is missing artifact identity")
    return ReviewVerdict(
        decision=VerdictDecision(data["decision"]),
        reviewer=str(data["reviewer"]),
        reviewer_role=str(data.get("reviewer_role") or ""),
        reviewed_artifact_identity=identity,
        findings=tuple(data.get("findings") or ()),
        report_reference=str(data.get("report_reference") or ""),
        report_hash=str(data.get("report_hash") or ""),
        issued_at=str(data.get("issued_at") or ""),
    )


def gate_to_dict(value: WorkflowGate) -> dict[str, Any]:
    return {
        "gate_id": value.gate_id,
        "revision_id": value.revision_id,
        "kind": value.kind.value,
        "status": value.status.value,
        "dependencies": list(value.dependencies),
        "assigned_agent": value.assigned_agent,
        "author_agent": value.author_agent,
        "attempt": value.attempt,
        "max_attempts": value.max_attempts,
        "controlling": value.controlling,
        "verdict": verdict_to_dict(value.verdict),
        "artifact_identity": artifact_to_dict(value.artifact_identity),
        "result": thaw(value.result),
        "error": thaw(value.error),
        "started_at": value.started_at,
        "completed_at": value.completed_at,
    }


def gate_from_dict(data: dict[str, Any]) -> WorkflowGate:
    return WorkflowGate(
        gate_id=str(data["gate_id"]),
        revision_id=str(data["revision_id"]),
        kind=GateKind(data["kind"]),
        status=GateStatus(data["status"]),
        dependencies=tuple(data.get("dependencies") or ()),
        assigned_agent=data.get("assigned_agent"),
        author_agent=data.get("author_agent"),
        attempt=int(data.get("attempt", 0)),
        max_attempts=int(data.get("max_attempts", 1)),
        controlling=bool(data.get("controlling", True)),
        verdict=verdict_from_dict(data.get("verdict")),
        artifact_identity=artifact_from_dict(data.get("artifact_identity")),
        result=data.get("result") or {},
        error=data.get("error"),
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
    )


def event_to_dict(value: WorkflowEvent) -> dict[str, Any]:
    return {
        "event_id": value.event_id,
        "workflow_id": value.workflow_id,
        "revision_id": value.revision_id,
        "gate_id": value.gate_id,
        "event_type": value.event_type.value,
        "actor": value.actor,
        "payload": jsonable(value.payload),
        "occurred_at": value.occurred_at,
    }


def state_to_dict(state: WorkflowState) -> dict[str, Any]:
    return {
        "run": {
            "workflow_id": state.run.workflow_id,
            "workflow_type": state.run.workflow_type,
            "objective": state.run.objective,
            "status": state.run.status.value,
            "active_revision": state.run.active_revision,
            "created_by": state.run.created_by,
            "created_at": state.run.created_at,
            "updated_at": state.run.updated_at,
            "metadata": thaw(state.run.metadata),
        },
        "revisions": [
            {
                "revision_id": revision.revision_id,
                "workflow_id": revision.workflow_id,
                "revision_number": revision.revision_number,
                "status": revision.status.value,
                "predecessor_revision_id": revision.predecessor_revision_id,
                "successor_revision_id": revision.successor_revision_id,
                "artifact_identity": artifact_to_dict(revision.artifact_identity),
                "gates": [gate_to_dict(gate) for gate in revision.gates],
                "created_at": revision.created_at,
                "completed_at": revision.completed_at,
                "terminal_reason": revision.terminal_reason,
            }
            for revision in state.revisions
        ],
        "events": [event_to_dict(item) for item in state.events],
        "event_digests": thaw(state.event_digests),
        "operator_decisions": [
            {
                "decision_id": item.decision_id,
                "requested_fields": list(item.requested_fields),
                "supplied_values": thaw(item.supplied_values),
                "requested_at": item.requested_at,
                "resolved_at": item.resolved_at,
                "status": item.status.value,
            }
            for item in state.operator_decisions
        ],
    }


def serialize_state(state: WorkflowState) -> str:
    validate_state(state)
    return json.dumps(
        state_to_dict(state), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _rehydrate_event(event: WorkflowEvent) -> WorkflowEvent:
    """Restore typed event payloads before deterministic replay."""
    payload = dict(event.payload)
    if event.event_type is EventType.WORKFLOW_CREATED:
        payload["artifact_identity"] = artifact_from_dict(payload.get("artifact_identity"))
    elif event.event_type is EventType.REVIEW_VERDICT_ISSUED:
        payload["verdict"] = verdict_from_dict(payload.get("verdict"))
    elif event.event_type in {
        EventType.ARTIFACT_FROZEN,
        EventType.SUCCESSOR_REVISION_STARTED,
    }:
        payload["artifact_identity"] = artifact_from_dict(payload.get("artifact_identity"))
    return replace(event, payload=payload)


_GENESIS_PAYLOAD_KEYS = frozenset(
    {
        "workflow_id",
        "workflow_type",
        "revision_id",
        "revision_number",
        "objective",
        "author",
        "created_at",
        "artifact_identity",
        "max_attempts",
    }
)


def _creation_event_id(workflow_id: str, revision_id: str) -> str:
    return f"workflow-created:{workflow_id}:{revision_id}"


def _validate_genesis_event(event: WorkflowEvent) -> WorkflowEvent:
    """Validate the only ledger record allowed to supply creation inputs."""
    raw_identity = event.payload.get("artifact_identity")
    if isinstance(raw_identity, Mapping) and set(raw_identity) != {
        "artifact_id",
        "references",
        "hashes",
        "byte_sizes",
        "frozen",
        "frozen_at",
        "created_by",
    }:
        raise SerializationError("workflow creation artifact identity has an invalid schema")
    event = _rehydrate_event(event)
    payload = dict(event.payload)
    if event.event_type is not EventType.WORKFLOW_CREATED:
        raise SerializationError("first ledger event must be workflow creation")
    if set(payload) != _GENESIS_PAYLOAD_KEYS:
        raise SerializationError("workflow creation payload has an invalid schema")
    if (
        event.gate_id is not None
        or not event.workflow_id
        or not event.revision_id
        or event.event_id != _creation_event_id(event.workflow_id, event.revision_id)
        or payload["workflow_id"] != event.workflow_id
        or payload["workflow_type"] != "architecture-governance"
        or payload["revision_id"] != event.revision_id
        or payload["revision_number"] != 1
        or not isinstance(payload["objective"], str)
        or not isinstance(payload["author"], str)
        or not payload["author"]
        or event.actor != payload["author"]
        or not isinstance(payload["created_at"], str)
        or not payload["created_at"]
        or event.occurred_at != payload["created_at"]
        or payload["max_attempts"] != 2
        or type(payload["max_attempts"]) is not int
    ):
        raise SerializationError("workflow creation envelope does not match its payload")
    identity = payload["artifact_identity"]
    if (
        not isinstance(identity, ArtifactIdentity)
        or identity.frozen
        or identity.frozen_at is not None
        or identity.created_by != payload["author"]
    ):
        raise SerializationError("workflow creation requires an unfrozen author-owned artifact")
    return event


def _replay_from_genesis(state: WorkflowState) -> WorkflowState:
    """Rebuild materialized state from the canonical template and its event ledger."""
    if state.run.workflow_type != "architecture-governance":
        raise SerializationError("unsupported workflow type")
    creation_events = [
        item for item in state.events if item.event_type is EventType.WORKFLOW_CREATED
    ]
    if len(creation_events) != 1 or not state.events or state.events[0] != creation_events[0]:
        raise SerializationError("workflow ledger requires exactly one first creation event")
    genesis = _validate_genesis_event(creation_events[0])
    payload = dict(genesis.payload)
    if (
        state.run.workflow_id != genesis.workflow_id
        or state.run.workflow_type != payload["workflow_type"]
        or state.run.objective != payload["objective"]
        or state.run.created_by != payload["author"]
        or state.run.created_at != payload["created_at"]
    ):
        raise SerializationError("workflow creation event does not match materialized run")
    from .templates import architecture_governance_state
    from .transitions import transition

    replayed = architecture_governance_state(
        workflow_id=genesis.workflow_id,
        revision_id=genesis.revision_id or "",
        objective=payload["objective"],
        created_by=payload["author"],
        created_at=payload["created_at"],
        artifact_identity=payload["artifact_identity"],
        max_attempts=payload["max_attempts"],
    )
    if replayed.events[0] != genesis or replayed.event_digests[genesis.event_id] != event_digest(
        genesis
    ):
        raise SerializationError("workflow creation event is not canonical")
    for item in state.events[1:]:
        replayed = transition(replayed, _rehydrate_event(item))
    return replayed


def restore_state(payload: str | bytes | dict[str, Any]) -> WorkflowState:
    try:
        data = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
        run_data = data["run"]
        run = WorkflowRun(
            workflow_id=str(run_data["workflow_id"]),
            workflow_type=str(run_data["workflow_type"]),
            objective=str(run_data["objective"]),
            status=WorkflowStatus(run_data["status"]),
            active_revision=run_data.get("active_revision"),
            created_by=str(run_data.get("created_by") or ""),
            created_at=str(run_data.get("created_at") or ""),
            updated_at=str(run_data.get("updated_at") or ""),
            metadata=run_data.get("metadata") or {},
        )
        revisions = tuple(
            WorkflowRevision(
                revision_id=str(item["revision_id"]),
                workflow_id=str(item["workflow_id"]),
                revision_number=int(item["revision_number"]),
                status=RevisionStatus(item["status"]),
                predecessor_revision_id=item.get("predecessor_revision_id"),
                successor_revision_id=item.get("successor_revision_id"),
                artifact_identity=artifact_from_dict(item.get("artifact_identity")),
                gates=tuple(gate_from_dict(gate) for gate in item.get("gates") or ()),
                created_at=str(item.get("created_at") or ""),
                completed_at=item.get("completed_at"),
                terminal_reason=item.get("terminal_reason"),
            )
            for item in data["revisions"]
        )
        events = tuple(
            WorkflowEvent(
                event_id=str(item["event_id"]),
                workflow_id=str(item["workflow_id"]),
                revision_id=item.get("revision_id"),
                gate_id=item.get("gate_id"),
                event_type=EventType(item["event_type"]),
                actor=str(item["actor"]),
                payload=item.get("payload") or {},
                occurred_at=str(item.get("occurred_at") or ""),
            )
            for item in data.get("events") or ()
        )
        decisions = tuple(
            OperatorDecision(
                decision_id=str(item["decision_id"]),
                requested_fields=tuple(item.get("requested_fields") or ()),
                supplied_values=item.get("supplied_values") or {},
                requested_at=str(item.get("requested_at") or ""),
                resolved_at=item.get("resolved_at"),
                status=OperatorDecisionStatus(item["status"]),
            )
            for item in data.get("operator_decisions") or ()
        )
        state = WorkflowState(
            run=run,
            revisions=revisions,
            events=events,
            event_digests=data.get("event_digests") or {},
            operator_decisions=decisions,
        )
        validate_state(state)
        replayed = _replay_from_genesis(state)
        if state_to_dict(replayed) != state_to_dict(state):
            raise SerializationError(
                "materialized workflow state does not match deterministic event replay"
            )
        return replayed
    except SerializationError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SerializationError(f"cannot restore workflow state: {exc}") from exc
