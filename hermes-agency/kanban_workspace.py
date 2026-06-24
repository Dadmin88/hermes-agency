"""Kanban workspace preservation helpers for Hermes Agency.

Hermes core historically treated scratch workspaces as ephemeral and deleted
``workspace_kind='scratch'`` directories when a task completed. Agency tasks can
produce user-facing artifacts in those workspaces, so the plugin defaults to
preserving them when the process has Hermes Agency loaded.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import get_config

log = logging.getLogger(__name__)
_PATCH_FLAG = "_hermes_agency_preserve_patch_installed"
_ORIGINAL_CLEANUP = "_hermes_agency_original_cleanup_workspace"


def install_workspace_preservation_patch(kb: Any | None = None) -> bool:
    """Patch ``hermes_cli.kanban_db._cleanup_workspace`` to preserve artifacts.

    The patch is intentionally fail-open and idempotent. When
    ``agency.kanban.preserve_workspaces`` is false, it delegates to the original
    Hermes cleanup behavior. When true, scratch workspace directories are left in
    place and only stale worker tmux cleanup is attempted.
    """

    if kb is None:
        try:
            from hermes_cli import kanban_db as imported_kb
        except Exception as exc:  # pragma: no cover - depends on host install
            log.debug("Hermes Kanban DB unavailable for workspace preservation patch: %s", exc)
            return False
        kb_module = imported_kb
    else:
        kb_module = kb

    original = getattr(kb_module, "_cleanup_workspace", None)
    if not callable(original):
        return False
    if getattr(kb_module, _PATCH_FLAG, False):
        return True

    setattr(kb_module, _ORIGINAL_CLEANUP, original)

    def _agency_cleanup_workspace(conn: Any, task_id: str) -> None:
        try:
            cfg = get_config()
            if not cfg.kanban.preserve_workspaces:
                original(conn, task_id)
                return

            row = conn.execute(
                "SELECT workspace_kind, workspace_path FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                return
            kind = row["workspace_kind"]
            path = row["workspace_path"]
            if kind != "scratch" or not path:
                original(conn, task_id)
                return

            workspace = Path(path)
            if workspace.exists():
                log.info("Preserved Kanban scratch workspace for task %s: %s", task_id, workspace)

            cleanup_tmux = getattr(kb_module, "_cleanup_worker_tmux", None)
            if callable(cleanup_tmux):
                cleanup_tmux(conn, task_id)
        except Exception:
            # Match Hermes core cleanup semantics: task completion must never fail
            # because cleanup/preservation bookkeeping hit an environment issue.
            log.debug("Hermes Agency workspace preservation cleanup failed", exc_info=True)

    kb_module._cleanup_workspace = _agency_cleanup_workspace
    setattr(kb_module, _PATCH_FLAG, True)
    return True
