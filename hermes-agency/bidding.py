"""Task bidding protocol for Hermes Agency autonomous operations."""

from __future__ import annotations

import inspect
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .config import get_config
from .registration import serialize_control_message


@dataclass
class BidRecord:
    """Structured bid for a Kanban/orchestrator task."""

    task_id: str
    agent: str
    capability_match: float
    estimated_time: int | None = None
    status: str = "available"
    reason: str = ""
    tenant: str = "default"
    created_at: float = field(default_factory=time.time)
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": "bid",
            "task_id": self.task_id,
            "agent": self.agent,
            "capability_match": max(0.0, min(1.0, float(self.capability_match))),
            "estimated_time": self.estimated_time,
            "status": self.status,
            "reason": self.reason,
            "tenant": self.tenant,
            "created_at": self.created_at,
            "raw": dict(self.raw),
        }


@dataclass
class BiddingState:
    bids: dict[str, list[BidRecord]] = field(default_factory=dict)
    requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests": dict(self.requests),
            "last_error": self.last_error,
            "bids": {
                task_id: [bid.as_dict() for bid in bids]
                for task_id, bids in sorted(self.bids.items())
            },
        }


_state = BiddingState()


def get_bidding_state() -> BiddingState:
    return _state


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_.-]+", text.lower()) if len(token) > 2}


def _skill_id(skill: Any) -> str:
    if isinstance(skill, dict):
        return str(skill.get("id") or skill.get("skill_id") or skill.get("name") or "").strip()
    return str(getattr(skill, "id", "") or getattr(skill, "skill_id", "") or getattr(skill, "name", "")).strip()


def calculate_capability_match(task: dict[str, Any], skills: list[Any]) -> float:
    """Compute a conservative 0..1 skill/text match score."""

    requested = {str(skill).lower() for skill in (task.get("skills") or []) if str(skill).strip()}
    available = {_skill_id(skill).lower() for skill in skills if _skill_id(skill)}
    if requested:
        overlap = requested & available
        return len(overlap) / max(1, len(requested))
    text = " ".join(str(task.get(key) or "") for key in ("title", "description", "body", "task"))
    task_tokens = _tokens(text)
    if not task_tokens or not available:
        return 0.5 if available else 0.0
    skill_tokens: set[str] = set()
    for skill in skills:
        skill_tokens |= _tokens(_skill_id(skill))
        if isinstance(skill, dict):
            skill_tokens |= _tokens(str(skill.get("description") or ""))
        else:
            skill_tokens |= _tokens(str(getattr(skill, "description", "") or ""))
    if not skill_tokens:
        return 0.0
    return min(1.0, len(task_tokens & skill_tokens) / max(1, min(len(task_tokens), 8)))


def build_bid_request(
    task_id: str,
    *,
    title: str,
    description: str = "",
    skills: list[str] | None = None,
    tenant: str | None = None,
) -> dict[str, Any]:
    """Build a structured A2A bid request."""

    return {
        "protocol": "agency.autonomous.v1",
        "type": "bid_request",
        "task_id": str(task_id),
        "task": {
            "title": str(title or ""),
            "description": str(description or ""),
            "skills": list(skills or []),
            "tenant": tenant or get_config().team.tenant,
        },
        "timestamp": time.time(),
    }


def evaluate_local_bid(
    task: dict[str, Any],
    *,
    agent: str,
    skills: list[Any],
    current_load: int = 0,
    capacity: int | None = None,
    estimated_time: int | None = None,
) -> BidRecord:
    """Return this agent's local bid for a task."""

    match = calculate_capability_match(task, skills)
    if capacity is not None and current_load >= capacity:
        status = "busy"
        reason = "capacity reached"
    elif match <= 0.0:
        status = "busy"
        reason = "no matching capability"
    else:
        status = "available"
        reason = "capability match"
    return BidRecord(
        task_id=str(task.get("task_id") or task.get("id") or ""),
        agent=agent,
        capability_match=match,
        estimated_time=estimated_time,
        status=status,
        reason=reason,
        tenant=str(task.get("tenant") or get_config().team.tenant),
    )


