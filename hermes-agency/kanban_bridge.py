"""Bridge between the Hermes Agency plugin and Hermes' existing Kanban board.

This module intentionally uses ``hermes_cli.kanban_db`` rather than defining a
plugin-local schema.  The bridge stores Hermes Agency-specific correlation data
in existing fields:

* ``tasks.body`` carries the delegation/context packet plus a compact metadata
  JSON block.
* ``tasks.idempotency_key`` is used for A2A task de-duplication.
* ``task_comments`` records lifecycle notes and metadata/result/error details.
* ``task_events`` records status transitions through the Kanban DB event log.

The public functions are fail-open: if the Kanban module/DB is unavailable or
``agency.team.kanban_integration`` is disabled, callers get an
``available: false`` result and A2A routing continues without Kanban tracking.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from typing import Any, cast

from .config import current_profile_name, get_config

log = logging.getLogger(__name__)

TERMINAL_PLUGIN_STATUSES = {"done", "blocked", "failed"}
_A2A_TO_KANBAN: dict[str, str] = {}


class KanbanUnavailable(RuntimeError):
    """Raised internally when the board cannot be reached."""


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(cast(Any, value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _json(data: Any) -> str:
    return json.dumps(_jsonable(data), ensure_ascii=False, sort_keys=True)


def _clean(value: Any, *, max_len: int | None = None) -> str:
    text = " ".join(str(value or "").split()).strip()
    if max_len and len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def _enabled() -> bool:
    try:
        cfg = get_config()
        return bool(cfg.enabled and cfg.team.kanban_integration)
    except Exception as exc:
        log.warning("Hermes Agency Kanban config check failed: %s", exc)
        return False


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    if reason:
        log.warning("Hermes Agency Kanban unavailable: %s", reason)
    payload = {"available": False, "ok": False, "warning": reason}
    payload.update(extra)
    return payload


def _import_kb() -> Any:
    if not _enabled():
        raise KanbanUnavailable("agency.team.kanban_integration is disabled")
    try:
        from hermes_cli import kanban_db as kb  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on host install
        raise KanbanUnavailable(f"could not import hermes_cli.kanban_db: {exc}") from exc
    return kb


@contextmanager
def _connection() -> Iterator[tuple[Any, Any]]:
    """Yield ``(kb, conn)`` for the active Kanban board, initializing if needed."""

    kb = _import_kb()
    try:
        # Mirrors ``hermes kanban``: opening a board is allowed to create/migrate
        # the existing Kanban DB.  Permission/path errors are reported as graceful
        # unavailability to callers.
        kb.init_db()
        with kb.connect_closing() as conn:
            yield kb, conn
    except KanbanUnavailable:
        raise
    except Exception as exc:
        raise KanbanUnavailable(f"could not open Kanban database: {exc}") from exc


def _safe_call(fn: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except KanbanUnavailable as exc:
        return _unavailable(str(exc))
    except Exception as exc:
        return _unavailable(f"{type(exc).__name__}: {exc}")


def _task_to_dict(kb: Any, conn: Any, task: Any, *, include_thread: bool = False) -> dict[str, Any]:
    if task is None:
        return {}
    data = {
        "id": task.id,
        "title": task.title,
        "body": task.body,
        "assignee": task.assignee,
        "status": task.status,
        "plugin_status": _plugin_status(kb, conn, task),
        "priority": task.priority,
        "tenant": task.tenant,
        "workspace_kind": task.workspace_kind,
        "workspace_path": task.workspace_path,
        "branch_name": task.branch_name,
        "created_by": task.created_by,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "result": task.result,
        "skills": list(task.skills or []),
        "idempotency_key": getattr(task, "idempotency_key", None),
        "session_id": getattr(task, "session_id", None),
    }
    try:
        data["parents"] = kb.parent_ids(conn, task.id)
        data["children"] = kb.child_ids(conn, task.id)
    except Exception:
        data["parents"] = []
        data["children"] = []
    if include_thread:
        data["comments"] = [
            {"id": c.id, "author": c.author, "body": c.body, "created_at": c.created_at}
            for c in kb.list_comments(conn, task.id)
        ]
        data["events"] = [
            {
                "id": e.id,
                "kind": e.kind,
                "payload": e.payload,
                "created_at": e.created_at,
                "run_id": getattr(e, "run_id", None),
            }
            for e in kb.list_events(conn, task.id)
        ]
    return data


def _latest_event_kind(kb: Any, conn: Any, task_id: str) -> str | None:
    try:
        events = kb.list_events(conn, task_id)
    except Exception:
        return None
    return events[-1].kind if events else None


def _plugin_status(kb: Any, conn: Any, task: Any) -> str:
    if task.status == "done":
        return "done"
    if task.status == "running":
        return "in_progress"
    if task.status == "blocked":
        return "failed" if _latest_event_kind(kb, conn, task.id) == "failed" else "blocked"
    if task.assignee:
        return "assigned"
    return "unassigned"


def _status_filter(status: str | None) -> str | None:
    if not status:
        return None
    normalized = _clean(status).lower()
    aliases = {
        "assigned": "ready",
        "unassigned": "ready",
        "in_progress": "running",
        "in-progress": "running",
        "working": "running",
        "completed": "done",
        "complete": "done",
        "failed": "blocked",
    }
    return aliases.get(normalized, normalized)


def _a2a_idempotency_key(a2a_task_id: str | None) -> str | None:
    clean = _clean(a2a_task_id)
    return f"agency:a2a:{clean}" if clean else None


def _resolve_task_id(kb: Any, conn: Any, task_id: str) -> str | None:
    clean = _clean(task_id)
    if not clean:
        return None
    if kb.get_task(conn, clean):
        return clean
    if clean in _A2A_TO_KANBAN:
        return _A2A_TO_KANBAN[clean]
    key = _a2a_idempotency_key(clean)
    if key:
        row = conn.execute(
            "SELECT id FROM tasks WHERE idempotency_key = ? AND status != 'archived' "
            "ORDER BY created_at DESC LIMIT 1",
            (key,),
        ).fetchone()
        if row:
            _A2A_TO_KANBAN[clean] = row["id"]
            return row["id"]
    return None


def _append_event(
    kb: Any, conn: Any, task_id: str, kind: str, payload: dict[str, Any] | None = None
) -> None:
    # kanban_db intentionally keeps event insertion private; this bridge uses it
    # rather than inventing a parallel audit table.  Fall back to raw SQL if the
    # helper ever moves.
    if hasattr(kb, "_append_event"):
        kb._append_event(conn, task_id, kind, _jsonable(payload))  # noqa: SLF001
        return
    conn.execute(
        "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
        (task_id, kind, _json(payload) if payload else None, int(time.time())),
    )


def _body_with_metadata(description: str, metadata: dict[str, Any]) -> str:
    body = str(description or "").strip()
    clean_metadata = {k: v for k, v in (metadata or {}).items() if v not in (None, "")}
    if clean_metadata:
        metadata_block = "Hermes Agency metadata:\n```json\n" + _json(clean_metadata) + "\n```"
        body = f"{body}\n\n{metadata_block}" if body else metadata_block
    return body


def _author() -> str:
    return current_profile_name() or os.getenv("HERMES_PROFILE") or "agency"


def create_task(
    title: str,
    description: str = "",
    assigned_to: str | None = None,
    skills: list[str] | tuple[str, ...] | None = None,
    dependencies: list[str] | tuple[str, ...] | None = None,
    metadata: dict[str, Any] | None = None,
    priority: int = 0,
) -> dict[str, Any]:
    """Create an Hermes Agency-tracked Kanban task.

    ``assigned_to`` maps to Kanban's existing ``assignee`` column.  No separate
    ``assigned`` status exists in the current Kanban schema: assigned work is a
    ``ready``/``todo`` task with an assignee, while unassigned work has no
    assignee.  Dependencies are stored as normal Kanban parent links.
    """

    return _safe_call(
        _create_task_impl,
        title,
        description,
        assigned_to,
        list(skills or []),
        list(dependencies or []),
        dict(metadata or {}),
        int(priority or 0),
    )


def _create_task_impl(
    title: str,
    description: str,
    assigned_to: str | None,
    skills: list[str],
    dependencies: list[str],
    metadata: dict[str, Any],
    priority: int,
) -> dict[str, Any]:
    clean_title = _clean(title, max_len=80) or "Hermes Agency task"
    clean_assignee = _clean(assigned_to) or None
    a2a_task_id = _clean(metadata.get("a2a_task_id")) or None
    session_id = _clean(metadata.get("session_id") or metadata.get("channel")) or None
    tenant = _clean(metadata.get("tenant")) or get_config().team.tenant or None
    idempotency_key = (
        _a2a_idempotency_key(a2a_task_id) or _clean(metadata.get("idempotency_key")) or None
    )
    body = _body_with_metadata(description, metadata)

    with _connection() as (kb, conn):
        try:
            task_id = kb.create_task(
                conn,
                title=clean_title,
                body=body,
                assignee=clean_assignee,
                created_by=_author(),
                parents=tuple(_clean(dep) for dep in dependencies if _clean(dep)),
                skills=skills or None,
                idempotency_key=idempotency_key,
                session_id=session_id,
                tenant=tenant,
                priority=priority,
                initial_status="running",
            )
        except ValueError as exc:
            # AgentCards can expose runtime capabilities that Kanban treats as
            # toolsets rather than skills. Preserve the task and metadata rather
            # than failing all Kanban tracking because of a skill-name mismatch.
            if "toolset name" not in str(exc):
                raise
            task_id = kb.create_task(
                conn,
                title=clean_title,
                body=body
                + "\n\n[Hermes Agency note: requested skills were not stored because Kanban rejected them as toolset names.]",
                assignee=clean_assignee,
                created_by=_author(),
                parents=tuple(_clean(dep) for dep in dependencies if _clean(dep)),
                skills=None,
                idempotency_key=idempotency_key,
                session_id=session_id,
                tenant=tenant,
                priority=priority,
                initial_status="running",
            )
        if a2a_task_id:
            _A2A_TO_KANBAN[a2a_task_id] = task_id
        kb.add_comment(
            conn,
            task_id,
            _author(),
            "Hermes Agency task created"
            + (f" for A2A task {a2a_task_id}" if a2a_task_id else "")
            + (f"; assigned_to={clean_assignee}" if clean_assignee else "; unassigned"),
        )
        task = kb.get_task(conn, task_id)
        return {
            "available": True,
            "ok": True,
            "task_id": task_id,
            "status": _plugin_status(kb, conn, task),
            "task": _task_to_dict(kb, conn, task, include_thread=True),
        }


def track_delegation(
    *,
    message: str,
    assigned_to: str | None,
    skills: list[str] | tuple[str, ...] | None = None,
    a2a_task_id: str | None = None,
    kanban_task_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Create or update the Kanban task for an outbound A2A delegation."""

    return _safe_call(
        _track_delegation_impl,
        message,
        assigned_to,
        list(skills or []),
        a2a_task_id,
        kanban_task_id,
        dict(metadata or {}),
        description,
    )


