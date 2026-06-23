"""Framework support for agent-initiated proactive tasks."""

from __future__ import annotations

from typing import Any

from .announcements import announce_proactive
from .config import current_profile_name, get_config
from .kanban_bridge import create_task as kanban_create_task


def create_proactive_task(
    title: str,
    description: str,
    priority: int = 0,
    skills: list[str] | tuple[str, ...] | None = None,
    *,
    assigned_to: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an agent-initiated Kanban task when proactive behavior is enabled."""

    cfg = get_config()
    if not cfg.team.proactive:
        return {"ok": False, "disabled": True, "warning": "agency.team.proactive is disabled"}
    clean_title = " ".join(str(title or "").split()).strip()
    clean_description = str(description or "").strip()
    if not clean_title:
        return {"ok": False, "error": "title is required"}
    meta = {
        "agency_kind": "proactive",
        "created_by_agent": current_profile_name(),
        "tenant": cfg.team.tenant,
        **(metadata or {}),
    }
    task = kanban_create_task(
        title=clean_title,
        description=clean_description,
        assigned_to=assigned_to,
        skills=list(skills or []),
        dependencies=[],
        metadata=meta,
        priority=int(priority or 0),
    )
    announcement = announce_proactive(
        clean_title, clean_description, kanban_task_id=str(task.get("task_id") or "") or None
    )
    return {"ok": bool(task.get("ok")), "task": task, "announcement": announcement}
