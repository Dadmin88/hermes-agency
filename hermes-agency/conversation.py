"""Conversation continuity helpers for Hermes Agency A2A tasks."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .kanban_bridge import list_tasks as kanban_list_tasks

DEFAULT_CONVERSATION_TTL_SECONDS = 3600
DEFAULT_CONVERSATION_MAX_TURNS = 20
_METADATA_BLOCK_RE = re.compile(r"Hermes Agency metadata:\s*```json\s*(.*?)\s*```", re.S)


def build_conversation_history(
    context_id: str,
    profile_home: str | Path | None = None,
    *,
    max_turns: int = DEFAULT_CONVERSATION_MAX_TURNS,
    ttl: int | float = DEFAULT_CONVERSATION_TTL_SECONDS,
) -> list[dict[str, Any]]:
    """Return recent completed turns for a conversation context id.

    The current implementation reads the profile's Kanban-backed A2A records.
    ``profile_home`` is accepted for the public API and future file-backed state,
    but Kanban already scopes itself to the active Hermes profile.
    """

    clean_context_id = str(context_id or "").strip()
    if not clean_context_id:
        return []

    try:
        result = kanban_list_tasks({"limit": 200, "include_archived": True, "tenant": "*"})
    except Exception:
        return []
    if not result.get("available") or not result.get("ok"):
        return []

    now = time.time()
    ttl_seconds = max(0.0, float(ttl or 0))
    turns: list[dict[str, Any]] = []
    for task in result.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        created_at = _float_or_none(task.get("created_at"))
        if ttl_seconds and created_at is not None and now - created_at > ttl_seconds:
            continue
        metadata = _metadata_from_task(task)
        if str(metadata.get("context_id") or "").strip() != clean_context_id:
            continue
        user_text = _turn_user_text(task, metadata)
        agent_text = _turn_agent_text(task)
        if not user_text and not agent_text:
            continue
        turns.append(
            {
                "task_id": str(task.get("id") or task.get("task_id") or ""),
                "created_at": created_at or 0,
                "user": user_text,
                "agent": agent_text,
            }
        )

    turns.sort(key=lambda item: (float(item.get("created_at") or 0), str(item.get("task_id") or "")))
    return turns[-max(1, int(max_turns or DEFAULT_CONVERSATION_MAX_TURNS)):]


def build_conversation_context(
    context_id: str,
    max_turns: int = 10,
    *,
    ttl: int | float = DEFAULT_CONVERSATION_TTL_SECONDS,
    profile_home: str | Path | None = None,
    local_history: list[dict[str, Any]] | None = None,
) -> str:
    """Build a formatted conversation history for prompts."""

    history = list(local_history or [])
    if history and ttl:
        now = time.time()
        ttl_seconds = max(0.0, float(ttl or 0))
        history = [
            item
            for item in history
            if now - float(item.get("created_at") or now) <= ttl_seconds
        ]
    if not history:
        history = build_conversation_history(context_id, profile_home, max_turns=max_turns, ttl=ttl)
    return format_conversation_history(history[-max(1, int(max_turns or 10)):])


def format_conversation_history(history: list[dict[str, Any]] | None) -> str:
    """Format previous turns for receiver-side delegation/subprocess prompts."""

    turns = [item for item in (history or []) if isinstance(item, dict)]
    if not turns:
        return ""
    lines = ["Previous conversation:"]
    for idx, item in enumerate(turns, start=1):
        user = _squash(item.get("user") or item.get("message") or item.get("request"))
        agent = _squash(item.get("agent") or item.get("response") or item.get("result"))
        lines.extend(["", f"Turn {idx}:"])
        if user:
            lines.append(f'You: "{user}"')
        if agent:
            lines.append(f'Agent: "{agent}"')
    return "\n".join(lines).strip()


def _metadata_from_task(task: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    raw_metadata = task.get("metadata")
    if isinstance(raw_metadata, dict):
        metadata.update(raw_metadata)
    body = str(task.get("body") or "")
    match = _METADATA_BLOCK_RE.search(body)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                metadata.update(parsed)
        except Exception:
            pass
    return metadata


def _turn_user_text(task: dict[str, Any], metadata: dict[str, Any]) -> str:
    for key in ("message", "goal", "request"):
        value = metadata.get(key)
        if value:
            return _squash(value)
    body = str(task.get("body") or "")
    packet_goal = _goal_from_context_packet(body)
    if packet_goal:
        return packet_goal
    return _squash(body.split("Hermes Agency metadata:", 1)[0])


def _turn_agent_text(task: dict[str, Any]) -> str:
    for key in ("result", "summary"):
        value = task.get(key)
        if value:
            return _squash(value)
    return ""


def _goal_from_context_packet(text: str) -> str:
    marker = "AGENTANYCAST_CONTEXT_PACKET "
    if marker not in text:
        return ""
    raw = text.split(marker, 1)[1].strip()
    try:
        packet = json.loads(raw)
    except Exception:
        return ""
    if isinstance(packet, dict):
        return _squash(packet.get("goal"))
    return ""


def _squash(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