def _track_delegation_impl(
    message: str,
    assigned_to: str | None,
    skills: list[str],
    a2a_task_id: str | None,
    kanban_task_id: str | None,
    metadata: dict[str, Any],
    description: str | None,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    if a2a_task_id:
        meta["a2a_task_id"] = a2a_task_id
    if kanban_task_id:
        meta["kanban_task_id"] = kanban_task_id
    if kanban_task_id:
        result = add_comment(
            kanban_task_id,
            "Hermes Agency delegation sent"
            + (f"; A2A task_id={a2a_task_id}" if a2a_task_id else ""),
        )
        if result.get("available") and a2a_task_id:
            with _connection() as (kb, conn):
                resolved = _resolve_task_id(kb, conn, kanban_task_id)
                if resolved:
                    _A2A_TO_KANBAN[a2a_task_id] = resolved
                    _append_event(kb, conn, resolved, "agency_delegated", meta)
                    task = kb.get_task(conn, resolved)
                    return {
                        "available": True,
                        "ok": True,
                        "task_id": resolved,
                        "status": _plugin_status(kb, conn, task),
                        "task": _task_to_dict(kb, conn, task, include_thread=True),
                    }
        return result
    return _create_task_impl(
        _clean(message, max_len=80),
        description or message,
        assigned_to,
        skills,
        [],
        meta,
        0,
    )


def update_task(
    task_id: str,
    status: str | None = None,
    result: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Update an Hermes Agency-tracked Kanban task's lifecycle state."""

    return _safe_call(_update_task_impl, task_id, status, result, error)


def _has_unfinished_parents(kb: Any, conn: Any, task_id: str) -> bool:
    rows = conn.execute(
        "SELECT p.status FROM tasks p JOIN task_links l ON l.parent_id = p.id WHERE l.child_id = ?",
        (task_id,),
    ).fetchall()
    return any(row["status"] not in {"done", "archived"} for row in rows)


def _set_status(
    kb: Any, conn: Any, task_id: str, status: str, payload: dict[str, Any] | None = None
) -> None:
    now = int(time.time())
    fields = ["status = ?"]
    params: list[Any] = [status]
    if status == "running":
        fields.append("started_at = COALESCE(started_at, ?)")
        params.append(now)
    if status in {"done", "blocked", "archived"}:
        fields.append("completed_at = COALESCE(completed_at, ?)")
        params.append(now)
    params.append(task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", tuple(params))
    _append_event(kb, conn, task_id, "agency_status", {"status": status, **(payload or {})})


def _update_task_impl(
    task_id: str, status: str | None, result: str | None, error: str | None
) -> dict[str, Any]:
    with _connection() as (kb, conn):
        resolved = _resolve_task_id(kb, conn, task_id)
        if not resolved:
            return {
                "available": True,
                "ok": False,
                "error": f"unknown Kanban/A2A task id: {task_id}",
            }
        clean_status = _clean(status).lower()
        comment_bits = []
        if result:
            comment_bits.append(f"RESULT:\n{result}")
        if error:
            comment_bits.append(f"ERROR:\n{error}")
        if comment_bits:
            kb.add_comment(conn, resolved, _author(), "\n\n".join(comment_bits))

        if clean_status in {"done", "completed", "complete"}:
            if not kb.complete_task(
                conn,
                resolved,
                result=result,
                summary=result,
                metadata={"agency_status": clean_status or "done"},
            ):
                _set_status(kb, conn, resolved, "done", {"result": result})
        elif clean_status in {"blocked", "escalated"}:
            if error or result:
                kb.add_comment(conn, resolved, _author(), f"BLOCKED: {error or result}")
            if not kb.block_task(conn, resolved, reason=error or result):
                _set_status(kb, conn, resolved, "blocked", {"reason": error or result})
        elif clean_status in {"failed", "error"}:
            if error or result:
                kb.add_comment(conn, resolved, _author(), f"FAILED: {error or result}")
            if not kb.block_task(conn, resolved, reason=error or result):
                _set_status(kb, conn, resolved, "blocked", {"error": error or result})
            _append_event(kb, conn, resolved, "failed", {"error": error, "result": result})
        elif clean_status in {"in_progress", "in-progress", "working", "running"}:
            _set_status(kb, conn, resolved, "running", {"source": "agency"})
        elif clean_status in {"assigned", "unassigned", "ready", "todo"}:
            if clean_status == "unassigned":
                conn.execute("UPDATE tasks SET assignee = NULL WHERE id = ?", (resolved,))
            target_status = "todo" if _has_unfinished_parents(kb, conn, resolved) else "ready"
            _set_status(
                kb,
                conn,
                resolved,
                target_status,
                {"source": "agency", "requested_status": clean_status},
            )
        elif clean_status:
            return {"available": True, "ok": False, "error": f"unsupported status: {status}"}

        kb.recompute_ready(conn)
        task = kb.get_task(conn, resolved)
        return {
            "available": True,
            "ok": True,
            "task_id": resolved,
            "status": _plugin_status(kb, conn, task),
            "task": _task_to_dict(kb, conn, task, include_thread=True),
        }


def get_task(task_id: str) -> dict[str, Any]:
    """Return Kanban task details, accepting either a Kanban id or A2A id."""

    return _safe_call(_get_task_impl, task_id)


def _get_task_impl(task_id: str) -> dict[str, Any]:
    with _connection() as (kb, conn):
        resolved = _resolve_task_id(kb, conn, task_id)
        if not resolved:
            return {
                "available": True,
                "ok": False,
                "error": f"unknown Kanban/A2A task id: {task_id}",
            }
        task = kb.get_task(conn, resolved)
        return {
            "available": True,
            "ok": True,
            "task_id": resolved,
            "task": _task_to_dict(kb, conn, task, include_thread=True),
        }


def list_tasks(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """List Kanban tasks with optional filters: status, assignee, tenant, limit."""

    return _safe_call(_list_tasks_impl, dict(filters or {}))


def _list_tasks_impl(filters: dict[str, Any]) -> dict[str, Any]:
    status = _status_filter(filters.get("status"))
    assignee = _clean(filters.get("assignee") or filters.get("assigned_to")) or None
    requested_tenant = _clean(filters.get("tenant"))
    tenant = (
        None if requested_tenant == "*" else (requested_tenant or get_config().team.tenant or None)
    )
    session_id = _clean(filters.get("session_id")) or None
    limit = filters.get("limit")
    include_archived = bool(filters.get("include_archived") or filters.get("archived"))
    with _connection() as (kb, conn):
        kb.recompute_ready(conn)
        tasks = kb.list_tasks(
            conn,
            assignee=assignee,
            status=status,
            tenant=tenant,
            session_id=session_id,
            include_archived=include_archived,
            limit=int(limit) if limit else None,
            order_by=filters.get("order_by") or filters.get("sort"),
        )
        data = [_task_to_dict(kb, conn, task, include_thread=False) for task in tasks]
        requested_status = _clean(filters.get("status")).lower()
        if requested_status == "assigned":
            data = [task for task in data if task.get("assignee")]
        elif requested_status == "unassigned":
            data = [task for task in data if not task.get("assignee")]
        elif requested_status == "failed":
            data = [task for task in data if task.get("plugin_status") == "failed"]
        return {"available": True, "ok": True, "tasks": data, "count": len(data)}


def add_comment(task_id: str, body: str) -> dict[str, Any]:
    """Append a comment to a Kanban task thread."""

    return _safe_call(_add_comment_impl, task_id, body)


def _add_comment_impl(task_id: str, body: str) -> dict[str, Any]:
    with _connection() as (kb, conn):
        resolved = _resolve_task_id(kb, conn, task_id)
        if not resolved:
            return {
                "available": True,
                "ok": False,
                "error": f"unknown Kanban/A2A task id: {task_id}",
            }
        comment_id = kb.add_comment(conn, resolved, _author(), str(body or ""))
        return {"available": True, "ok": True, "task_id": resolved, "comment_id": comment_id}


def link_tasks(parent_id: str, child_id: str) -> dict[str, Any]:
    """Create a Kanban dependency link: child waits for parent."""

    return _safe_call(_link_tasks_impl, parent_id, child_id)


def _link_tasks_impl(parent_id: str, child_id: str) -> dict[str, Any]:
    with _connection() as (kb, conn):
        parent = _resolve_task_id(kb, conn, parent_id)
        child = _resolve_task_id(kb, conn, child_id)
        if not parent or not child:
            return {
                "available": True,
                "ok": False,
                "error": f"unknown task link endpoint: {parent_id} -> {child_id}",
            }
        kb.link_tasks(conn, parent, child)
        kb.recompute_ready(conn)
        return {"available": True, "ok": True, "parent_id": parent, "child_id": child}


def claim_task(task_id: str, assignee: str, *, start: bool = False) -> dict[str, Any]:
    """Assign an unclaimed task to an agent for Phase-3 self-serve fallback."""

    return _safe_call(_claim_task_impl, task_id, assignee, start)


def _claim_task_impl(task_id: str, assignee: str, start: bool) -> dict[str, Any]:
    clean_assignee = _clean(assignee)
    if not clean_assignee:
        return {"available": True, "ok": False, "error": "assignee is required"}
    with _connection() as (kb, conn):
        resolved = _resolve_task_id(kb, conn, task_id)
        if not resolved:
            return {
                "available": True,
                "ok": False,
                "error": f"unknown Kanban/A2A task id: {task_id}",
            }
        task = kb.get_task(conn, resolved)
        if task.assignee and task.assignee != clean_assignee:
            return {
                "available": True,
                "ok": False,
                "error": f"task already assigned to {task.assignee}",
            }
        kb.assign_task(conn, resolved, clean_assignee)
        if start:
            _set_status(kb, conn, resolved, "running", {"claimed_by": clean_assignee})
        task = kb.get_task(conn, resolved)
        return {
            "available": True,
            "ok": True,
            "task_id": resolved,
            "task": _task_to_dict(kb, conn, task, include_thread=True),
        }


def assign_task(task_id: str, assignee: str | None) -> dict[str, Any]:
    """Assign/reassign a Kanban task to the selected agent."""

    return _safe_call(_assign_task_impl, task_id, assignee)


def _assign_task_impl(task_id: str, assignee: str | None) -> dict[str, Any]:
    with _connection() as (kb, conn):
        resolved = _resolve_task_id(kb, conn, task_id)
        if not resolved:
            return {
                "available": True,
                "ok": False,
                "error": f"unknown Kanban/A2A task id: {task_id}",
            }
        if not kb.assign_task(conn, resolved, _clean(assignee) or None):
            return {"available": True, "ok": False, "error": f"could not assign task: {resolved}"}
        task = kb.get_task(conn, resolved)
        return {
            "available": True,
            "ok": True,
            "task_id": resolved,
            "task": _task_to_dict(kb, conn, task, include_thread=True),
        }


def find_self_serve_tasks(
    skills: list[str] | tuple[str, ...], *, assignee: str | None = None, limit: int = 20
) -> dict[str, Any]:
    """Return unassigned ready/todo tasks whose requested skills overlap ``skills``."""

    return _safe_call(_find_self_serve_tasks_impl, list(skills or []), assignee, limit)


def _find_self_serve_tasks_impl(
    skills: list[str], assignee: str | None, limit: int
) -> dict[str, Any]:
    wanted = {str(skill).strip().lower() for skill in skills if str(skill).strip()}
    with _connection() as (kb, conn):
        kb.recompute_ready(conn)
        tasks = kb.list_tasks(
            conn,
            status="ready",
            tenant=get_config().team.tenant,
            limit=max(limit * 3, limit),
            include_archived=False,
        )
        candidates = []
        for task in tasks:
            if task.assignee and (not assignee or task.assignee != assignee):
                continue
            task_skills = {str(skill).lower() for skill in (task.skills or [])}
            if wanted and task_skills and not (wanted & task_skills):
                continue
            candidates.append(_task_to_dict(kb, conn, task, include_thread=False))
            if len(candidates) >= limit:
                break
        return {"available": True, "ok": True, "tasks": candidates, "count": len(candidates)}
