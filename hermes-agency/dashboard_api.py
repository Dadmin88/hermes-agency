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

from fastapi import APIRouter, Depends, HTTPException, Query

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


def _pool_roster_by_name() -> dict[str, dict[str, Any]]:
    """Return the persistent agency pool roster keyed by profile name."""
    try:
        from .pool.roster import build_roster

        roster = build_roster(include_plugin_setup=False)
        profiles = roster.get("profiles") or []
        return {
            str(profile.get("name") or ""): profile
            for profile in profiles
            if isinstance(profile, dict) and str(profile.get("name") or "")
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_api_router(settings: DashboardSettings) -> APIRouter:
    """Build and return the fully-configured API router."""

    router = APIRouter(prefix="/api")
    _server_start_time = settings.server_start_time or time.time()
    _tasks_cache: list[DashboardTask] | None = None
    _tasks_cache_at = 0.0
    _tasks_cache_ttl_seconds = 10.0

    def clear_tasks_cache() -> None:
        nonlocal _tasks_cache, _tasks_cache_at
        _tasks_cache = None
        _tasks_cache_at = 0.0

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
        pool_roster = _pool_roster_by_name()
        by_dept: dict[str, list[DashboardAgent]] = defaultdict(list)
        for entry in agents_raw:
            name = str(entry.get("name", ""))
            runtime = pool_roster.get(name, {})
            dept = _department_from_category(str(entry.get("category", "")))
            peer_id = str(runtime.get("peer_id") or entry.get("peer_id") or "") or None
            agent = DashboardAgent(
                name=name,
                label=_agent_label(name),
                department=dept,
                skills=list(entry.get("skills") or []),
                description=str(entry.get("description", "")),
                discoverable=True,
                online=bool(runtime.get("online")),
                peer_id=peer_id,
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
        pool_roster = _pool_roster_by_name()

        result: list[DashboardAgent] = []
        for entry in agents_raw:
            name = str(entry.get("name", ""))
            runtime = pool_roster.get(name, {})
            dept = _department_from_category(str(entry.get("category", "")))
            peer_id = str(runtime.get("peer_id") or entry.get("peer_id") or "") or None
            result.append(
                DashboardAgent(
                    name=name,
                    label=_agent_label(name),
                    department=dept,
                    skills=list(entry.get("skills") or []),
                    description=str(entry.get("description", "")),
                    discoverable=True,
                    online=bool(runtime.get("online")),
                    peer_id=peer_id,
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
    async def get_tasks(status: str | None = None) -> list[DashboardTask]:
        nonlocal _tasks_cache, _tasks_cache_at

        now = time.time()
        if _tasks_cache is not None and now - _tasks_cache_at <= _tasks_cache_ttl_seconds:
            tasks = list(_tasks_cache)
            if status:
                normalized = status.strip().lower()
                active_statuses = {"active", "running", "working", "queued", "processing", "received"}
                if normalized == "active":
                    return [t for t in tasks if (t.status or "").lower() in active_statuses]
                return [t for t in tasks if (t.status or "").lower() == normalized]
            return tasks

        tasks: list[DashboardTask] = []
        kanban_tasks: list[dict[str, Any]] = []
        kanban_task_ids: set[str] = set()

        # Load Kanban once. The incoming records use this set to resolve links without
        # issuing one get_task call per incoming task.
        try:
            from .kanban_bridge import list_tasks as kanban_list_tasks

            kanban_result = kanban_list_tasks({"limit": 100})
            if kanban_result.get("available") and kanban_result.get("ok"):
                kanban_tasks = [
                    ktask
                    for ktask in (kanban_result.get("tasks") or [])
                    if isinstance(ktask, dict)
                ]
                kanban_task_ids = {str(ktask.get("id", "")) for ktask in kanban_tasks}
        except Exception as exc:
            logger.debug("Could not load Kanban tasks: %s", exc)

        # 1) Agency incoming records
        try:
            from .node_manager import manager

            records = manager.incoming_tasks_sync(limit=100, timeout=5)
            for rec in records:
                task_id = str(rec.get("task_id", ""))
                kanban_tid = rec.get("kanban_task_id")
                linked_status = "none"
                if kanban_tid:
                    linked_status = "present" if str(kanban_tid) in kanban_task_ids else "missing"

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
        for ktask in kanban_tasks:
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
                    board=ktask.get("board"),
                    assignee=ktask.get("assignee"),
                    available_actions=actions,
                )
            )

        # Sort newest first, cache the unified list, then apply an optional status filter.
        tasks.sort(key=lambda t: t.updated_at or t.created_at or 0, reverse=True)
        if tasks:
            _tasks_cache = list(tasks)
            _tasks_cache_at = time.time()
        else:
            # Startup can briefly report an empty manager snapshot while the runtime warms.
            # Do not cache that transient empty view.
            clear_tasks_cache()
        if status:
            normalized = status.strip().lower()
            active_statuses = {"active", "running", "working", "queued", "processing", "received"}
            if normalized == "active":
                tasks = [t for t in tasks if (t.status or "").lower() in active_statuses]
            else:
                tasks = [t for t in tasks if (t.status or "").lower() == normalized]
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
        clear_tasks_cache()
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
        clear_tasks_cache()
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
        clear_tasks_cache()
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
        clear_tasks_cache()
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

        target_agent = str(req.target_agent or "").strip()
        target = target_agent or req.skill or req.department or "auto-router"
        priority_value = _dispatch_priority(req.priority)
        kanban_task_id: str | None = None
        metadata = {
            "source": "dashboard",
            "priority": str(req.priority),
            "target_agent": target_agent or None,
            "department": req.department,
            "skill": req.skill,
        }

        # Dashboard dispatches should be visible in Kanban by default.  When a
        # target agent is chosen, create_task routes to that agent's department
        # board via kanban_bridge's department mapping.
        if req.create_kanban_task:
            try:
                from .kanban_bridge import create_task as kanban_create

                kresult = kanban_create(
                    title=req.message[:80],
                    description=req.message,
                    assigned_to=target_agent or None,
                    skills=[req.skill] if req.skill else None,
                    metadata=metadata,
                    priority=priority_value,
                )
                if kresult.get("ok"):
                    kanban_task_id = str(kresult.get("task_id"))
            except Exception as exc:
                logger.warning("Dashboard dispatch: Kanban task creation failed: %s", exc)

        dispatch_message = req.message
        if kanban_task_id or target_agent or req.department or req.skill:
            context_lines = ["", "Dashboard dispatch context:"]
            if target_agent:
                context_lines.append(f"- Target agent: {target_agent}")
            if req.department:
                context_lines.append(f"- Department: {req.department}")
            if req.skill:
                context_lines.append(f"- Requested skill: {req.skill}")
            if kanban_task_id:
                context_lines.append(f"- Kanban task id: {kanban_task_id}")
            context_lines.append(f"- Priority: {req.priority}")
            dispatch_message = req.message.rstrip() + "\n" + "\n".join(context_lines)

        try:
            if target_agent.startswith("agency-"):
                from .pool.tools import pool_send

                pool_result = pool_send(target_agent, dispatch_message)
                task_id = _extract_dispatch_id(pool_result, "task_id") or _extract_dispatch_id(
                    pool_result, "queue_id"
                )
                is_error = pool_result.startswith("Error:")
                if kanban_task_id:
                    try:
                        from .kanban_bridge import track_delegation, update_task

                        tracking_metadata = dict(metadata)
                        tracking_metadata["dispatch_result"] = pool_result
                        if task_id:
                            tracking_metadata["a2a_task_id"] = task_id
                        track_delegation(
                            message=dispatch_message,
                            assigned_to=target_agent,
                            skills=[req.skill] if req.skill else [],
                            a2a_task_id=task_id,
                            kanban_task_id=kanban_task_id,
                            metadata=tracking_metadata,
                        )
                        update_task(
                            kanban_task_id,
                            status="assigned" if pool_result.startswith("Queued task") else "running",
                            result=pool_result,
                        )
                    except Exception as exc:
                        logger.warning("Dashboard dispatch: Kanban tracking failed: %s", exc)
                clear_tasks_cache()
                return DashboardDispatchResponse(
                    ok=not is_error,
                    task_id=task_id,
                    kanban_task_id=kanban_task_id,
                    target=target_agent,
                    result_text=pool_result[:500],
                    error_text=pool_result if is_error else None,
                )

            result = manager.send_task_sync(
                message=dispatch_message,
                skill=req.skill,
                metadata=metadata,
                timeout=30,
            )
            task_id = str(result.get("task_id") or "")
            clear_tasks_cache()
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
    async def get_events(limit: int = Query(default=100, ge=1, le=500)) -> list[DashboardEvent]:
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
        return events[:limit]

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
        from .model_sets import (
            active_model_set_name,
            discover_model_set_files,
            load_model_set,
            model_set_summary,
        )

        files = discover_model_set_files()
        sets: list[dict[str, Any]] = []
        for name in sorted(files):
            try:
                ms = load_model_set(name)
                sets.append(model_set_summary(ms))
            except Exception as exc:
                sets.append({"name": name, "error": str(exc)})
        return {
            "model_sets": sets,
            "count": len(sets),
            "active_model_set": active_model_set_name(),
        }

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

        # Set via environment variable for the current dashboard process.
        os.environ["HERMES_AGENCY_MODEL_SET"] = name

        # Persist to the active Hermes profile config unless explicitly disabled.
        persisted = False
        config_path: str | None = None
        if bool(body.get("persist", True)):
            try:
                import yaml
                from hermes_cli.config import ensure_hermes_home, get_config_path
                from utils import atomic_yaml_write

                ensure_hermes_home()
                path = get_config_path()
                if path.exists():
                    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                else:
                    raw = {}
                config = raw if isinstance(raw, dict) else {}
                agency = config.setdefault("agency", {})
                if not isinstance(agency, dict):
                    agency = {}
                    config["agency"] = agency
                models = agency.setdefault("models", {})
                if not isinstance(models, dict):
                    models = {}
                    agency["models"] = models
                models["active_set"] = name
                atomic_yaml_write(path, config, sort_keys=False)
                persisted = True
                config_path = str(path)
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to persist active model set: {type(exc).__name__}: {exc}",
                ) from exc

        return {
            "ok": True,
            "active_model_set": name,
            "persisted": persisted,
            "config_path": config_path,
        }


    # -----------------------------------------------------------------------
    # GET /api/model-sets/{name}/source
    # -----------------------------------------------------------------------

    @router.get("/model-sets/{name}/source")
    async def get_model_set_source(name: str) -> dict[str, Any]:
        from .model_sets import discover_model_set_files, user_model_sets_dir

        files = discover_model_set_files()
        path = files.get(name)
        if path is None:
            raise HTTPException(status_code=404, detail=f"Unknown model set: {name}")
        user_dir = user_model_sets_dir()
        return {
            "name": name,
            "source_path": str(path),
            "source": "user" if user_dir in path.parents else "packaged",
            "editable": user_dir in path.parents,
            "content": path.read_text(encoding="utf-8"),
        }

    # -----------------------------------------------------------------------
    # POST /api/model-sets — create or duplicate a user model set
    # -----------------------------------------------------------------------

    @router.post("/model-sets", dependencies=[Depends(require_token)])
    async def create_model_set(body: dict[str, Any]) -> dict[str, Any]:
        import yaml

        from .model_sets import (
            discover_model_set_files,
            load_model_set,
            model_set_summary,
            user_model_sets_dir,
        )

        name = _safe_model_set_name(str(body.get("name") or ""))
        if not name:
            raise HTTPException(status_code=400, detail="A model set name is required")
        files = discover_model_set_files()
        if name in files:
            raise HTTPException(status_code=409, detail=f"Model set already exists: {name}")

        duplicate_from = str(body.get("duplicate_from") or "").strip()
        content = str(body.get("content") or "").strip()
        if duplicate_from:
            source_path = files.get(duplicate_from)
            if source_path is None:
                raise HTTPException(status_code=404, detail=f"Unknown source model set: {duplicate_from}")
            raw = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise HTTPException(status_code=400, detail="Source model set is not a YAML mapping")
            raw["name"] = name
            content = yaml.safe_dump(raw, sort_keys=False)
        elif not content:
            content = _default_model_set_yaml(name)

        target_dir = user_model_sets_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{name}.yaml"
        _validate_model_set_yaml_content(content)
        target_path.write_text(content.rstrip() + "\n", encoding="utf-8")
        model_set = load_model_set(name)
        return {"ok": True, "model_set": model_set_summary(model_set), "source_path": str(target_path)}

    # -----------------------------------------------------------------------
    # PUT /api/model-sets/{name} — edit a user model set source file
    # -----------------------------------------------------------------------

    @router.put("/model-sets/{name}", dependencies=[Depends(require_token)])
    async def update_model_set(name: str, body: dict[str, Any]) -> dict[str, Any]:
        from .model_sets import (
            discover_model_set_files,
            load_model_set,
            model_set_summary,
            user_model_sets_dir,
        )

        clean_name = _safe_model_set_name(name)
        files = discover_model_set_files()
        path = files.get(clean_name)
        if path is None:
            raise HTTPException(status_code=404, detail=f"Unknown model set: {clean_name}")
        if user_model_sets_dir() not in path.parents:
            raise HTTPException(status_code=403, detail="Packaged model sets cannot be edited directly. Duplicate it first.")
        content = str(body.get("content") or "")
        _validate_model_set_yaml_content(content)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        model_set = load_model_set(clean_name)
        return {"ok": True, "model_set": model_set_summary(model_set), "source_path": str(path)}

    # -----------------------------------------------------------------------
    # DELETE /api/model-sets/{name} — delete a user model set
    # -----------------------------------------------------------------------

    @router.delete("/model-sets/{name}", dependencies=[Depends(require_token)])
    async def delete_model_set(name: str) -> dict[str, Any]:
        from .model_sets import active_model_set_name, discover_model_set_files, user_model_sets_dir

        clean_name = _safe_model_set_name(name)
        if clean_name == active_model_set_name():
            raise HTTPException(status_code=400, detail="Cannot delete the active model set")
        files = discover_model_set_files()
        path = files.get(clean_name)
        if path is None:
            raise HTTPException(status_code=404, detail=f"Unknown model set: {clean_name}")
        if user_model_sets_dir() not in path.parents:
            raise HTTPException(status_code=403, detail="Packaged model sets cannot be deleted")
        path.unlink()
        return {"ok": True, "deleted": clean_name}

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




def _safe_model_set_name(value: str) -> str:
    """Return a filesystem-safe model-set name/slug."""
    import re

    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip(".-_")
    return clean[:80]


def _validate_model_set_yaml_content(content: str) -> dict[str, Any]:
    import yaml

    if not str(content or "").strip():
        raise HTTPException(status_code=400, detail="Model set content cannot be empty")
    try:
        data = yaml.safe_load(content) or {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Model set YAML must be a mapping")
    if data.get("version") is None:
        raise HTTPException(status_code=400, detail="Model set YAML must include version")
    if not isinstance(data.get("families"), dict) or not data.get("families"):
        raise HTTPException(status_code=400, detail="Model set YAML must include at least one family")
    defaults = data.get("defaults")
    if not isinstance(defaults, dict) or not defaults.get("family"):
        raise HTTPException(status_code=400, detail="Model set YAML must include defaults.family")
    return data


def _default_model_set_yaml(name: str) -> str:
    return f"""version: 1
name: {name}
description: Custom Hermes Agency model set.
defaults:
  family: general_worker
families:
  general_worker:
    provider: openai-codex
    model: gpt-5.5
    reason: Default custom worker family.
profiles: {{}}
escalation:
  default_family: general_worker
  triggers: []
budget: {{}}
metadata:
  source: dashboard
"""

def _dispatch_priority(value: Any) -> int:
    """Map dashboard priority labels to Kanban's integer priority field."""
    if isinstance(value, int):
        return value
    text = str(value or "").strip().lower()
    mapping = {"low": 0, "medium": 1, "normal": 1, "high": 2, "critical": 3, "urgent": 3}
    if text in mapping:
        return mapping[text]
    try:
        return int(text)
    except ValueError:
        return 1


def _extract_dispatch_id(text: str, key: str) -> str | None:
    """Extract a compact key=value id from pool_send's human-readable result."""
    marker = f"{key}="
    if marker not in text:
        return None
    value = text.split(marker, 1)[1].split()[0].strip().strip(",.;")
    return value or None


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
