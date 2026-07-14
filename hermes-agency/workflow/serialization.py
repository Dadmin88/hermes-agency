"""Canonical JSON serialization for complete workflow state.

The restore path is a hostile-input boundary.  Parse raw values before constructing
models: dataclass constructors intentionally normalize trusted in-process input,
but restoration must never let that normalization reinterpret serialized data.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, TypeVar

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

_T = TypeVar("_T")
_ARTIFACT_KEYS = frozenset(
    {"artifact_id", "references", "hashes", "byte_sizes", "frozen", "frozen_at", "created_by"}
)
_VERDICT_KEYS = frozenset(
    {
        "decision",
        "reviewer",
        "reviewer_role",
        "reviewed_artifact_identity",
        "findings",
        "report_reference",
        "report_hash",
        "issued_at",
    }
)
_GATE_KEYS = frozenset(
    {
        "gate_id",
        "revision_id",
        "kind",
        "status",
        "dependencies",
        "assigned_agent",
        "author_agent",
        "attempt",
        "max_attempts",
        "controlling",
        "verdict",
        "artifact_identity",
        "result",
        "error",
        "started_at",
        "completed_at",
    }
)
_REVISION_KEYS = frozenset(
    {
        "revision_id",
        "workflow_id",
        "revision_number",
        "status",
        "predecessor_revision_id",
        "successor_revision_id",
        "artifact_identity",
        "gates",
        "created_at",
        "completed_at",
        "terminal_reason",
    }
)
_EVENT_KEYS = frozenset(
    {
        "event_id",
        "workflow_id",
        "revision_id",
        "gate_id",
        "event_type",
        "actor",
        "payload",
        "occurred_at",
    }
)
_RUN_KEYS = frozenset(
    {
        "workflow_id",
        "workflow_type",
        "objective",
        "status",
        "active_revision",
        "created_by",
        "created_at",
        "updated_at",
        "metadata",
    }
)
_OPERATOR_DECISION_KEYS = frozenset(
    {"decision_id", "requested_fields", "supplied_values", "requested_at", "resolved_at", "status"}
)
_STATE_KEYS = frozenset({"run", "revisions", "events", "event_digests", "operator_decisions"})


def _invalid(context: str) -> SerializationError:
    return SerializationError(f"invalid serialized {context}")


def _mapping(value: Any, context: str, *, keys: frozenset[str] | None = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _invalid(context)
    if keys is not None and set(value) != keys:
        raise _invalid(f"{context} schema")
    return value


def _sequence(value: Any, context: str) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise _invalid(context)
    return tuple(value)


def _string(
    value: Any, context: str, *, allow_none: bool = False, nonempty: bool = False
) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or (nonempty and not value):
        raise _invalid(context)
    return value


def _integer(
    value: Any, context: str, *, allowed: set[int] | None = None, minimum: int | None = None
) -> int:
    if (
        type(value) is not int
        or (allowed is not None and value not in allowed)
        or (minimum is not None and value < minimum)
    ):
        raise _invalid(context)
    return value


def _json_value(value: Any, context: str = "value") -> Any:
    """Validate JSON-shaped untyped metadata without coercing keys or values."""
    if value is None or type(value) in {str, int, float, bool}:
        return value
    if isinstance(value, Mapping):
        return {key: _json_value(item, context) for key, item in _mapping(value, context).items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item, context) for item in value]
    raise _invalid(context)


def _enum(enum_type: type[_T], value: Any, context: str) -> _T:
    raw = _string(value, context, nonempty=True)
    try:
        return enum_type(raw)  # type: ignore[call-arg]
    except ValueError as exc:
        raise _invalid(context) from exc


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


def artifact_from_dict(
    data: Any, *, allow_none: bool = True, context: str = "artifact identity"
) -> ArtifactIdentity | None:
    if data is None and allow_none:
        return None
    raw = _mapping(data, context, keys=_ARTIFACT_KEYS)
    artifact_id = _string(raw["artifact_id"], f"{context}.artifact_id", nonempty=True)
    created_by = _string(raw["created_by"], f"{context}.created_by", nonempty=True)
    references = _sequence(raw["references"], f"{context}.references")
    if any(not isinstance(item, str) for item in references):
        raise _invalid(f"{context}.references")
    hashes_raw = _mapping(raw["hashes"], f"{context}.hashes")
    if any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in hashes_raw.items()
    ):
        raise _invalid(f"{context}.hashes")
    sizes_raw = _mapping(raw["byte_sizes"], f"{context}.byte_sizes")
    if any(
        not isinstance(key, str) or type(value) is not int or value < 0
        for key, value in sizes_raw.items()
    ):
        raise _invalid(f"{context}.byte_sizes")
    frozen = raw["frozen"]
    if type(frozen) is not bool:
        raise _invalid(f"{context}.frozen")
    frozen_at = _string(raw["frozen_at"], f"{context}.frozen_at", allow_none=True, nonempty=True)
    if (frozen and frozen_at is None) or (not frozen and frozen_at is not None):
        raise _invalid(f"{context}.frozen_at")
    return ArtifactIdentity(
        artifact_id=artifact_id or "",
        references=tuple(references),
        hashes=dict(hashes_raw),
        byte_sizes=dict(sizes_raw),
        frozen=frozen,
        frozen_at=frozen_at,
        created_by=created_by or "",
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


def verdict_from_dict(
    data: Any, *, allow_none: bool = True, context: str = "review verdict"
) -> ReviewVerdict | None:
    if data is None and allow_none:
        return None
    raw = _mapping(data, context, keys=_VERDICT_KEYS)
    identity = artifact_from_dict(
        raw["reviewed_artifact_identity"], allow_none=False, context=f"{context}.artifact_identity"
    )
    assert identity is not None
    findings = _sequence(raw["findings"], f"{context}.findings")
    return ReviewVerdict(
        decision=_enum(VerdictDecision, raw["decision"], f"{context}.decision"),
        reviewer=_string(raw["reviewer"], f"{context}.reviewer") or "",
        reviewer_role=_string(raw["reviewer_role"], f"{context}.reviewer_role") or "",
        reviewed_artifact_identity=identity,
        findings=tuple(_json_value(item, f"{context}.findings") for item in findings),
        report_reference=_string(raw["report_reference"], f"{context}.report_reference") or "",
        report_hash=_string(raw["report_hash"], f"{context}.report_hash") or "",
        issued_at=_string(raw["issued_at"], f"{context}.issued_at") or "",
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


def gate_from_dict(data: Any) -> WorkflowGate:
    raw = _mapping(data, "gate", keys=_GATE_KEYS)
    dependencies = _sequence(raw["dependencies"], "gate.dependencies")
    if any(not isinstance(item, str) for item in dependencies):
        raise _invalid("gate.dependencies")
    assigned = _string(raw["assigned_agent"], "gate.assigned_agent", allow_none=True)
    author = _string(raw["author_agent"], "gate.author_agent", allow_none=True)
    if type(raw["controlling"]) is not bool:
        raise _invalid("gate.controlling")
    error = raw["error"]
    if error is not None:
        _mapping(error, "gate.error")
    return WorkflowGate(
        gate_id=_string(raw["gate_id"], "gate.gate_id", nonempty=True) or "",
        revision_id=_string(raw["revision_id"], "gate.revision_id", nonempty=True) or "",
        kind=_enum(GateKind, raw["kind"], "gate.kind"),
        status=_enum(GateStatus, raw["status"], "gate.status"),
        dependencies=tuple(dependencies),
        assigned_agent=assigned,
        author_agent=author,
        attempt=_integer(raw["attempt"], "gate.attempt", minimum=0),
        max_attempts=_integer(raw["max_attempts"], "gate.max_attempts", minimum=1),
        controlling=raw["controlling"],
        verdict=verdict_from_dict(raw["verdict"], context="gate.verdict"),
        artifact_identity=artifact_from_dict(
            raw["artifact_identity"], context="gate.artifact_identity"
        ),
        result=_json_value(_mapping(raw["result"], "gate.result"), "gate.result"),
        error=_json_value(_mapping(error, "gate.error"), "gate.error")
        if error is not None
        else None,
        started_at=_string(raw["started_at"], "gate.started_at", allow_none=True),
        completed_at=_string(raw["completed_at"], "gate.completed_at", allow_none=True),
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


def _event_payload(event_type: EventType, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate typed authoritative payloads before transition code sees them."""
    if event_type is EventType.WORKFLOW_CREATED:
        if set(payload) != _GENESIS_PAYLOAD_KEYS:
            raise _invalid("workflow creation payload schema")
        artifact = artifact_from_dict(
            payload["artifact_identity"],
            allow_none=False,
            context="workflow creation artifact identity",
        )
        return {
            "workflow_id": _string(
                payload["workflow_id"], "workflow creation workflow_id", nonempty=True
            ),
            "workflow_type": _string(
                payload["workflow_type"], "workflow creation workflow_type", nonempty=True
            ),
            "revision_id": _string(
                payload["revision_id"], "workflow creation revision_id", nonempty=True
            ),
            "revision_number": _integer(
                payload["revision_number"], "workflow creation revision_number", allowed={1}
            ),
            "objective": _string(payload["objective"], "workflow creation objective"),
            "author": _string(payload["author"], "workflow creation author", nonempty=True),
            "created_at": _string(
                payload["created_at"], "workflow creation created_at", nonempty=True
            ),
            "artifact_identity": artifact,
            "max_attempts": _integer(
                payload["max_attempts"], "workflow creation max_attempts", allowed={2}
            ),
        }
    if event_type is EventType.ARTIFACT_FROZEN:
        if set(payload) != {"artifact_identity"}:
            raise _invalid("artifact frozen payload schema")
        return {
            "artifact_identity": artifact_from_dict(
                payload["artifact_identity"], allow_none=False, context="artifact frozen identity"
            )
        }
    if event_type is EventType.SUCCESSOR_REVISION_STARTED:
        if set(payload) not in (
            {"revision_id", "author", "artifact_identity"},
            {"revision_id", "author", "artifact_identity", "max_attempts"},
        ):
            raise _invalid("successor revision payload schema")
        parsed: dict[str, Any] = {
            "revision_id": _string(payload["revision_id"], "successor revision_id", nonempty=True),
            "author": _string(payload["author"], "successor author", nonempty=True),
            "artifact_identity": artifact_from_dict(
                payload["artifact_identity"],
                allow_none=False,
                context="successor artifact identity",
            ),
        }
        if "max_attempts" in payload:
            parsed["max_attempts"] = _integer(
                payload["max_attempts"], "successor max_attempts", allowed={1, 2}
            )
        return parsed
    if event_type is EventType.REVIEW_VERDICT_ISSUED:
        if set(payload) != {"verdict"}:
            raise _invalid("review verdict payload schema")
        return {
            "verdict": verdict_from_dict(
                payload["verdict"], allow_none=False, context="review verdict"
            )
        }
    return dict(_json_value(payload, "event payload"))


