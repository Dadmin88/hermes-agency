"""API router for the Hermes Agency dashboard.

Exposes all ``/api/`` endpoints consumed by the React frontend.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .dashboard_models import (
    DashboardAgent,
    DashboardConfig,
    DashboardDepartment,
    DashboardDispatchRequest,
    DashboardDispatchResponse,
    DashboardDoctorSummary,
    DashboardEvent,
    DashboardHealth,
    DashboardSettings,
    DashboardSkill,
    DashboardTask,
    DashboardWarning,
)
from .dashboard_security import require_token

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _registry_agents() -> list[dict[str, Any]]:
    """Load the static 83-agent roster from registry_definition.json."""
    registry_path = Path(__file__).resolve().parent / "pool" / "registry_definition.json"
    if not registry_path.exists():
        return []
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        return data.get("agents") if isinstance(data, dict) else []
    except Exception:
        return []


def _agent_label(name: str) -> str:
    """Derive a human-friendly label from an agent name like 'agency-ai-engineer'."""
    prefix = "agency-"
    slug = name[len(prefix) :] if name.startswith(prefix) else name
    return slug.replace("-", " ").title()


def _department_from_category(category: str) -> str:
    """Normalise the registry 'category' field into a department slug."""
    return (category or "general").strip().lower()


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_api_router(settings: DashboardSettings) -> APIRouter:
    """Build and return the fully-configured API router."""

    router = APIRouter(prefix="/api")
    _server_start_time = settings.server_start_time or time.time()

    # -----------------------------------------------------------------------
    # GET /api/health
    # -----------------------------------------------------------------------

    @router.get("/health", response_model=DashboardHealth)
    async def get_health() -> DashboardHealth:
        from .config import current_profile_name
        from .node_manager import manager

        try:
            from hermes_constants import get_hermes_home

            profile_home = str(get_hermes_home())
        except Exception:
            profile_home = ""

        # Determine daemon running state.
        daemon_running = False
        try:
            compact = manager.compact_info()
            daemon_running = bool(compact.get("node_started"))
        except Exception:
            pass

        # Registry configured?
        registry_configured = False
        try:
            from .registry_client import _registry_addresses

            registry_configured = bool(_registry_addresses())
        except Exception:
            pass

        # Kanban available?
        kanban_available = False
        try:
            from .doctor import _kanban_available

            kanban_available = _kanban_available()
        except Exception:
            pass

        # Incoming queue count
        incoming_count = 0
        try:
            incoming_count = manager.state.incoming_task_count
        except Exception:
            pass

        # Active model set
        active_model_set = ""
        try:
            from .model_sets import active_model_set_name

            active_model_set = active_model_set_name()
        except Exception:
            pass

        # Build warnings from doctor checks that are not passing.
        warnings: list[DashboardWarning] = []
        try:
            from .doctor import run_doctor

            report = run_doctor()
            for check in report.checks:
                if check.status in ("warn", "fail"):
                    warnings.append(
                        DashboardWarning(
                            id=check.id,
                            label=check.label,
                            status=check.status,
                            message=check.message,
                            remediation=check.remediation,
                        )
                    )
        except Exception:
            pass

        return DashboardHealth(
            ok=daemon_running,
            profile_home=profile_home,
            active_profile=current_profile_name() or "",
            active_model_set=active_model_set,
            daemon_running=daemon_running,
            registry_configured=registry_configured,
            kanban_available=kanban_available,
            incoming_queue_count=incoming_count,
            warnings=warnings,
        )

    # -----------------------------------------------------------------------
    # GET /api/doctor
    # -----------------------------------------------------------------------

    @router.get("/doctor", response_model=DashboardDoctorSummary)
    async def get_doctor() -> DashboardDoctorSummary:
        from .doctor import run_doctor

        report = run_doctor()
        return DashboardDoctorSummary(
            summary=report.summary,
            checks=[c.as_dict() for c in report.checks],
            exit_code=report.exit_code,
        )

    # -----------------------------------------------------------------------
    # GET /api/roster — static agent roster grouped by department
    # -----------------------------------------------------------------------

    @router.get("/roster", response_model=list[DashboardDepartment])
    async def get_roster() -> list[DashboardDepartment]:
        agents_raw = _registry_agents()
        by_dept: dict[str, list[DashboardAgent]] = defaultdict(list)
        for entry in agents_raw:
            name = str(entry.get("name", ""))
            dept = _department_from_category(str(entry.get("category", "")))
            agent = DashboardAgent(
                name=name,
                label=_agent_label(name),
                department=dept,
                skills=list(entry.get("skills") or []),
                description=str(entry.get("description", "")),
            )
            by_dept[dept].append(agent)

        departments: list[DashboardDepartment] = []
        for dept_name in sorted(by_dept):
            agents = by_dept[dept_name]
            departments.append(
                DashboardDepartment(
                    name=dept_name,
                    agent_count=len(agents),
                    agents=agents,
                )
            )
        return departments

    # -----------------------------------------------------------------------
    # GET /api/agents — roster + live discovery status
    # -----------------------------------------------------------------------

    @router.get("/agents", response_model=list[DashboardAgent])
    async def get_agents() -> list[DashboardAgent]:
        agents_raw = _registry_agents()

        # Try to get live peer info for discoverability.
        live_peer_ids: set[str] = set()
        try:
            from .node_manager import manager

            if manager.state.started:
                peers = manager.list_peers_sync(timeout=5)
                for peer in peers:
                    pid = str(peer.get("peer_id") or peer.get("id") or "")
                    if pid:
                        live_peer_ids.add(pid)
        except Exception:
            pass

        result: list[DashboardAgent] = []
        for entry in agents_raw:
            name = str(entry.get("name", ""))
            dept = _department_from_category(str(entry.get("category", "")))
            # We don't have direct peer_id mapping for static roster agents,
            # but we can check if any live peer advertises matching skills.
            result.append(
                DashboardAgent(
                    name=name,
                    label=_agent_label(name),
                    department=dept,
                    skills=list(entry.get("skills") or []),
                    description=str(entry.get("description", "")),
                    discoverable=bool(live_peer_ids),  # broad signal
                )
            )
        return result

    # -----------------------------------------------------------------------
    # GET /api/skills — aggregated skill catalog
    # -----------------------------------------------------------------------

    @router.get("/skills", response_model=list[DashboardSkill])
    async def get_skills() -> list[DashboardSkill]:
        agents_raw = _registry_agents()
        skill_agents: dict[str, list[str]] = defaultdict(list)
        skill_descs: dict[str, str] = {}
        for entry in agents_raw:
            name = str(entry.get("name", ""))
            for skill in entry.get("skills") or []:
                skill_str = str(skill)
                skill_agents[skill_str].append(name)

        return sorted(
            [
                DashboardSkill(
                    name=skill_name,
                    description=skill_descs.get(skill_name, ""),
                    agent_count=len(agent_names),
                )
                for skill_name, agent_names in skill_agents.items()
            ],
            key=lambda s: (-s.agent_count, s.name),
        )

    # -----------------------------------------------------------------------
    # GET /api/tasks — unified task view
    # -----------------------------------------------------------------------

    @router.get("/tasks", response_model=list[DashboardTask])
    async def get_tasks() -> list[DashboardTask]:
        tasks: list[DashboardTask] = []

        # 1) Agency incoming records
        try:
            from .node_manager import manager

            records = manager.incoming_tasks_sync(limit=100, timeout=5)
            for rec in records:
                task_id = str(rec.get("task_id", ""))
                kanban_tid = rec.get("kanban_task_id")
                linked_status = "none"
                if kanban_tid:
                    linked_status = _check_kanban_link(str(kanban_tid))

                actions = _agency_actions(rec.get("status", ""))
                tasks.append(
                    DashboardTask(
                        id=task_id,
                        source="agency_incoming",
                        title=_title_from_message(rec.get("message_text", "")),
                        status=str(rec.get("status", "")),
                        created_at=rec.get("created_at"),
                        updated_at=rec.get("updated_at"),
                        message_text=str(rec.get("message_text", "")),
                        result_text=rec.get("result_text"),
                        error_text=rec.get("error"),
                        kanban_task_id=str(kanban_tid) if kanban_tid else None,
                        linked_kanban_status=linked_status,
                        available_actions=actions,
                    )
                )
        except Exception as exc:
            logger.debug("Could not load agency incoming records: %s", exc)

        # 2) Kanban tasks
        try:
            from .kanban_bridge import list_tasks as kanban_list_tasks

            kanban_result = kanban_list_tasks({"limit": 100})
            if kanban_result.get("available") and kanban_result.get("ok"):
                for ktask in kanban_result.get("tasks") or []:
                    ktask_id = str(ktask.get("id", ""))
                    actions = _kanban_actions(
                        ktask.get("status", ""), ktask.get("plugin_status", "")
                    )
                    tasks.append(
                        DashboardTask(
                            id=ktask_id,
                            source="kanban",
                            title=str(ktask.get("title", "")),
                            status=str(ktask.get("plugin_status") or ktask.get("status", "")),
                            created_at=ktask.get("created_at"),
                            updated_at=ktask.get("completed_at")
                            or ktask.get("started_at")
                            or ktask.get("created_at"),
                            message_text=str(ktask.get("body", "")[:500]),
                            result_text=ktask.get("result"),
                            kanban_task_id=ktask_id,
                            linked_kanban_status="present",
                            available_actions=actions,
                        )
                    )
        except Exception as exc:
            logger.debug("Could not load Kanban tasks: %s", exc)

        # Sort newest first
        tasks.sort(key=lambda t: t.updated_at or t.created_at or 0, reverse=True)
        return tasks

    # -----------------------------------------------------------------------
    # POST /api/agency-records/{record_id}/archive
    # -----------------------------------------------------------------------

    @router.post(
        "/agency-records/{record_id}/archive",
        dependencies=[Depends(require_token)],
    )
    async def archive_agency_record(record_id: str) -> dict[str, Any]:
        from .node_manager import manager

        record = manager._incoming_records.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Agency record not found: {record_id}")
        record.status = "archived"
        record.updated_at = time.time()
        manager._refresh_incoming_state()
        manager._persist_incoming_records()
        return {"ok": True, "record_id": record_id, "status": "archived"}

    # -----------------------------------------------------------------------
    # POST /api/kanban-tasks/{task_id}/archive, /complete, /retry
    # -----------------------------------------------------------------------

    @router.post(
        "/kanban-tasks/{task_id}/archive",
        dependencies=[Depends(require_token)],
    )
    async def archive_kanban_task(task_id: str) -> dict[str, Any]:
        from .kanban_bridge import update_task

        result = update_task(task_id, status="archived")
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Archive failed"))
        return result

    @router.post(
        "/kanban-tasks/{task_id}/complete",
        dependencies=[Depends(require_token)],
    )
    async def complete_kanban_task(task_id: str) -> dict[str, Any]:
        from .kanban_bridge import update_task

        result = update_task(task_id, status="done")
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Complete failed"))
        return result

    @router.post(
        "/kanban-tasks/{task_id}/retry",
        dependencies=[Depends(require_token)],
    )
    async def retry_kanban_task(task_id: str) -> dict[str, Any]:
        from .kanban_bridge import update_task

        result = update_task(task_id, status="running")
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Retry failed"))
        return result

    # -----------------------------------------------------------------------
    # POST /api/dispatch
    # -----------------------------------------------------------------------

    @router.post(
        "/dispatch",
        response_model=DashboardDispatchResponse,
        dependencies=[Depends(require_token)],
    )
    async def dispatch_task(req: DashboardDispatchRequest) -> DashboardDispatchResponse:
        from .node_manager import manager

        kanban_task_id: str | None = None

        # Optionally create a Kanban task first.
        if req.create_kanban_task:
            try:
                from .kanban_bridge import create_task as kanban_create

                kresult = kanban_create(
                    title=req.message[:80],
                    description=req.message,
                    assigned_to=req.target_agent,
                    skills=[req.skill] if req.skill else None,
                    priority=req.priority,
                )
                if kresult.get("ok"):
                    kanban_task_id = str(kresult.get("task_id"))
            except Exception as exc:
                logger.warning("Dashboard dispatch: Kanban task creation failed: %s", exc)

        # Determine target peer / skill.
        target = req.target_agent or req.skill or ""
        try:
            result = manager.send_task_sync(
                message=req.message,
                skill=req.skill,
                peer_id=req.target_agent
                if req.target_agent and len(req.target_agent) > 20
                else None,
                metadata={"source": "dashboard", "priority": str(req.priority)},
                timeout=30,
            )
            task_id = str(result.get("task_id") or "")
            return DashboardDispatchResponse(
                ok=True,
                task_id=task_id,
                kanban_task_id=kanban_task_id,
                target=target,
                result_text=str(result.get("result") or "")[:500] or None,
            )
        except Exception as exc:
            return DashboardDispatchResponse(
                ok=False,
                kanban_task_id=kanban_task_id,
                target=target,
                error_text=f"{type(exc).__name__}: {exc}",
            )

    # -----------------------------------------------------------------------
    # GET /api/events
    # -----------------------------------------------------------------------

    @router.get("/events", response_model=list[DashboardEvent])
    async def get_events() -> list[DashboardEvent]:
        events: list[DashboardEvent] = []

        # Announcements (agency lifecycle events)
        try:
            from .announcements import recent_announcements

            for ann in recent_announcements(limit=50):
                severity = "info"
                ann_kind = str(ann.get("kind", ""))
                if "error" in ann_kind or "fail" in ann_kind:
                    severity = "error"
                elif "complete" in ann_kind or "success" in ann_kind:
                    severity = "success"
                elif "warn" in ann_kind:
                    severity = "warning"

                events.append(
                    DashboardEvent(
                        id=str(ann.get("id") or ann.get("timestamp") or ""),
                        severity=severity,
                        source="agency",
                        message=str(ann.get("message") or ann.get("text") or ""),
                        timestamp=ann.get("timestamp"),
                        related_task_id=ann.get("task_id"),
                        related_agent=ann.get("agent") or ann.get("profile"),
                        metadata={
                            k: v
                            for k, v in ann.items()
                            if k not in ("message", "text", "timestamp")
                        },
                    )
                )
        except Exception as exc:
            logger.debug("Could not load announcements: %s", exc)

        # Incoming task lifecycle events
        try:
            from .node_manager import manager

            for rec_dict in manager.incoming_tasks_sync(limit=50, timeout=5):
                status = str(rec_dict.get("status", ""))
                severity = "info"
                if status == "completed":
                    severity = "success"
                elif status == "failed":
                    severity = "error"

                events.append(
                    DashboardEvent(
                        id=f"incoming-{rec_dict.get('task_id', '')}",
                        severity=severity,
                        source="agency_incoming",
                        message=f"Incoming task {status}: {str(rec_dict.get('message_text', ''))[:120]}",
                        timestamp=rec_dict.get("updated_at"),
                        related_task_id=str(rec_dict.get("task_id", "")),
                    )
                )
        except Exception:
            pass

        events.sort(key=lambda e: e.timestamp or 0, reverse=True)
        return events[:100]

    # -----------------------------------------------------------------------
    # GET /api/config
    # -----------------------------------------------------------------------

    @router.get("/config", response_model=DashboardConfig)
    async def get_config() -> DashboardConfig:
        from .config import get_config as load_cfg
        from .model_sets import active_model_set_name, discover_model_set_files

        cfg = load_cfg()
        profile_home = ""
        try:
            from hermes_constants import get_hermes_home

            profile_home = str(get_hermes_home())
        except Exception:
            pass

        available_sets = sorted(discover_model_set_files().keys())
        daemon_status = "stopped"
        try:
            from .node_manager import manager

            if manager.state.started:
                daemon_status = "running"
            elif manager.state.error:
                daemon_status = "error"
        except Exception:
            pass

        return DashboardConfig(
            active_model_set=active_model_set_name(),
            available_model_sets=available_sets,
            profile_home=profile_home,
            daemon_status=daemon_status,
            security=cfg.relay_security.as_dict(),
        )

    # -----------------------------------------------------------------------
    # GET /api/model-sets
    # -----------------------------------------------------------------------

    @router.get("/model-sets")
    async def list_model_sets() -> dict[str, Any]:
        from .model_sets import discover_model_set_files, load_model_set, model_set_summary

        files = discover_model_set_files()
        sets: list[dict[str, Any]] = []
        for name in sorted(files):
            try:
                ms = load_model_set(name)
                sets.append(model_set_summary(ms))
            except Exception as exc:
                sets.append({"name": name, "error": str(exc)})
        return {"model_sets": sets, "count": len(sets)}

    # -----------------------------------------------------------------------
    # POST /api/model-sets/active
    # -----------------------------------------------------------------------

    @router.post(
        "/model-sets/active",
        dependencies=[Depends(require_token)],
    )
    async def set_active_model_set(body: dict[str, Any]) -> dict[str, Any]:
        import os

        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="'name' is required")

        from .model_sets import discover_model_set_files

        available = discover_model_set_files()
        if name not in available:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown model set '{name}'. Available: {', '.join(sorted(available))}",
            )

        # Set via environment variable (runtime override).
        os.environ["HERMES_AGENCY_MODEL_SET"] = name
        return {"ok": True, "active_model_set": name}

    # -----------------------------------------------------------------------
    # GET /api/settings
    # -----------------------------------------------------------------------

    @router.get("/settings", response_model=DashboardSettings)
    async def get_settings() -> DashboardSettings:
        return settings

    return router


# ---------------------------------------------------------------------------
# Task normalisation helpers
# ---------------------------------------------------------------------------


def _title_from_message(message_text: str) -> str:
    """Derive a short title from the first line of a message."""
    first_line = (message_text or "").strip().split("\n", 1)[0].strip()
    if len(first_line) > 80:
        return first_line[:79] + "…"
    return first_line or "(no message)"


def _check_kanban_link(kanban_task_id: str) -> str:
    """Check whether a kanban_task_id from an agency record points to a real Kanban task."""
    if not kanban_task_id:
        return "none"
    try:
        from .kanban_bridge import get_task

        result = get_task(kanban_task_id)
        if result.get("available") and result.get("ok"):
            return "present"
        return "missing"
    except Exception:
        return "unknown"


def _agency_actions(status: str) -> list[str]:
    """Return available dashboard actions for an agency incoming record."""
    s = (status or "").lower()
    if s in ("received", "queued", "processing"):
        return ["archive"]
    if s in ("completed", "failed"):
        return ["archive"]
    if s == "archived":
        return []
    return ["archive"]


def _kanban_actions(status: str, plugin_status: str) -> list[str]:
    """Return available dashboard actions for a Kanban task."""
    s = (status or "").lower()
    actions: list[str] = []
    if s not in ("done", "archived"):
        actions.append("complete")
    if s in ("blocked", "done"):
        actions.append("retry")
    if s != "archived":
        actions.append("archive")
    return actions
