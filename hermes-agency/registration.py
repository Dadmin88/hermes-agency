"""Agent self-registration for Hermes Agency autonomous operations.

Registrations are live, process-local plugin state. They are intentionally not
written to SOUL.md or Kanban. Agents broadcast compact control messages over the
same A2A network used for task delegation so any peer/orchestrator can maintain
a live registry.
"""

from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any

from .config import current_profile_name, get_config

CONTROL_PREFIX = "AGENTANYCAST_CONTROL "
REGISTRATION_TTL_SECONDS = 15 * 60


@dataclass
class RegistrationRecord:
    """Live registry entry for one Hermes Agency peer."""

    peer_id: str
    name: str = ""
    description: str = ""
    skills: list[dict[str, str]] = field(default_factory=list)
    capacity: int | None = None
    current_load: int = 0
    tenant: str = "default"
    status: str = "registered"
    updated_at: float = field(default_factory=time.time)
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "name": self.name,
            "description": self.description,
            "skills": list(self.skills),
            "capacity": self.capacity,
            "current_load": self.current_load,
            "tenant": self.tenant,
            "status": self.status,
            "updated_at": self.updated_at,
            "raw": dict(self.raw),
        }

    @property
    def alive(self) -> bool:
        return self.status != "deregistered"


@dataclass
class RegistrationState:
    registrations: dict[str, RegistrationRecord] = field(default_factory=dict)
    local_peer_id: str | None = None
    last_broadcast_at: float | None = None
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "local_peer_id": self.local_peer_id,
            "last_broadcast_at": self.last_broadcast_at,
            "last_error": self.last_error,
            "registrations": {
                peer_id: record.as_dict() for peer_id, record in sorted(self.registrations.items())
            },
        }


_state = RegistrationState()


def get_registration_state() -> RegistrationState:
    """Return process-local registration state."""

    return _state


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def serialize_control_message(payload: dict[str, Any]) -> str:
    """Serialize a plugin control message for transport as an A2A text part."""

    clean = {str(key): value for key, value in payload.items() if value is not None}
    return CONTROL_PREFIX + json.dumps(clean, ensure_ascii=False, sort_keys=True)


def parse_control_message(text: str) -> dict[str, Any] | None:
    """Parse an Hermes Agency plugin control message if one is present."""

    raw = str(text or "").strip()
    if not raw.startswith(CONTROL_PREFIX):
        return None
    try:
        data = json.loads(raw[len(CONTROL_PREFIX) :].strip())
    except Exception:
        return None
    if isinstance(data, dict) and data.get("protocol") == "agency.autonomous.v1":
        return data
    return None


def _skill_id(skill: Any) -> str:
    if isinstance(skill, dict):
        return str(skill.get("id") or skill.get("skill_id") or skill.get("name") or "").strip()
    return str(
        getattr(skill, "id", "") or getattr(skill, "skill_id", "") or getattr(skill, "name", "")
    ).strip()


def _skill_description(skill: Any) -> str:
    if isinstance(skill, dict):
        return str(skill.get("description") or "").strip()
    return str(getattr(skill, "description", "") or "").strip()


def _card_summary(card: Any) -> dict[str, Any]:
    skills: list[dict[str, str]] = []
    for item in getattr(card, "skills", []) or []:
        skill_id = _skill_id(item)
        if skill_id:
            skills.append({"id": skill_id, "description": _skill_description(item)})
    metadata = getattr(card, "metadata", None)
    tenant = "default"
    if isinstance(metadata, dict):
        tenant = (
            (
                metadata.get("agency", {}).get("team", {}).get("tenant")
                if isinstance(metadata.get("agency"), dict)
                else None
            )
            or metadata.get("tenant")
            or tenant
        )
    try:
        tenant = get_config().team.tenant or str(tenant or "default")
    except Exception:
        tenant = str(tenant or "default")
    return {
        "name": str(getattr(card, "name", "") or current_profile_name()),
        "description": str(getattr(card, "description", "") or ""),
        "skills": skills,
        "tenant": tenant,
    }


def _registration_payload(
    node: Any,
    card: Any,
    *,
    event: str,
    capacity: int | None = None,
    current_load: int = 0,
) -> dict[str, Any]:
    card_data = _card_summary(card)
    peer_id = str(getattr(node, "peer_id", "") or "")
    return {
        "protocol": "agency.autonomous.v1",
        "type": "registration",
        "event": event,
        "peer_id": peer_id,
        "agent": {
            "name": card_data["name"],
            "description": card_data["description"],
            "skills": card_data["skills"],
            "capacity": capacity,
            "current_load": max(0, int(current_load or 0)),
            "tenant": card_data["tenant"],
        },
        "timestamp": time.time(),
    }


def _record_registration_payload(payload: dict[str, Any]) -> RegistrationRecord | None:
    peer_id = str(payload.get("peer_id") or "").strip()
    if not peer_id:
        return None
    agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
    event = str(payload.get("event") or "registered")
    status = "deregistered" if event == "deregistered" else "registered"
    raw_skills = agent.get("skills") if isinstance(agent, dict) else []
    skills: list[dict[str, str]] = []
    if isinstance(raw_skills, list):
        for item in raw_skills:
            skill_id = _skill_id(item)
            if skill_id:
                skills.append({"id": skill_id, "description": _skill_description(item)})
    capacity_raw = agent.get("capacity") if isinstance(agent, dict) else None
    try:
        capacity = int(capacity_raw) if capacity_raw not in (None, "") else None
    except (TypeError, ValueError):
        capacity = None
    try:
        current_load = int(agent.get("current_load") or 0) if isinstance(agent, dict) else 0
    except (TypeError, ValueError):
        current_load = 0
    record = RegistrationRecord(
        peer_id=peer_id,
        name=str(agent.get("name") or "") if isinstance(agent, dict) else "",
        description=str(agent.get("description") or "") if isinstance(agent, dict) else "",
        skills=skills,
        capacity=capacity,
        current_load=max(0, current_load),
        tenant=str(agent.get("tenant") or "default") if isinstance(agent, dict) else "default",
        status=status,
        updated_at=float(payload.get("timestamp") or time.time()),
        raw=payload,
    )
    _state.registrations[peer_id] = record
    return record