def _event_from_dict(data: Any) -> WorkflowEvent:
    raw = _mapping(data, "event", keys=_EVENT_KEYS)
    event_type = _enum(EventType, raw["event_type"], "event.event_type")
    payload = _mapping(raw["payload"], "event.payload")
    return WorkflowEvent(
        event_id=_string(raw["event_id"], "event.event_id", nonempty=True) or "",
        workflow_id=_string(raw["workflow_id"], "event.workflow_id", nonempty=True) or "",
        revision_id=_string(
            raw["revision_id"], "event.revision_id", allow_none=True, nonempty=True
        ),
        gate_id=_string(raw["gate_id"], "event.gate_id", allow_none=True, nonempty=True),
        event_type=event_type,
        actor=_string(raw["actor"], "event.actor", nonempty=True) or "",
        payload=_event_payload(event_type, payload),
        occurred_at=_string(raw["occurred_at"], "event.occurred_at", nonempty=True) or "",
    )


def _rehydrate_event(event: WorkflowEvent) -> WorkflowEvent:
    """Events are parsed raw before construction; retained for replay clarity."""
    return event


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
    if event.event_type is not EventType.WORKFLOW_CREATED:
        raise SerializationError("first ledger event must be workflow creation")
    payload = event.payload
    if (
        event.gate_id is not None
        or event.event_id != _creation_event_id(event.workflow_id, event.revision_id or "")
        or payload["workflow_id"] != event.workflow_id
        or payload["workflow_type"] != "architecture-governance"
        or payload["revision_id"] != event.revision_id
        or payload["revision_number"] != 1
        or event.actor != payload["author"]
        or event.occurred_at != payload["created_at"]
        or payload["max_attempts"] != 2
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
    if state.run.workflow_type != "architecture-governance":
        raise SerializationError("unsupported workflow type")
    creation_events = [
        item for item in state.events if item.event_type is EventType.WORKFLOW_CREATED
    ]
    if len(creation_events) != 1 or not state.events or state.events[0] != creation_events[0]:
        raise SerializationError("workflow ledger requires exactly one first creation event")
    genesis = _validate_genesis_event(creation_events[0])
    payload = genesis.payload
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
        replayed = transition(replayed, item)
    return replayed


def _revision_from_dict(data: Any) -> WorkflowRevision:
    raw = _mapping(data, "revision", keys=_REVISION_KEYS)
    return WorkflowRevision(
        revision_id=_string(raw["revision_id"], "revision.revision_id", nonempty=True) or "",
        workflow_id=_string(raw["workflow_id"], "revision.workflow_id", nonempty=True) or "",
        revision_number=_integer(raw["revision_number"], "revision.revision_number", minimum=1),
        status=_enum(RevisionStatus, raw["status"], "revision.status"),
        predecessor_revision_id=_string(
            raw["predecessor_revision_id"],
            "revision.predecessor_revision_id",
            allow_none=True,
            nonempty=True,
        ),
        successor_revision_id=_string(
            raw["successor_revision_id"],
            "revision.successor_revision_id",
            allow_none=True,
            nonempty=True,
        ),
        artifact_identity=artifact_from_dict(
            raw["artifact_identity"], context="revision.artifact_identity"
        ),
        gates=tuple(gate_from_dict(item) for item in _sequence(raw["gates"], "revision.gates")),
        created_at=_string(raw["created_at"], "revision.created_at", nonempty=True) or "",
        completed_at=_string(raw["completed_at"], "revision.completed_at", allow_none=True),
        terminal_reason=_string(
            raw["terminal_reason"], "revision.terminal_reason", allow_none=True
        ),
    )


def restore_state(payload: str | bytes | dict[str, Any]) -> WorkflowState:
    try:
        data = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
        raw = _mapping(data, "workflow state", keys=_STATE_KEYS)
        run_data = _mapping(raw["run"], "run", keys=_RUN_KEYS)
        run = WorkflowRun(
            workflow_id=_string(run_data["workflow_id"], "run.workflow_id", nonempty=True) or "",
            workflow_type=_string(run_data["workflow_type"], "run.workflow_type", nonempty=True)
            or "",
            objective=_string(run_data["objective"], "run.objective") or "",
            status=_enum(WorkflowStatus, run_data["status"], "run.status"),
            active_revision=_string(
                run_data["active_revision"], "run.active_revision", allow_none=True, nonempty=True
            ),
            created_by=_string(run_data["created_by"], "run.created_by", nonempty=True) or "",
            created_at=_string(run_data["created_at"], "run.created_at", nonempty=True) or "",
            updated_at=_string(run_data["updated_at"], "run.updated_at", nonempty=True) or "",
            metadata=_json_value(_mapping(run_data["metadata"], "run.metadata"), "run.metadata"),
        )
        revisions = tuple(
            _revision_from_dict(item) for item in _sequence(raw["revisions"], "revisions")
        )
        events = tuple(_event_from_dict(item) for item in _sequence(raw["events"], "events"))
        digests = _mapping(raw["event_digests"], "event digests")
        if any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in digests.items()
        ):
            raise _invalid("event digests")
        decisions = []
        for item in _sequence(raw["operator_decisions"], "operator decisions"):
            decision = _mapping(item, "operator decision", keys=_OPERATOR_DECISION_KEYS)
            fields = _sequence(decision["requested_fields"], "operator decision requested_fields")
            if any(not isinstance(field, str) for field in fields):
                raise _invalid("operator decision requested_fields")
            decisions.append(
                OperatorDecision(
                    decision_id=_string(
                        decision["decision_id"], "operator decision_id", nonempty=True
                    )
                    or "",
                    requested_fields=tuple(fields),
                    supplied_values=_json_value(
                        _mapping(decision["supplied_values"], "operator decision supplied_values"),
                        "operator decision supplied_values",
                    ),
                    requested_at=_string(
                        decision["requested_at"], "operator decision requested_at", nonempty=True
                    )
                    or "",
                    resolved_at=_string(
                        decision["resolved_at"], "operator decision resolved_at", allow_none=True
                    ),
                    status=_enum(
                        OperatorDecisionStatus, decision["status"], "operator decision status"
                    ),
                )
            )
        state = WorkflowState(
            run=run,
            revisions=revisions,
            events=events,
            event_digests=dict(digests),
            operator_decisions=tuple(decisions),
        )
        # Validate creation ownership before graph validation can expose a raw
        # hostile-serialization mutation as a domain validation exception.
        if events and events[0].event_type is EventType.WORKFLOW_CREATED:
            _validate_genesis_event(events[0])
        validate_state(state)
        replayed = _replay_from_genesis(state)
        if state_to_dict(replayed) != state_to_dict(state):
            raise SerializationError(
                "materialized workflow state does not match deterministic event replay"
            )
        return replayed
    except SerializationError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, AttributeError) as exc:
        raise SerializationError(f"cannot restore workflow state: {exc}") from exc
