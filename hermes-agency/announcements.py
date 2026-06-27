"""Platform-agnostic announcement helpers for Hermes Agency collaboration.

These helpers intentionally return plain text. The Hermes gateway/platform
adapter is responsible for delivering/formatting the agent's final response.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from .config import get_config


@dataclass
class AnnouncementRecord:
    kind: str
    text: str
    created_at: float
    metadata: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data = {"kind": self.kind, "text": self.text, "created_at": self.created_at}
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


_RECENT: deque[AnnouncementRecord] = deque(maxlen=50)


def _clean(value: Any, *, max_len: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def _record(kind: str, text: str | None, metadata: dict[str, Any] | None = None) -> str | None:
    if not text:
        return None
    _RECENT.append(
        AnnouncementRecord(kind=kind, text=text, created_at=time.time(), metadata=metadata)
    )
    return text


def recent_announcements(limit: int = 10) -> list[dict[str, Any]]:
    """Return recent announcement records for status/debug output."""

    return [item.as_dict() for item in list(_RECENT)[-max(1, limit) :]]


def announce_start(task: Any) -> str:
    """Announce that this agent is starting work."""

    return _record("start", f"Working on {_clean(task)}...") or ""


def announce_complete(task: Any, result: Any, *, kanban_task_id: str | None = None) -> str:
    """Announce task completion with a compact result summary."""

    summary = _clean(result, max_len=700)
    task_text = _clean(task, max_len=220)
    suffix = f" (Kanban: {kanban_task_id})" if kanban_task_id else ""
    if summary:
        text = f"Done with {task_text}{suffix}. {summary}"
    else:
        text = f"Done with {task_text}{suffix}."
    metadata = {"kanban_task_id": kanban_task_id} if kanban_task_id else None
    return _record("complete", text, metadata) or ""


def announce_error(task: Any, error: Any, *, kanban_task_id: str | None = None) -> str:
    """Announce task failure."""

    suffix = f" (Kanban: {kanban_task_id})" if kanban_task_id else ""
    metadata = {"kanban_task_id": kanban_task_id} if kanban_task_id else None
    return _record("error", f"Failed{suffix}: {_clean(error, max_len=700)}", metadata) or ""


def announce_delegate(task: Any, target: Any, *, kanban_task_id: str | None = None) -> str:
    """Announce direct A2A delegation."""

    suffix = f" (Kanban: {kanban_task_id})" if kanban_task_id else ""
    metadata = {"kanban_task_id": kanban_task_id} if kanban_task_id else None
    return (
        _record("delegate", f"Delegating to {_clean(target, max_len=220)}{suffix}...", metadata)
        or ""
    )


def announce_escalate(task: Any, reason: Any) -> str:
    """Announce that work needs operator attention."""

    task_text = _clean(task, max_len=320)
    reason_text = _clean(reason, max_len=700)
    return _record("escalate", f"Operator input needed for {task_text}: {reason_text}") or ""


def announce_registration(agent: Any, event: str, *, peer_id: str | None = None) -> str:
    """Announce agent registration/deregistration/update events."""

    suffix = f" ({peer_id})" if peer_id else ""
    return (
        _record(
            "registration",
            f"Agent registration {event}: {_clean(agent, max_len=220)}{suffix}",
            {"peer_id": peer_id, "event": event},
        )
        or ""
    )


def announce_bid(task_id: str, winner: Any, *, status: str = "selected") -> str:
    """Announce bidding outcome for a task."""

    return (
        _record(
            "bid",
            f"Bidding {status} for task {_clean(task_id, max_len=120)}: {_clean(winner, max_len=220)}",
            {"task_id": task_id, "status": status},
        )
        or ""
    )


def announce_proactive(
    title: Any, description: Any = "", *, kanban_task_id: str | None = None
) -> str:
    """Announce creation of a proactive agent-initiated task."""

    suffix = f" (Kanban: {kanban_task_id})" if kanban_task_id else ""
    body = _clean(description, max_len=320)
    text = f"Proactive task created{suffix}: {_clean(title, max_len=220)}" + (
        f" — {body}" if body else ""
    )
    return (
        _record("proactive", text, {"kanban_task_id": kanban_task_id} if kanban_task_id else None)
        or ""
    )


def announce_policy(action: Any, decision: Any, *, agent: str | None = None) -> str:
    """Announce an autonomy policy decision."""

    target = f" for {agent}" if agent else ""
    return (
        _record(
            "policy",
            f"Autonomy policy{target}: {_clean(action, max_len=120)} -> {_clean(decision, max_len=80)}",
        )
        or ""
    )


def announce_workflow(name: str, workflow_id: str, step_count: int) -> str:
    """Announce workflow creation."""

    return (
        _record(
            "workflow",
            f"Workflow started: {_clean(name, max_len=120)} ({workflow_id}) with {step_count} step task(s).",
            {"workflow_id": workflow_id},
        )
        or ""
    )


def announce_progress(task: Any, update: Any) -> str | None:
    """Announce optional progress when enabled by config."""

    if not get_config().team.announce_progress:
        return None
    return _record("progress", f"Progress: {_clean(update, max_len=700)}")


# ── Escalation hooks for future Kanban integration ──────────────────────────


def build_blocked_context(task: Any, why: Any, needed: Any = "") -> dict[str, str]:
    """Build the context payload a future Kanban bridge will attach to blocked tasks."""

    return {
        "task": _clean(task, max_len=700),
        "why_stuck": _clean(why, max_len=700),
        "needed_from_operator": _clean(needed, max_len=700),
    }


def mark_blocked_hook(
    task: Any, why: Any, needed: Any = "", *, task_id: str | None = None
) -> dict[str, Any]:
    """Mark a Kanban task blocked when available, otherwise return context."""

    context = build_blocked_context(task, why, needed)
    if task_id:
        try:
            from .kanban_bridge import update_task

            result = update_task(task_id, status="blocked", error=context["why_stuck"])
            return {
                "implemented": bool(result.get("available")),
                "kanban": result,
                "context": context,
            }
        except Exception as exc:  # pragma: no cover - defensive fail-open hook
            return {
                "implemented": False,
                "error": f"{type(exc).__name__}: {exc}",
                "context": context,
            }
    return {"implemented": False, "context": context}
