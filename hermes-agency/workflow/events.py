"""Event construction and canonical identity for deterministic workflows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from .models import EventType, WorkflowEvent, thaw


def jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: jsonable(getattr(value, item.name)) for item in fields(value)}
    if hasattr(value, "items"):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    return thaw(value)


def canonical_event_json(event: WorkflowEvent) -> str:
    """Return a byte-stable representation used for idempotency identity."""
    return json.dumps(jsonable(event), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_digest(event: WorkflowEvent) -> str:
    return hashlib.sha256(canonical_event_json(event).encode("utf-8")).hexdigest()


def event(
    event_id: str,
    workflow_id: str,
    event_type: EventType | str,
    *,
    actor: str,
    occurred_at: str,
    revision_id: str | None = None,
    gate_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> WorkflowEvent:
    """Small explicit constructor useful to callers and tests."""
    return WorkflowEvent(
        event_id=event_id,
        workflow_id=workflow_id,
        revision_id=revision_id,
        gate_id=gate_id,
        event_type=EventType(event_type),
        actor=actor,
        payload=payload or {},
        occurred_at=occurred_at,
    )