def record_bid(payload: dict[str, Any]) -> BidRecord | None:
    """Record an incoming structured bid message."""

    if payload.get("type") != "bid":
        return None
    task_id = str(payload.get("task_id") or "").strip()
    agent = str(payload.get("agent") or "").strip()
    if not task_id or not agent:
        return None
    try:
        match = float(payload.get("capability_match") or 0.0)
    except (TypeError, ValueError):
        match = 0.0
    estimated_raw = payload.get("estimated_time")
    try:
        estimated = int(estimated_raw) if estimated_raw not in (None, "") else None
    except (TypeError, ValueError):
        estimated = None
    bid = BidRecord(
        task_id=task_id,
        agent=agent,
        capability_match=max(0.0, min(1.0, match)),
        estimated_time=estimated,
        status=str(payload.get("status") or "available"),
        reason=str(payload.get("reason") or ""),
        tenant=str(payload.get("tenant") or get_config().team.tenant),
        created_at=float(payload.get("timestamp") or time.time()),
        raw=payload,
    )
    existing = [item for item in _state.bids.get(task_id, []) if item.agent != agent]
    existing.append(bid)
    _state.bids[task_id] = existing
    return bid


def handle_bid_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Process incoming bid protocol messages."""

    msg_type = payload.get("type")
    if msg_type == "bid_request":
        task_id = str(payload.get("task_id") or "").strip()
        if task_id:
            _state.requests[task_id] = payload
            return {"ok": True, "bid_request": payload}
        return {"ok": False, "error": "bid_request missing task_id"}
    if msg_type == "bid":
        bid = record_bid(payload)
        return {"ok": bool(bid), "bid": bid.as_dict() if bid else None}
    return None


def choose_best_bid(task_id: str, *, past_performance: dict[str, float] | None = None) -> dict[str, Any] | None:
    """Choose the best bid by availability, capability, performance, and time."""

    bids = list(_state.bids.get(str(task_id), []))
    if not bids:
        return None
    performance = past_performance or {}

    def score(bid: BidRecord) -> tuple[float, float, float, float]:
        available = 1.0 if bid.status == "available" else 0.25 if bid.status.startswith("delegating_to:") else 0.0
        capability = max(0.0, min(1.0, bid.capability_match))
        perf = max(0.0, min(1.0, float(performance.get(bid.agent, 0.5))))
        time_score = 0.5
        if bid.estimated_time is not None:
            time_score = max(0.0, min(1.0, 1.0 - (bid.estimated_time / 480.0)))
        return (available, capability, perf, time_score)

    winner = sorted(bids, key=score, reverse=True)[0]
    return winner.as_dict()


async def broadcast_bid_request(node: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Broadcast a bid request to connected peers."""

    if not get_config().team.bidding:
        return {"ok": False, "disabled": True, "warning": "agency.team.bidding is disabled"}
    sent: list[str] = []
    errors: list[str] = []
    message_text = serialize_control_message(request)
    try:
        peers = await _maybe_await(node.list_peers())
    except Exception as exc:
        peers = []
        errors.append(f"list_peers: {type(exc).__name__}: {exc}")
    for peer in peers or []:
        peer_id = str(peer.get("peer_id") or peer.get("id") or "").strip() if isinstance(peer, dict) else str(getattr(peer, "peer_id", "") or getattr(peer, "id", "")).strip()
        if not peer_id or peer_id == str(getattr(node, "peer_id", "") or ""):
            continue
        try:
            await _maybe_await(
                node.send_task(
                    message={"role": "user", "parts": [{"text": message_text}]},
                    peer_id=peer_id,
                    metadata={"agency_control": "bid_request", "task_id": str(request.get("task_id") or "")},
                )
            )
            sent.append(peer_id)
        except Exception as exc:
            errors.append(f"send({peer_id}): {type(exc).__name__}: {exc}")
    _state.last_error = "; ".join(errors) if errors else None
    return {"ok": not errors, "sent": sent, "errors": errors, "request": request}


def bid_to_payload(bid: BidRecord) -> dict[str, Any]:
    payload = bid.as_dict()
    payload.update({"protocol": "agency.autonomous.v1", "timestamp": bid.created_at})
    payload.pop("raw", None)
    return payload


def bidding_summary(task_id: str | None = None) -> dict[str, Any]:
    if task_id:
        return {"task_id": task_id, "bids": [bid.as_dict() for bid in _state.bids.get(task_id, [])], "winner": choose_best_bid(task_id)}
    return _state.as_dict()
