"""Framework support for agent-initiated proactive tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .announcements import announce_proactive
from .config import current_profile_name, ensure_workspace, get_config
from .departments import get_department, get_department_board_slug
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
    if not proactive_enabled():
        return {"ok": False, "disabled": True, "warning": "agency.proactive.enabled is disabled"}
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
    department = get_department(assigned_to)
    board_slug = get_department_board_slug(assigned_to)
    if department:
        meta.setdefault("department", department)
    if board_slug:
        meta.setdefault("agency_board", board_slug)
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


def proactive_enabled() -> bool:
    """Return whether proactive triggers are enabled by either legacy or new config."""

    cfg = get_config()
    return bool(cfg.team.proactive or cfg.proactive.get("enabled"))


def reviewer_for_path(path: str | Path) -> str:
    """Pick the default reviewer profile for a deliverable path."""

    suffix = Path(path).suffix.lower()
    if suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb"}:
        return "agency-code-reviewer"
    if suffix in {".html", ".css", ".svg", ".png", ".jpg", ".jpeg", ".webp"}:
        return "agency-design-reviewer"
    if suffix in {".md", ".mdx", ".rst", ".txt"}:
        return "agency-editor-in-chief"
    return "agency-qa-tester"


def route_file_created(path: str | Path, *, board_id: str | None = None) -> dict[str, Any]:
    """Create a review task for a newly-created deliverable file."""

    if not proactive_enabled():
        return {"ok": False, "disabled": True, "warning": "agency.proactive.enabled is disabled"}
    file_path = Path(path).expanduser()
    workspace = ensure_workspace()
    reviewer = reviewer_for_path(file_path)
    board = (
        board_id or file_path.parent.name
        if file_path.parent != workspace.deliverables
        else "unboarded"
    )
    return create_proactive_task(
        title=f"Review deliverable {file_path.name}",
        description=(
            f"A new deliverable was saved at {file_path}. Review it for correctness, "
            "quality, and fit for the assigned domain."
        ),
        priority=1,
        skills=["review"],
        assigned_to=reviewer,
        metadata={
            "trigger": "file-watch",
            "path": str(file_path),
            "board_id": board,
            "reviewer": reviewer,
        },
    )


def route_review_needed_task(
    kanban_task_id: str, title: str, *, path: str | None = None
) -> dict[str, Any]:
    """Create a reviewer task for a Kanban card tagged review-needed."""

    if not proactive_enabled():
        return {"ok": False, "disabled": True, "warning": "agency.proactive.enabled is disabled"}
    reviewer = reviewer_for_path(path or title)
    return create_proactive_task(
        title=f"Review-needed: {title}",
        description=f"Kanban task {kanban_task_id} is tagged review-needed. Review and comment with findings.",
        priority=1,
        skills=["review"],
        assigned_to=reviewer,
        metadata={
            "trigger": "kanban-tag",
            "source_task_id": kanban_task_id,
            "path": path or "",
            "reviewer": reviewer,
        },
    )


def route_blocker(
    blocked_task_id: str, reason: str, *, preferred_alternative: str | None = None
) -> dict[str, Any]:
    """Create an escalation/fallback task for a reported blocker."""

    if not proactive_enabled():
        return {"ok": False, "disabled": True, "warning": "agency.proactive.enabled is disabled"}
    assignee = preferred_alternative or "agency-orchestrator"
    return create_proactive_task(
        title=f"Resolve blocker on {blocked_task_id}",
        description=f"Task {blocked_task_id} reported blocked: {reason}",
        priority=2,
        skills=["escalation", "routing"],
        assigned_to=assignee,
        metadata={
            "trigger": "blocker",
            "blocked_task_id": blocked_task_id,
            "reason": reason,
            "assignee": assignee,
        },
    )
