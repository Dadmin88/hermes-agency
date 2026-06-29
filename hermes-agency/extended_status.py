"""Extended Hermes Agency visibility and health summaries."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from .departments import DEPARTMENT_BOARD_SLUGS, get_department
from .doctor import run_doctor
from .kanban_bridge import list_tasks as kanban_list_tasks
from .node_manager import manager

TERMINAL_TASK_STATUSES = {"done", "completed", "failed", "blocked", "cancelled", "archived"}
RECENT_WINDOW_SECONDS = 24 * 60 * 60


def _duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _timestamp(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _status(task: dict[str, Any]) -> str:
    return str(task.get("plugin_status") or task.get("status") or "unknown")


def _department_for_task(task: dict[str, Any]) -> str:
    assignee = str(task.get("assignee") or "").strip()
    return get_department(assignee) or "Unassigned"


def _model_status() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        from .model_sets import active_model_set_name, load_model_set
        from .profile_config_writer import plan_model_set

        active = active_model_set_name(config=load_config())
        planned = plan_model_set(load_model_set(active))
        counts = Counter(item.status for item in planned)
        drift = sum(1 for item in planned if item.status == "changed")
        missing = sum(1 for item in planned if item.status == "missing")
        return {
            "ok": True,
            "active_set": active,
            "profiles_checked": len(planned),
            "drift": drift,
            "missing": missing,
            "status_counts": dict(sorted(counts.items())),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _gpt_bridge_status() -> dict[str, Any]:
    try:
        from .gpt_bridge import summary

        return summary()
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _roster_status(now: float) -> dict[str, Any]:
    try:
        from .pool.roster import load_roster

        roster = load_roster()
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    profiles = list(roster.get("profiles") or [])
    online = [p for p in profiles if p.get("online")]
    stale = []
    recently_seen = []
    for profile in profiles:
        last_seen = _timestamp(profile.get("last_seen"))
        age = None if last_seen is None else now - last_seen
        if profile.get("online") and age is not None and age > 30 * 60:
            stale.append(profile.get("name"))
        if age is not None and age <= RECENT_WINDOW_SECONDS:
            recently_seen.append(profile.get("name"))
    return {
        "ok": True,
        "total": int(roster.get("total") or len(profiles)),
        "online": int(roster.get("online") or len(online)),
        "offline": max(
            0, int(roster.get("total") or len(profiles)) - int(roster.get("online") or len(online))
        ),
        "recently_seen_24h": len(recently_seen),
        "stale_online": [name for name in stale if name],
        "state_path": roster.get("state_path"),
    }


def _kanban_status(now: float) -> dict[str, Any]:
    payload = kanban_list_tasks({"limit": 500, "include_archived": False, "sort": "created-desc"})
    if not (payload.get("available") and payload.get("ok")):
        return {
            "ok": False,
            "available": bool(payload.get("available")),
            "error": payload.get("warning") or payload.get("error") or "Kanban unavailable",
        }
    tasks = list(payload.get("tasks") or [])
    status_counts = Counter(_status(task) for task in tasks)
    created_recent = 0
    completed_recent = 0
    failed_recent = 0
    by_department: dict[str, Counter[str]] = defaultdict(Counter)
    for task in tasks:
        task_status = _status(task)
        department = _department_for_task(task)
        by_department[department][task_status] += 1
        created_at = _timestamp(task.get("created_at"))
        completed_at = _timestamp(task.get("completed_at"))
        if created_at is not None and now - created_at <= RECENT_WINDOW_SECONDS:
            created_recent += 1
        if completed_at is not None and now - completed_at <= RECENT_WINDOW_SECONDS:
            completed_recent += 1
            if task_status in {"failed", "blocked"}:
                failed_recent += 1
    departments = {}
    for department, slug in DEPARTMENT_BOARD_SLUGS.items():
        counts = by_department.get(department, Counter())
        active = sum(
            count for status, count in counts.items() if status not in TERMINAL_TASK_STATUSES
        )
        departments[department] = {
            "board": slug,
            "total": sum(counts.values()),
            "active": active,
            "status_counts": dict(sorted(counts.items())),
        }
    if by_department.get("Unassigned"):
        counts = by_department["Unassigned"]
        departments["Unassigned"] = {
            "board": None,
            "total": sum(counts.values()),
            "active": sum(
                count for status, count in counts.items() if status not in TERMINAL_TASK_STATUSES
            ),
            "status_counts": dict(sorted(counts.items())),
        }
    return {
        "ok": True,
        "task_count": len(tasks),
        "status_counts": dict(sorted(status_counts.items())),
        "throughput_24h": {
            "created": created_recent,
            "completed": completed_recent,
            "failed_or_blocked_completed": failed_recent,
        },
        "departments": departments,
    }


def extended_status() -> dict[str, Any]:
    now = time.time()
    info = manager.info()
    started_at = _timestamp(info.get("started_at"))
    peers = []
    peer_error = None
    try:
        peers = manager.list_peers_sync()
    except Exception as exc:  # pragma: no cover - runtime dependent
        peer_error = f"{type(exc).__name__}: {exc}"
    doctor = run_doctor()
    return {
        "ok": doctor.exit_code == 0,
        "generated_at": datetime.now(UTC).isoformat(),
        "node": {
            "started": bool(info.get("started")),
            "peer_id": info.get("peer_id") or info.get("last_peer_id"),
            "card_name": info.get("card_name"),
            "uptime_seconds": None if started_at is None else max(0.0, now - started_at),
            "serve_task_running": bool(info.get("serve_task_running")),
            "incoming": {
                "records": info.get("incoming_task_count", 0),
                "queued": info.get("incoming_queue_size", 0),
                "processing": info.get("incoming_processing_count", 0),
                "completed": info.get("incoming_completed_count", 0),
                "failed": info.get("incoming_failed_count", 0),
            },
            "connected_peers": len(peers),
            "peer_error": peer_error,
        },
        "doctor": {"exit_code": doctor.exit_code, "summary": doctor.summary},
        "models": _model_status(),
        "gpt_bridge": _gpt_bridge_status(),
        "roster": _roster_status(now),
        "kanban": _kanban_status(now),
    }


def render_extended_status(payload: dict[str, Any]) -> str:
    node = payload.get("node") or {}
    doctor = payload.get("doctor") or {}
    models = payload.get("models") or {}
    bridge = payload.get("gpt_bridge") or {}
    roster = payload.get("roster") or {}
    kanban = payload.get("kanban") or {}
    lines = ["Hermes Agency extended status"]
    lines.extend(
        [
            "  node:",
            f"    started: {node.get('started')}",
            f"    peer_id: {node.get('peer_id') or '-'}",
            f"    card: {node.get('card_name') or '-'}",
            f"    uptime: {_duration(node.get('uptime_seconds'))}",
            f"    serve_task_running: {node.get('serve_task_running')}",
            f"    connected_peers: {node.get('connected_peers', 0)}",
            "  incoming queue:",
        ]
    )
    incoming = node.get("incoming") or {}
    lines.append(
        f"    records={incoming.get('records', 0)} queued={incoming.get('queued', 0)} processing={incoming.get('processing', 0)} completed={incoming.get('completed', 0)} failed={incoming.get('failed', 0)}"
    )
    if node.get("peer_error"):
        lines.append(f"    peer_error: {node['peer_error']}")
    summary = doctor.get("summary") or {}
    lines.append(
        f"  doctor: pass={summary.get('pass', 0)} warn={summary.get('warn', 0)} fail={summary.get('fail', 0)} na={summary.get('na', 0)} exit={doctor.get('exit_code')}"
    )
    if models.get("ok"):
        lines.append(
            f"  models: active={models.get('active_set')} checked={models.get('profiles_checked')} drift={models.get('drift')} missing={models.get('missing')}"
        )
    else:
        lines.append(f"  models: unavailable ({models.get('error')})")
    bridge_counts = bridge.get("counts") or {}
    lines.append(f"  gpt_bridge: total={bridge.get('total', 0)} counts={bridge_counts or {}}")
    if roster.get("ok"):
        lines.append(
            f"  roster: online={roster.get('online', 0)}/{roster.get('total', 0)} offline={roster.get('offline', 0)} recently_seen_24h={roster.get('recently_seen_24h', 0)}"
        )
        if roster.get("stale_online"):
            lines.append(f"    stale_online: {', '.join(roster['stale_online'][:10])}")
    else:
        lines.append(f"  roster: unavailable ({roster.get('error')})")
    if kanban.get("ok"):
        throughput = kanban.get("throughput_24h") or {}
        lines.append(
            f"  kanban: tasks={kanban.get('task_count', 0)} statuses={kanban.get('status_counts') or {}}"
        )
        lines.append(
            f"    throughput_24h: created={throughput.get('created', 0)} completed={throughput.get('completed', 0)} failed_or_blocked_completed={throughput.get('failed_or_blocked_completed', 0)}"
        )
        lines.append("  department boards:")
        for department, data in (kanban.get("departments") or {}).items():
            lines.append(
                f"    - {department}: board={data.get('board') or '-'} total={data.get('total', 0)} active={data.get('active', 0)} statuses={data.get('status_counts') or {}}"
            )
    else:
        lines.append(f"  kanban: unavailable ({kanban.get('error')})")
    return "\n".join(lines)
