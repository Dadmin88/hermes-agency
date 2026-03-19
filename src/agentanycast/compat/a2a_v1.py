"""A2A v1.0 protocol compatibility layer.

Converts between AgentAnycast's internal data models and the official
A2A v1.0 (``lf.a2a.v1``) JSON wire format. Used by the HTTP Bridge
when interoperating with standard A2A agents over HTTP.

The official spec uses slightly different field names, nesting, and
status representations. This module provides bidirectional conversion
so the rest of the codebase can work with our internal types while
speaking standards-compliant JSON on the wire.

Key differences handled:

* ``task_id`` <-> ``id``
* ``messages`` <-> ``history``
* ``TaskStatus`` enum <-> ``status`` object ``{state, message, timestamp}``
* ``TASK_STATUS_*`` <-> ``TASK_STATE_*`` naming
* Flat Part (``text``, ``data``, ``url``, ``raw``) in A2A v1.0
* ``AgentCard`` P2P extension stripped for A2A JSON output
* ``Skill`` <-> ``AgentSkill`` (with ``name`` / ``tags`` / ``examples``)

Example::

    from agentanycast.compat.a2a_v1 import task_to_a2a_json, task_from_a2a_json

    json_payload = task_to_a2a_json(internal_task)
    # Send json_payload to a standard A2A v1.0 agent ...
    restored = task_from_a2a_json(json_payload)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agentanycast.card import AgentCard, Skill
from agentanycast.task import Artifact, Message, Part, Task, TaskStatus

# ---------------------------------------------------------------------------
# Status mapping between internal enum values and A2A v1.0 state strings
# ---------------------------------------------------------------------------

_STATUS_TO_A2A_STATE: dict[TaskStatus, str] = {
    TaskStatus.SUBMITTED: "submitted",
    TaskStatus.WORKING: "working",
    TaskStatus.INPUT_REQUIRED: "input-required",
    TaskStatus.COMPLETED: "completed",
    TaskStatus.FAILED: "failed",
    TaskStatus.CANCELED: "canceled",
    TaskStatus.REJECTED: "rejected",
}

_A2A_STATE_TO_STATUS: dict[str, TaskStatus] = {v: k for k, v in _STATUS_TO_A2A_STATE.items()}
# A2A v1.0 defines auth-required; map it to input_required as closest match.
_A2A_STATE_TO_STATUS["auth-required"] = TaskStatus.INPUT_REQUIRED
# Also accept underscore variants for robustness.
_A2A_STATE_TO_STATUS["input_required"] = TaskStatus.INPUT_REQUIRED


# ---------------------------------------------------------------------------
# Part conversion
# ---------------------------------------------------------------------------


def _part_to_a2a_json(part: Part) -> dict[str, Any]:
    """Convert an internal Part to A2A v1.0 flat JSON."""
    d: dict[str, Any] = {}
    if part.text is not None:
        d["type"] = "text"
        d["text"] = part.text
    elif part.data is not None:
        d["type"] = "data"
        d["data"] = part.data
    elif part.url is not None:
        d["type"] = "file"
        d["file"] = {"url": part.url}
        if part.media_type:
            d["file"]["mimeType"] = part.media_type
    elif part.raw is not None:
        d["type"] = "data"
        d["data"] = {"raw": part.raw.hex()}
    if part.metadata:
        d["metadata"] = dict(part.metadata)  # copy to avoid mutating source
    # media_type at top level for non-file parts
    if part.media_type and part.url is None:
        meta = dict(d.get("metadata") or {})
        meta["media_type"] = part.media_type
        d["metadata"] = meta
    return d


def _part_from_a2a_json(data: dict[str, Any]) -> Part:
    """Parse an A2A v1.0 Part JSON into an internal Part."""
    part_type = data.get("type", "")
    metadata = data.get("metadata")

    # Extract media_type from metadata if present (copy to avoid mutating input).
    media_type: str | None = None
    if metadata and "media_type" in metadata:
        metadata = dict(metadata)
        media_type = metadata.pop("media_type")
        if not metadata:
            metadata = None

    if part_type == "text":
        return Part(text=data.get("text"), metadata=metadata, media_type=media_type)

    if part_type == "file":
        file_info = data.get("file", {})
        url = file_info.get("url")
        mt = file_info.get("mimeType") or media_type
        return Part(url=url, media_type=mt, metadata=metadata)

    if part_type == "data":
        raw_data = data.get("data")
        # Check if this is our encoded raw bytes
        if isinstance(raw_data, dict) and list(raw_data.keys()) == ["raw"]:
            raw_hex = raw_data["raw"]
            if isinstance(raw_hex, str):
                try:
                    return Part(raw=bytes.fromhex(raw_hex), metadata=metadata)
                except ValueError:
                    pass  # Not valid hex — treat as regular data below
        return Part(data=raw_data, media_type=media_type, metadata=metadata)

    # Fallback: try direct field mapping for lenient parsing
    if "text" in data:
        return Part(text=data["text"], metadata=metadata, media_type=media_type)
    if "data" in data:
        return Part(data=data["data"], metadata=metadata, media_type=media_type)
    if "file" in data:
        file_info = data["file"]
        return Part(
            url=file_info.get("url"),
            media_type=file_info.get("mimeType") or media_type,
            metadata=metadata,
        )

    return Part(metadata=metadata, media_type=media_type)


# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------


def message_to_a2a_json(msg: Message) -> dict[str, Any]:
    """Convert an internal Message to official A2A v1.0 JSON format.

    Maps our flat message structure to the A2A v1.0 Message which includes
    additional optional fields like ``context_id``, ``task_id``, and
    ``extensions``.
    """
    d: dict[str, Any] = {
        "role": msg.role,
        "parts": [_part_to_a2a_json(p) for p in msg.parts],
    }
    if msg.message_id:
        d["messageId"] = msg.message_id
    return d


def message_from_a2a_json(data: dict[str, Any]) -> Message:
    """Parse an official A2A v1.0 Message JSON into an internal Message.

    Ignores A2A v1.0 fields that have no internal equivalent (e.g.,
    ``context_id``, ``extensions``, ``reference_task_ids``).
    """
    parts = [_part_from_a2a_json(p) for p in data.get("parts", [])]
    return Message(
        role=data.get("role", "user"),
        parts=parts,
        message_id=data.get("messageId", data.get("message_id", "")),
    )


# ---------------------------------------------------------------------------
# Artifact conversion
# ---------------------------------------------------------------------------


def _artifact_to_a2a_json(artifact: Artifact) -> dict[str, Any]:
    """Convert an internal Artifact to A2A v1.0 JSON."""
    d: dict[str, Any] = {
        "artifactId": artifact.artifact_id,
        "parts": [_part_to_a2a_json(p) for p in artifact.parts],
    }
    if artifact.name:
        d["name"] = artifact.name
    return d


def _artifact_from_a2a_json(data: dict[str, Any]) -> Artifact:
    """Parse an A2A v1.0 Artifact JSON into an internal Artifact."""
    parts = [_part_from_a2a_json(p) for p in data.get("parts", [])]
    return Artifact(
        artifact_id=data.get("artifactId", data.get("artifact_id", "")),
        name=data.get("name", ""),
        parts=parts,
    )


# ---------------------------------------------------------------------------
# Task conversion
# ---------------------------------------------------------------------------


def _status_to_a2a_json(
    status: TaskStatus,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    """Convert internal TaskStatus enum to A2A v1.0 status object."""
    state = _STATUS_TO_A2A_STATE.get(status, "submitted")
    d: dict[str, Any] = {"state": state}
    if updated_at is not None:
        d["timestamp"] = updated_at.isoformat()
    return d


def _status_from_a2a_json(data: dict[str, Any]) -> tuple[TaskStatus, datetime | None]:
    """Parse an A2A v1.0 status object into internal TaskStatus + timestamp."""
    state = data.get("state", "submitted")
    status = _A2A_STATE_TO_STATUS.get(state, TaskStatus.SUBMITTED)

    timestamp: datetime | None = None
    ts_str = data.get("timestamp")
    if ts_str:
        try:
            timestamp = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            pass

    return status, timestamp


def task_to_a2a_json(task: Task) -> dict[str, Any]:
    """Convert an internal Task to official A2A v1.0 JSON format.

    Field mapping:

    * ``task_id`` -> ``id``
    * ``messages`` -> ``history``
    * ``status`` enum -> ``status`` object with ``state`` / ``timestamp``
    * ``target_skill_id``, ``originator_peer_id`` -> dropped (P2P-only)
    """
    d: dict[str, Any] = {
        "id": task.task_id,
        "status": _status_to_a2a_json(task.status, task.updated_at),
    }
    if task.context_id:
        d["contextId"] = task.context_id
    if task.messages:
        d["history"] = [message_to_a2a_json(m) for m in task.messages]
    if task.artifacts:
        d["artifacts"] = [_artifact_to_a2a_json(a) for a in task.artifacts]
    return d


def task_from_a2a_json(data: dict[str, Any]) -> Task:
    """Parse an official A2A v1.0 JSON into an internal Task.

    Reads ``id`` as ``task_id``, ``history`` as ``messages``, and the
    ``status`` object as a ``TaskStatus`` enum value.
    """
    status_data = data.get("status", {})
    if isinstance(status_data, dict):
        status, updated_at = _status_from_a2a_json(status_data)
    else:
        # Defensive: treat string as state name
        status = _A2A_STATE_TO_STATUS.get(str(status_data), TaskStatus.SUBMITTED)
        updated_at = None

    messages = [message_from_a2a_json(m) for m in data.get("history", [])]
    artifacts = [_artifact_from_a2a_json(a) for a in data.get("artifacts", [])]

    return Task(
        task_id=data.get("id", ""),
        context_id=data.get("contextId", data.get("context_id", "")),
        status=status,
        messages=messages,
        artifacts=artifacts,
        updated_at=updated_at,
    )


# ---------------------------------------------------------------------------
# Skill conversion
# ---------------------------------------------------------------------------


def skill_to_a2a_json(skill: Skill) -> dict[str, Any]:
    """Convert an internal Skill to A2A v1.0 AgentSkill JSON.

    A2A v1.0 ``AgentSkill`` uses ``name`` for the human-readable label
    (our ``description``) and adds ``tags``, ``examples``, ``inputModes``,
    and ``outputModes``.
    """
    d: dict[str, Any] = {
        "id": skill.id,
        "name": skill.description or skill.id,
        "description": skill.description,
    }
    if skill.input_schema:
        d["inputModes"] = [skill.input_schema]
    if skill.output_schema:
        d["outputModes"] = [skill.output_schema]
    return d


def skill_from_a2a_json(data: dict[str, Any]) -> Skill:
    """Parse an A2A v1.0 AgentSkill JSON into an internal Skill.

    Maps ``name`` to ``description`` (preferring ``description`` if both
    present), and ``inputModes`` / ``outputModes`` to schema fields.
    """
    description = data.get("description", data.get("name", ""))
    input_modes = data.get("inputModes", data.get("input_modes", []))
    output_modes = data.get("outputModes", data.get("output_modes", []))
    return Skill(
        id=data.get("id", ""),
        description=description,
        input_schema=input_modes[0] if input_modes else None,
        output_schema=output_modes[0] if output_modes else None,
    )


# ---------------------------------------------------------------------------
# AgentCard conversion
# ---------------------------------------------------------------------------


def card_to_a2a_json(card: AgentCard, url: str = "") -> dict[str, Any]:
    """Convert an internal AgentCard to official A2A v1.0 Agent Card JSON.

    The P2P extension (``peer_id``, ``relay_addresses``, ``did_key``) is
    intentionally stripped since standard A2A agents do not understand it.

    Args:
        card: Internal AgentCard.
        url: Optional base URL for this agent's A2A endpoint. If provided,
            it is included in ``supported_interfaces``.
    """
    d: dict[str, Any] = {
        "name": card.name,
        "description": card.description,
        "version": card.version,
        "skills": [skill_to_a2a_json(s) for s in card.skills],
    }
    if url:
        d["url"] = url
    return d


def card_from_a2a_json(data: dict[str, Any]) -> AgentCard:
    """Parse an official A2A v1.0 Agent Card JSON into an internal AgentCard.

    Ignores A2A v1.0 fields that have no internal equivalent (e.g.,
    ``provider``, ``capabilities``, ``security_schemes``, ``signatures``).
    """
    skills = [skill_from_a2a_json(s) for s in data.get("skills", [])]
    return AgentCard(
        name=data.get("name", ""),
        description=data.get("description", ""),
        version=data.get("version", "1.0.0"),
        skills=skills,
    )