def _extract_relay_peer_id() -> str:
    """Extract the relay peer ID from config to skip it during broadcast."""
    try:
        from .config import get_config

        cfg = get_config()
        relay = cfg.relay or ""
        # relay format: /ip4/<addr>/tcp/<port>/p2p/<peer_id>
        parts = relay.split("/p2p/")
        if len(parts) == 2:
            return parts[-1].strip()
    except Exception:
        pass
    return ""


async def _broadcast(node: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Broadcast a control payload to all connected peers using list_peers + send_task."""

    sent: list[str] = []
    errors: list[str] = []
    peer_id = str(getattr(node, "peer_id", "") or "")
    message_text = serialize_control_message(payload)

    # Extract relay peer ID to skip it — relay doesn't support A2A protocol
    relay_peer_id = _extract_relay_peer_id()

    try:
        peers = await _maybe_await(node.list_peers())
    except Exception as exc:
        peers = []
        errors.append(f"list_peers: {type(exc).__name__}: {exc}")
    for peer in peers or []:
        target = ""
        if isinstance(peer, dict):
            target = str(peer.get("peer_id") or peer.get("id") or "").strip()
        else:
            target = str(getattr(peer, "peer_id", "") or getattr(peer, "id", "")).strip()
        if not target or target == peer_id:
            continue
        if relay_peer_id and target == relay_peer_id:
            continue  # skip relay — it doesn't support A2A
        try:
            await _maybe_await(
                node.send_task(
                    message={"role": "user", "parts": [{"text": message_text}]},
                    peer_id=target,
                    metadata={
                        "agency_control": "registration",
                        "type": str(payload.get("event") or "registration"),
                    },
                )
            )
            sent.append(target)
        except Exception as exc:  # fail-open: one bad peer should not block startup/shutdown
            errors.append(f"send({target}): {type(exc).__name__}: {exc}")
    _state.last_broadcast_at = time.time()
    _state.last_error = "; ".join(errors) if errors else None
    return {"ok": not errors, "sent": sent, "errors": errors, "payload": payload}


async def register_agent(
    node: Any,
    card: Any,
    *,
    capacity: int | None = None,
    current_load: int = 0,
) -> dict[str, Any]:
    """Announce this agent's capabilities to the A2A network on startup."""

    payload = _registration_payload(
        node,
        card,
        event="registered",
        capacity=capacity,
        current_load=current_load,
    )
    _state.local_peer_id = payload.get("peer_id") or None
    _record_registration_payload(payload)
    return await _broadcast(node, payload)


async def update_registration(
    node: Any,
    card: Any,
    *,
    capacity: int | None = None,
    current_load: int = 0,
) -> dict[str, Any]:
    """Announce capability/load changes for this agent."""

    payload = _registration_payload(
        node,
        card,
        event="updated",
        capacity=capacity,
        current_load=current_load,
    )
    _state.local_peer_id = payload.get("peer_id") or None
    _record_registration_payload(payload)
    return await _broadcast(node, payload)


async def deregister_agent(node: Any, *, card: Any | None = None) -> dict[str, Any]:
    """Announce shutdown to connected peers."""

    if card is None:
        agent = {
            "name": current_profile_name(),
            "description": "Hermes Hermes Agency node shutting down.",
            "skills": [],
            "capacity": None,
            "current_load": 0,
            "tenant": get_config().team.tenant,
        }
        payload = {
            "protocol": "agency.autonomous.v1",
            "type": "registration",
            "event": "deregistered",
            "peer_id": str(getattr(node, "peer_id", "") or _state.local_peer_id or ""),
            "agent": agent,
            "timestamp": time.time(),
        }
    else:
        payload = _registration_payload(node, card, event="deregistered", current_load=0)
    _record_registration_payload(payload)
    return await _broadcast(node, payload)


def handle_registration_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Process an incoming registration/deregistration control message."""

    if payload.get("type") != "registration":
        return None
    record = _record_registration_payload(payload)
    if record is None:
        return {"ok": False, "error": "registration missing peer_id"}
    return {"ok": True, "registration": record.as_dict()}


def live_registrations(
    *, tenant: str | None = None, include_stale: bool = False
) -> list[dict[str, Any]]:
    """Return live registrations, filtered by tenant unless explicitly overridden."""

    now = time.time()
    requested_tenant = tenant if tenant is not None else get_config().team.tenant
    records: list[dict[str, Any]] = []
    for record in _state.registrations.values():
        if not include_stale and now - record.updated_at > REGISTRATION_TTL_SECONDS:
            continue
        if not record.alive and not include_stale:
            continue
        if requested_tenant not in (None, "", "*") and record.tenant != requested_tenant:
            continue
        records.append(record.as_dict())
    return sorted(records, key=lambda item: (item.get("name") or item.get("peer_id") or "").lower())
