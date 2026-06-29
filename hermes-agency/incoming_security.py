"""Incoming Hermes Agency task security checks.

This module centralizes sender verification so control messages and normal task
messages pass the same trust gate before any state mutation occurs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .config import AgencyConfig
from .trust import TrustError, peer_allowed_by_config, store_for_config

TRUST_ORDER = {"blocked": 0, "limited": 1, "full": 2}


@dataclass(frozen=True)
class IncomingSecurityDecision:
    """Decision returned by incoming sender verification."""

    allowed: bool
    reason: str
    sender_peer_id: str
    trust_level: str
    action: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "sender_peer_id": self.sender_peer_id,
            "trust_level": self.trust_level,
            "action": self.action,
        }


def verify_incoming_sender(
    task: Any,
    cfg: AgencyConfig,
    *,
    purpose: str,
    control_payload: dict[str, Any] | None = None,
) -> IncomingSecurityDecision:
    """Verify an incoming task sender before processing or mutating state.

    Args:
        task: IncomingTask-like object from the SDK.
        cfg: Resolved Hermes Agency config.
        purpose: One of ``"control"`` or ``"task"``. Control messages require
            ``full`` trust because they mutate registry/bidding/workflow state.
        control_payload: Optional already-parsed control payload used to extract
            sender identity hints without reparsing the message.
    """

    normalized_purpose = str(purpose or "task").strip().lower()
    sender_peer_id = extract_sender_peer_id(task, control_payload)
    if not sender_peer_id:
        return IncomingSecurityDecision(
            False,
            "incoming sender peer_id is required",
            "",
            "",
            "missing_peer_id",
        )

    if _peer_blocked(cfg, sender_peer_id):
        return IncomingSecurityDecision(
            False,
            "peer is blocked",
            sender_peer_id,
            "blocked",
            "blocked",
        )

    if not _peer_allowed_by_effective_config(cfg, sender_peer_id):
        return IncomingSecurityDecision(
            False,
            f"sender peer {sender_peer_id} is not in effective agency.relay.allowlist",
            sender_peer_id,
            "",
            "not_in_allowlist",
        )

    name = _sender_name(task, control_payload)
    try:
        decision = store_for_config(cfg).verify_peer(
            sender_peer_id,
            name=name,
            trust_level="limited",
            source=f"incoming_{normalized_purpose}",
        )
    except Exception as exc:  # defensive: corrupt trust store should fail closed
        raise TrustError(str(exc)) from exc

    if not decision.allowed:
        return IncomingSecurityDecision(
            False,
            decision.reason or decision.action,
            sender_peer_id,
            decision.trust_level,
            decision.action,
        )

    min_trust = "full"
    if _trust_rank(decision.trust_level) < _trust_rank(min_trust):
        return IncomingSecurityDecision(
            False,
            f"incoming {normalized_purpose} requires {min_trust} trust; sender is {decision.trust_level}",
            sender_peer_id,
            decision.trust_level,
            "insufficient_trust",
        )

    return IncomingSecurityDecision(
        True,
        "allowed",
        sender_peer_id,
        decision.trust_level,
        decision.action,
    )


def extract_sender_peer_id(task: Any, control_payload: dict[str, Any] | None = None) -> str:
    """Extract a sender peer ID from task fields, metadata, or control payload."""

    for value in (
        getattr(task, "peer_id", ""),
        getattr(task, "originator_peer_id", ""),
        getattr(task, "sender_peer_id", ""),
    ):
        clean = str(value or "").strip()
        if clean:
            return clean

    metadata = _metadata_to_dict(getattr(task, "metadata", None))
    for key in ("sender_peer_id", "originator_peer_id", "peer_id"):
        clean = str(metadata.get(key) or "").strip()
        if clean:
            return clean

    if isinstance(control_payload, dict):
        clean = str(control_payload.get("peer_id") or "").strip()
        if clean:
            return clean
    return ""


def _peer_blocked(cfg: AgencyConfig, peer_id: str) -> bool:
    record = store_for_config(cfg).list_peers().get(str(peer_id or "").strip()) or {}
    return str(record.get("trust_level") or "").strip().lower() == "blocked"


def _peer_allowed_by_effective_config(cfg: AgencyConfig, peer_id: str) -> bool:
    clean = str(peer_id or "").strip()
    if not clean:
        return False
    records = store_for_config(cfg).list_peers()
    record = records.get(clean) or {}
    if str(record.get("trust_level") or "").strip().lower() == "blocked":
        return False
    if peer_allowed_by_config(cfg, clean):
        return True
    if not cfg.relay_security.auto_allow_team:
        return False
    try:
        from .team_context import get_team_state

        if clean not in get_team_state().peers:
            return False
    except Exception:
        return False
    trust_level = str(record.get("trust_level") or "").strip().lower()
    return trust_level in {"limited", "full"}


def _sender_name(task: Any, control_payload: dict[str, Any] | None = None) -> str:
    if isinstance(control_payload, dict):
        agent = control_payload.get("agent")
        if isinstance(agent, dict):
            name = str(agent.get("name") or "").strip()
            if name:
                return name
        name = str(control_payload.get("agent_name") or control_payload.get("name") or "").strip()
        if name:
            return name

    sender_card = getattr(task, "sender_card", None)
    for attr in ("name", "card_name"):
        value = str(getattr(sender_card, attr, "") or "").strip()
        if value:
            return value

    metadata = _metadata_to_dict(getattr(task, "metadata", None))
    for key in ("sender_name", "agent_name", "from_agent", "source_agent"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _metadata_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        try:
            data = value.to_dict()
            return {str(k): v for k, v in data.items()} if isinstance(data, dict) else {}
        except Exception:
            return {}
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return {str(k): v for k, v in data.items()} if isinstance(data, dict) else {}
    return {}


def _trust_rank(level: str | None) -> int:
    return TRUST_ORDER.get(str(level or "limited").strip().lower(), TRUST_ORDER["limited"])
