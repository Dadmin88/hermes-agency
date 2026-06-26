"""Orchestrator helper for queueing tasks into the GPT bridge inbox."""

from __future__ import annotations

import json
from typing import Any

from .config import current_profile_name
from .gpt_bridge import enqueue_task
from .kanban_bridge import get_task as kanban_get_task
from .kanban_bridge import update_task as kanban_update_task


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def _clean(value: Any, *, max_len: int | None = None) -> str:
    text = " ".join(str(value or "").split()).strip()
    if max_len and len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def orch_escalate_to_gpt(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Queue a task for pull-based ChatGPT completion through the GPT bridge inbox."""

    args = args or {}
    task_description = _clean(args.get("task_description") or args.get("task") or "")
    reason = _clean(args.get("reason") or "")
    expected_output = _clean(args.get("expected_output") or args.get("output") or "")
    urgency = _clean(args.get("urgency") or "normal") or "normal"
    source_task_id = _clean(args.get("task_id") or "") or None

    if not task_description and source_task_id:
        existing = kanban_get_task(source_task_id)
        if existing.get("available") and existing.get("ok"):
            task = existing.get("task") or {}
            task_description = str(task.get("title") or task.get("body") or source_task_id)

    if not task_description:
        return _json({"ok": False, "error": "task_description is required"})
    if not reason:
        reason = "Escalated to ChatGPT bridge for senior/fixer assistance."

    queued = enqueue_task(
        task_description,
        reason=reason,
        expected_output=expected_output,
        urgency=urgency,
        source_profile=current_profile_name(),
        source_task_id=source_task_id,
        kanban_task_id=source_task_id,
        metadata={
            "agency_kind": "gpt_bridge_escalation",
            "caller": "orch_escalate_to_gpt",
        },
    )

    if source_task_id:
        kanban_update_task(
            source_task_id, status="blocked", error=f"Queued for GPT bridge: {reason}"
        )
    return _json(queued)


ORCH_ESCALATE_TO_GPT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "orch_escalate_to_gpt",
        "description": "Queue a blocked or high-leverage task into the pull-based ChatGPT bridge inbox for human/ChatGPT completion.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Task for ChatGPT to complete.",
                },
                "task_id": {
                    "type": "string",
                    "description": "Optional existing Kanban/local task ID.",
                },
                "reason": {"type": "string", "description": "Why GPT bridge help is needed."},
                "expected_output": {
                    "type": "string",
                    "description": "Expected deliverable or result format.",
                },
                "urgency": {"type": "string", "description": "low, normal, high, urgent."},
            },
            "required": ["task_description"],
            "additionalProperties": False,
        },
    },
}
