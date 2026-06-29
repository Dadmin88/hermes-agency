"""Pull-based GPT bridge inbox for Hermes Agency escalations.

This module does not try to summon a ChatGPT conversation in the background.
Instead, agents/orchestrators can enqueue work into a durable inbox. A human
ChatGPT session can later pull, complete, and write results back through the
Hermes bridge tools.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from hermes_constants import get_hermes_home
except Exception:  # pragma: no cover - Hermes runtime import
    get_hermes_home = None  # type: ignore[assignment]

GPT_BRIDGE_VERSION = 1
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@dataclass(frozen=True)
class GptBridgeTask:
    task_id: str
    status: str
    task_description: str
    reason: str
    expected_output: str
    urgency: str
    source_profile: str
    source_task_id: str | None = None
    kanban_task_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    claimed_at: str | None = None
    claimed_by: str | None = None
    completed_at: str | None = None
    result: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": GPT_BRIDGE_VERSION,
            "task_id": self.task_id,
            "status": self.status,
            "task_description": self.task_description,
            "reason": self.reason,
            "expected_output": self.expected_output,
            "urgency": self.urgency,
            "source_profile": self.source_profile,
            "source_task_id": self.source_task_id,
            "kanban_task_id": self.kanban_task_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "claimed_at": self.claimed_at,
            "claimed_by": self.claimed_by,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"gpt-{stamp}-{secrets.token_hex(3)}"


def _clean(value: Any, *, max_len: int | None = None) -> str:
    text = " ".join(str(value or "").split()).strip()
    if max_len and len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def _hermes_root() -> Path:
    override = os.getenv("HERMES_AGENCY_GPT_BRIDGE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve().parent.parent
    if get_hermes_home is not None:
        try:
            home = Path(get_hermes_home()).expanduser().resolve()
            if home.parent.name == "profiles":
                return home.parent.parent
            return home
        except Exception:
            pass
    env_home = os.getenv("HERMES_HOME", "").strip()
    if env_home:
        home = Path(env_home).expanduser().resolve()
        if home.parent.name == "profiles":
            return home.parent.parent
        return home
    return Path("~/.hermes").expanduser().resolve()


def bridge_dir() -> Path:
    override = os.getenv("HERMES_AGENCY_GPT_BRIDGE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _hermes_root() / "agency" / "gpt_bridge"


def tasks_dir() -> Path:
    return bridge_dir() / "tasks"


def _task_path(task_id: str) -> Path:
    safe = _clean(task_id)
    if not safe or "/" in safe or ".." in safe:
        raise ValueError("invalid GPT bridge task_id")
    return tasks_dir() / f"{safe}.json"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def _read_task(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"GPT bridge task file must contain an object: {path}")
    return data


def _write_task(data: dict[str, Any]) -> dict[str, Any]:
    data["updated_at"] = _now()
    _atomic_write(_task_path(str(data["task_id"])), data)
    return data


def enqueue_task(
    task_description: str,
    *,
    reason: str = "",
    expected_output: str = "",
    urgency: str = "normal",
    source_profile: str = "",
    source_task_id: str | None = None,
    kanban_task_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    description = _clean(task_description)
    if not description:
        return {"ok": False, "error": "task_description is required"}
    created = _now()
    task = GptBridgeTask(
        task_id=_timestamp_id(),
        status="queued",
        task_description=description,
        reason=_clean(reason),
        expected_output=_clean(expected_output),
        urgency=_clean(urgency) or "normal",
        source_profile=_clean(source_profile) or current_profile_name(),
        source_task_id=_clean(source_task_id) or None,
        kanban_task_id=_clean(kanban_task_id) or None,
        created_at=created,
        updated_at=created,
        metadata=metadata or {},
    )
    data = task.as_dict()
    _atomic_write(_task_path(task.task_id), data)
    return {"ok": True, "task": data, "path": str(_task_path(task.task_id))}


def current_profile_name() -> str:
    try:
        from .config import current_profile_name as _current_profile_name

        return _current_profile_name()
    except Exception:
        return os.getenv("HERMES_PROFILE", "") or "unknown"


def get_task(task_id: str) -> dict[str, Any]:
    path = _task_path(task_id)
    if not path.exists():
        return {"ok": False, "error": f"unknown GPT bridge task: {task_id}", "task_id": task_id}
    return {"ok": True, "task": _read_task(path), "path": str(path)}


def list_tasks(
    *, status: str | None = None, include_terminal: bool = True, limit: int = 25
) -> dict[str, Any]:
    root = tasks_dir()
    if not root.is_dir():
        return {"ok": True, "tasks": [], "dir": str(root)}
    wanted = _clean(status).lower()
    tasks: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            task = _read_task(path)
        except Exception as exc:
            tasks.append(
                {"task_id": path.stem, "status": "invalid", "error": f"{type(exc).__name__}: {exc}"}
            )
            continue
        task_status = str(task.get("status") or "").lower()
        if wanted and task_status != wanted:
            continue
        if not include_terminal and task_status in TERMINAL_STATUSES:
            continue
        tasks.append(task)
        if len(tasks) >= limit:
            break
    return {"ok": True, "tasks": tasks, "dir": str(root)}


def claim_task(task_id: str, *, claimed_by: str = "ChatGPT") -> dict[str, Any]:
    loaded = get_task(task_id)
    if not loaded.get("ok"):
        return loaded
    task = loaded["task"]
    status = str(task.get("status") or "")
    if status in TERMINAL_STATUSES:
        return {"ok": False, "error": f"task is already {status}", "task": task}
    task["status"] = "claimed"
    task["claimed_at"] = _now()
    task["claimed_by"] = _clean(claimed_by) or "ChatGPT"
    return {"ok": True, "task": _write_task(task), "path": loaded.get("path")}


def complete_task(task_id: str, result: str, *, completed_by: str = "ChatGPT") -> dict[str, Any]:
    loaded = get_task(task_id)
    if not loaded.get("ok"):
        return loaded
    clean_result = str(result or "").strip()
    if not clean_result:
        return {"ok": False, "error": "result is required", "task_id": task_id}
    task = loaded["task"]
    if not task.get("claimed_at"):
        task["claimed_at"] = _now()
        task["claimed_by"] = _clean(completed_by) or "ChatGPT"
    task["status"] = "completed"
    task["completed_at"] = _now()
    task["completed_by"] = _clean(completed_by) or "ChatGPT"
    task["result"] = clean_result
    task["error"] = None
    return {"ok": True, "task": _write_task(task), "path": loaded.get("path")}


def fail_task(task_id: str, error: str, *, failed_by: str = "ChatGPT") -> dict[str, Any]:
    loaded = get_task(task_id)
    if not loaded.get("ok"):
        return loaded
    clean_error = _clean(error)
    if not clean_error:
        return {"ok": False, "error": "error is required", "task_id": task_id}
    task = loaded["task"]
    task["status"] = "failed"
    task["completed_at"] = _now()
    task["completed_by"] = _clean(failed_by) or "ChatGPT"
    task["error"] = clean_error
    return {"ok": True, "task": _write_task(task), "path": loaded.get("path")}


def summary() -> dict[str, Any]:
    all_tasks = list_tasks(limit=500).get("tasks", [])
    counts: dict[str, int] = {}
    for task in all_tasks:
        status = str(task.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"ok": True, "dir": str(tasks_dir()), "counts": counts, "total": len(all_tasks)}
