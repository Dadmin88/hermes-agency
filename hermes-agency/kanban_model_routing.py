"""Integration patch that applies Agency smart model routing to Kanban spawns."""

from __future__ import annotations

import json
import logging
from typing import Any

from .model_sets import active_model_set_name, load_model_set
from .smart_model_router import ROUTE_METADATA_KEY, TaskRoutingContext, route_task_model

log = logging.getLogger(__name__)
_PATCH_ATTR = "_hermes_agency_model_router_patched"
_ORIGINAL_ATTR = "_hermes_agency_original_default_spawn"


def install_task_model_router_patch() -> bool:
    """Patch Hermes Kanban's default spawn path to set per-run model overrides.

    Hermes core already supports ``Task.model_override`` and passes it to the
    worker CLI as ``-m``. The Agency plugin owns the task-aware policy, so this
    wrapper computes a conservative decision immediately before spawn without
    permanently rewriting the assignee profile's config.yaml.
    """

    try:
        from hermes_cli import kanban_db as kb  # type: ignore
    except Exception as exc:
        log.debug("Agency smart model router patch skipped: %s", exc)
        return False

    if getattr(kb, _PATCH_ATTR, False):
        return True
    original = getattr(kb, "_default_spawn", None)
    if original is None:
        return False

    def _agency_routed_spawn(task: Any, workspace: str, *, board: str | None = None) -> Any:
        decision = _route_for_task(kb, task, board=board)
        _record_route(kb, task, decision, board=board)
        if decision.block_reason:
            _block_for_provider_health(kb, task, decision, board=board)
            raise RuntimeError(decision.block_reason)
        if decision.model_override:
            setattr(task, "model_override", decision.model_override)
        return original(task, workspace, board=board)

    setattr(kb, _ORIGINAL_ATTR, original)
    setattr(kb, "_default_spawn", _agency_routed_spawn)
    setattr(kb, _PATCH_ATTR, True)
    return True


def _route_for_task(kb: Any, task: Any, *, board: str | None = None):
    model_set = None
    user_config: dict[str, Any] = {}
    try:
        from hermes_cli.config import load_config

        loaded = load_config()
        user_config = loaded if isinstance(loaded, dict) else {}
        model_set = load_model_set(active_model_set_name(config=user_config))
    except Exception:
        try:
            model_set = load_model_set("openai-codex-only")
        except Exception:
            model_set = None

    metadata = _task_metadata(kb, task, board=board)
    context = TaskRoutingContext.from_task(task, board=board, metadata=metadata)
    return route_task_model(context, model_set=model_set, user_config=user_config)


def _task_metadata(kb: Any, task: Any, *, board: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    task_id = str(getattr(task, "id", "") or "")
    if not task_id:
        return metadata
    try:
        with _board_scope(kb, board):
            with kb.connect_closing() as conn:
                try:
                    metadata["parents"] = kb.parent_ids(conn, task_id)
                    metadata["children"] = kb.child_ids(conn, task_id)
                except Exception:
                    pass
                try:
                    rows = conn.execute(
                        "SELECT outcome, status FROM task_runs WHERE task_id = ? ORDER BY started_at DESC LIMIT 20",
                        (task_id,),
                    ).fetchall()
                    metadata["prior_attempts"] = len(rows)
                    metadata["prior_failures"] = sum(
                        1
                        for row in rows
                        if str(row["outcome"] or row["status"] or "").lower()
                        in {"failed", "blocked", "timed_out", "crashed", "spawn_failed", "stale"}
                    )
                except Exception:
                    pass
    except Exception:
        return metadata
    return metadata


def _record_route(kb: Any, task: Any, decision: Any, *, board: str | None = None) -> None:
    task_id = str(getattr(task, "id", "") or "")
    run_id = getattr(task, "current_run_id", None)
    if not task_id:
        return
    route = decision.metadata()[ROUTE_METADATA_KEY]
    compact_reason = "; ".join(route.get("reasons") or [])[:300]
    try:
        with _board_scope(kb, board):
            with kb.connect_closing() as conn:
                with kb.write_txn(conn):
                    if run_id is not None:
                        row = conn.execute(
                            "SELECT metadata FROM task_runs WHERE id = ?",
                            (int(run_id),),
                        ).fetchone()
                        current = {}
                        if row and row["metadata"]:
                            try:
                                parsed = json.loads(row["metadata"])
                                current = parsed if isinstance(parsed, dict) else {}
                            except Exception:
                                current = {}
                        current[ROUTE_METADATA_KEY] = route
                        conn.execute(
                            "UPDATE task_runs SET metadata = ? WHERE id = ?",
                            (json.dumps(current, sort_keys=True), int(run_id)),
                        )
                    kb._append_event(
                        conn,
                        task_id,
                        "model_routed",
                        {
                            "provider": route.get("provider"),
                            "model": route.get("model"),
                            "tier": route.get("tier"),
                            "source": route.get("source"),
                            "reason": compact_reason,
                            "preflight_category": (route.get("preflight") or {}).get("category"),
                        },
                        run_id=run_id,
                    )
    except Exception as exc:
        log.debug("Agency model route metadata write failed for %s: %s", task_id, exc)


def _block_for_provider_health(
    kb: Any, task: Any, decision: Any, *, board: str | None = None
) -> None:
    task_id = str(getattr(task, "id", "") or "")
    if not task_id:
        return
    try:
        with _board_scope(kb, board):
            with kb.connect_closing() as conn:
                kb.block_task(
                    conn,
                    task_id,
                    reason=decision.block_reason,
                    kind="capability",
                    expected_run_id=getattr(task, "current_run_id", None),
                )
    except Exception as exc:
        log.debug("Agency provider-health block failed for %s: %s", task_id, exc)


class _NullContext:
    def __enter__(self):
        return None

    def __exit__(self, *_: object) -> bool:
        return False


def _board_scope(kb: Any, board: str | None):
    if board and hasattr(kb, "scoped_current_board"):
        return kb.scoped_current_board(board)
    return _NullContext()
