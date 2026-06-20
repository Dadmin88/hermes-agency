"""Hermes tool stubs for AgentAnycast P2P communication."""

from __future__ import annotations

import importlib.util
import json
from typing import Any

from .card_builder import build_card, card_to_dict
from .node_manager import manager

TOOLSET = "agentanycast"


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def check_agentanycast_available() -> bool:
    """Return True when the AgentAnycast Python SDK is importable."""

    return importlib.util.find_spec("agentanycast") is not None



def a2a_info(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Return local AgentAnycast plugin/SDK status and generated AgentCard."""

    card = None
    error = None
    if check_agentanycast_available():
        try:
            card = card_to_dict(build_card())
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

    return _json(
        {
            "ok": error is None,
            "sdk_available": check_agentanycast_available(),
            "card": card,
            "card_error": error,
            "node": manager.info(),
        }
    )


def a2a_start_node(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Start this profile's AgentAnycast node."""

    try:
        state = manager.start_sync()
        return _json({"ok": state.error is None and state.started, "node": state.as_dict()})
    except Exception as exc:
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}", "node": manager.info()})


def a2a_stop_node(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Stop this profile's AgentAnycast node."""

    try:
        state = manager.stop_sync()
        return _json({"ok": state.error is None, "node": state.as_dict()})
    except Exception as exc:
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}", "node": manager.info()})


def a2a_list_peers(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Return currently connected peers when the node is running."""

    try:
        peers = manager.list_peers_sync()
        return _json({"ok": True, "peers": peers, "node": manager.info()})
    except Exception as exc:
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}", "node": manager.info()})


def a2a_discover(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Discover peers offering a skill via AgentAnycast routing."""

    args = args or {}
    skill = str(args.get("skill") or "").strip()
    if not skill:
        return _json({"ok": False, "error": "skill is required", "node": manager.info()})
    tags = args.get("tags") or None
    if tags is not None and not isinstance(tags, dict):
        return _json({"ok": False, "error": "tags must be an object", "node": manager.info()})
    limit = int(args.get("limit") or 0)
    try:
        agents = manager.discover_sync(skill=skill, tags=tags, limit=limit)
        return _json({"ok": True, "agents": agents, "node": manager.info()})
    except Exception as exc:
        return _json(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "requested_skill": skill,
                "tags": tags or {},
                "node": manager.info(),
            }
        )


def a2a_send(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Send a task to an AgentAnycast peer or skill."""

    args = args or {}
    message = str(args.get("message") or "").strip()
    peer_id = str(args.get("peer_id") or "").strip() or None
    skill = str(args.get("skill") or "").strip() or None
    wait_seconds = float(args.get("wait_seconds") or 0)
    metadata = args.get("metadata") or None
    if not message:
        return _json({"ok": False, "error": "message is required", "node": manager.info()})
    if sum(bool(item) for item in (peer_id, skill)) != 1:
        return _json({"ok": False, "error": "exactly one of peer_id or skill is required", "node": manager.info()})
    if metadata is not None and not isinstance(metadata, dict):
        return _json({"ok": False, "error": "metadata must be an object", "node": manager.info()})
    try:
        task = manager.send_task_sync(
            message=message,
            peer_id=peer_id,
            skill=skill,
            wait_seconds=wait_seconds,
            metadata=metadata,
        )
        return _json({"ok": True, "task_id": task.get("task_id"), "task": task, "node": manager.info()})
    except Exception as exc:
        return _json(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "peer_id": peer_id,
                "skill": skill,
                "message_present": bool(message),
                "node": manager.info(),
            }
        )


def a2a_status(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Return the latest tracked status for an AgentAnycast task."""

    args = args or {}
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return _json({"ok": False, "error": "task_id is required", "node": manager.info()})
    try:
        task = manager.task_status_sync(task_id)
        if task is None:
            return _json({"ok": False, "error": f"unknown task_id: {task_id}", "task_id": task_id, "node": manager.info()})
        return _json({"ok": True, "task_id": task_id, "task": task, "node": manager.info()})
    except Exception as exc:
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}", "task_id": task_id, "node": manager.info()})


def a2a_inbox(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Return recent incoming AgentAnycast task queue/history records."""

    args = args or {}
    limit = int(args.get("limit") or 20)
    try:
        tasks = manager.incoming_tasks_sync(limit=limit)
        return _json({"ok": True, "tasks": tasks, "node": manager.info()})
    except Exception as exc:
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}", "node": manager.info()})


A2A_INFO_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_info",
        "description": "Show this Hermes profile's AgentAnycast plugin, SDK, config, and node status.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

A2A_START_NODE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_start_node",
        "description": "Start this Hermes profile's AgentAnycast P2P node and begin listening for incoming tasks.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

A2A_STOP_NODE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_stop_node",
        "description": "Stop this Hermes profile's AgentAnycast P2P node and daemon cleanly.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

A2A_LIST_PEERS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_list_peers",
        "description": "List AgentAnycast peers currently connected to this profile's node.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

A2A_DISCOVER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_discover",
        "description": "Discover AgentAnycast peers offering a skill via anycast routing. Starts the local node if needed.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill": {"type": "string", "description": "Skill ID to discover."},
                "tags": {"type": "object", "description": "Optional tag filters."},
                "limit": {"type": "integer", "description": "Maximum results; 0 means server default."},
            },
            "required": ["skill"],
            "additionalProperties": False,
        },
    },
}

A2A_SEND_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_send",
        "description": "Send a task to an AgentAnycast peer_id or skill. Starts the local node if needed and returns a task_id plus initial/latest status.",
        "parameters": {
            "type": "object",
            "properties": {
                "peer_id": {"type": "string", "description": "Target peer ID for direct addressing. Mutually exclusive with skill."},
                "skill": {"type": "string", "description": "Target skill for anycast routing. Mutually exclusive with peer_id."},
                "message": {"type": "string", "description": "Task message text."},
                "wait_seconds": {"type": "number", "description": "Optional seconds to wait for completion before returning."},
                "metadata": {"type": "object", "description": "Optional string metadata to attach to the task."},
            },
            "required": ["message"],
            "additionalProperties": False,
        },
    },
}

A2A_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_status",
        "description": "Check latest locally tracked status and artifacts for a task sent by a2a_send.",
        "parameters": {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "Task ID."}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
}

A2A_INBOX_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_inbox",
        "description": "List recent incoming AgentAnycast tasks queued/processed by this profile's safe stub handler.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum records to return; default 20."}
            },
            "additionalProperties": False,
        },
    },
}

TOOLS = (
    ("a2a_discover", A2A_DISCOVER_SCHEMA, a2a_discover, "🔎"),
    ("a2a_send", A2A_SEND_SCHEMA, a2a_send, "📨"),
    ("a2a_status", A2A_STATUS_SCHEMA, a2a_status, "📋"),
    ("a2a_inbox", A2A_INBOX_SCHEMA, a2a_inbox, "📥"),
    ("a2a_start_node", A2A_START_NODE_SCHEMA, a2a_start_node, "▶️"),
    ("a2a_stop_node", A2A_STOP_NODE_SCHEMA, a2a_stop_node, "⏹️"),
    ("a2a_list_peers", A2A_LIST_PEERS_SCHEMA, a2a_list_peers, "🧭"),
    ("a2a_info", A2A_INFO_SCHEMA, a2a_info, "🛰️"),
)
