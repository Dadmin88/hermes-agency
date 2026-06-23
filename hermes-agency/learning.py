"""Learning/feedback infrastructure for Hermes Agency routing corrections."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import get_config


def _state_path() -> Path:
    cfg = get_config()
    home = cfg.home
    if home is None:
        from hermes_constants import get_hermes_home

        home = get_hermes_home() / ".agency"
    home.mkdir(parents=True, exist_ok=True)
    return home / "learning_corrections.json"


def _read() -> list[dict[str, Any]]:
    path = _state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _write(items: list[dict[str, Any]]) -> None:
    path = _state_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(items[-500:], indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def log_routing_correction(
    task_type: str,
    wrong_target: str,
    correct_target: str,
    *,
    note: str = "",
) -> dict[str, Any]:
    """Store Kyle's correction for future model-readable routing context."""

    cfg = get_config()
    if not cfg.team.learning:
        return {"ok": False, "disabled": True, "warning": "agency.team.learning is disabled"}
    correction = {
        "task_type": str(task_type or "").strip(),
        "wrong_target": str(wrong_target or "").strip(),
        "correct_target": str(correct_target or "").strip(),
        "note": str(note or "").strip(),
        "timestamp": time.time(),
    }
    if (
        not correction["task_type"]
        or not correction["wrong_target"]
        or not correction["correct_target"]
    ):
        return {"ok": False, "error": "task_type, wrong_target, and correct_target are required"}
    items = _read()
    items.append(correction)
    _write(items)
    return {"ok": True, "correction": correction, "count": len(items)}


def correction_history(task_type: str | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent corrections, optionally filtered by task type substring."""

    if not get_config().team.learning:
        return []
    items = _read()
    if task_type:
        needle = str(task_type).strip().lower()
        items = [item for item in items if needle in str(item.get("task_type") or "").lower()]
    return list(reversed(items[-max(1, limit) :]))


def learning_summary(task_type: str | None = None) -> dict[str, Any]:
    history = correction_history(task_type, limit=20)
    return {"enabled": get_config().team.learning, "corrections": history, "count": len(history)}
