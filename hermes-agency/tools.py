"""Hermes tool stubs for Hermes Agency P2P communication."""

from __future__ import annotations

import copy
import importlib.util
import json
import logging
import os
from collections.abc import Callable
from typing import Any

from .autonomous_tools import AUTONOMOUS_TOOLS
from .card_builder import build_card, card_to_dict
from .node_manager import manager

TOOLSET = "agency"
logger = logging.getLogger(__name__)


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def check_agency_available() -> bool:
    """Return True when the Hermes Agency Python SDK is importable."""

    return importlib.util.find_spec("agentanycast") is not None


def _compact_node() -> dict[str, Any]:
    """Return small node health for high-traffic tool responses."""

    compact_info = getattr(manager, "compact_info", None)
    if callable(compact_info):
        result = compact_info()
        return result if isinstance(result, dict) else {"raw": result}
    return manager.info()


def _compact_agent(agent: dict[str, Any], requested_skill: str) -> dict[str, Any]:
    """Return discovery result without the full skill/card payload."""

    skills = agent.get("skills") if isinstance(agent, dict) else []
    skills = skills if isinstance(skills, list) else []
    needle = requested_skill.strip().lower()
    matching_skills = []
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        skill_id = str(skill.get("skill_id") or "")
        description = str(skill.get("description") or "")
        haystack = f"{skill_id}\n{description}".lower()
        if not needle or needle in haystack:
            matching_skills.append({"skill_id": skill_id, "description": description})
        if len(matching_skills) >= 5:
            break
    return {
        "peer_id": agent.get("peer_id"),
        "agent_name": agent.get("agent_name"),
        "agent_description": agent.get("agent_description"),
        "skill_count": len(skills),
        "matching_skills": matching_skills,
    }


def _compact_agents(agents: list[dict[str, Any]], requested_skill: str) -> list[dict[str, Any]]:
    return [_compact_agent(agent, requested_skill) for agent in agents if isinstance(agent, dict)]


def a2a_info(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Return local Hermes Agency plugin/SDK status and generated AgentCard."""

    args = args or {}
    sdk_available = check_agency_available()
    if bool(args.get("compact")):
        node = manager.compact_info()
        return _json(
            {
                "ok": bool(node.get("ok")) and sdk_available,
                "sdk_available": sdk_available,
                "compact": True,
                "node": node,
            }
        )

    card = None
    error = None
    if sdk_available:
        try:
            card = card_to_dict(build_card())
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

    return _json(
        {
            "ok": error is None,
            "sdk_available": sdk_available,
            "card": card,
            "card_error": error,
            "node": manager.info(),
        }
    )


def a2a_start_node(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Start this profile's Hermes Agency node."""

    try:
        state = manager.start_sync()
        return _json({"ok": state.error is None and state.started, "node": state.as_dict()})
    except Exception as exc:
        return _json(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}", "node": _compact_node()}
        )


def a2a_stop_node(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Stop this profile's Hermes Agency node."""

    try:
        state = manager.stop_sync()
        return _json({"ok": state.error is None, "node": state.as_dict()})
    except Exception as exc:
        return _json(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}", "node": _compact_node()}
        )


def a2a_list_peers(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Return currently connected peers when the node is running."""

    try:
        peers = manager.list_peers_sync()
        return _json({"ok": True, "peers": peers, "node": _compact_node()})
    except Exception as exc:
        return _json(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}", "node": _compact_node()}
        )


def a2a_discover(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Discover peers offering a skill via Hermes Agency routing."""

    args = args or {}
    skill = str(args.get("skill") or "").strip()
    if not skill:
        return _json({"ok": False, "error": "skill is required", "node": _compact_node()})
    tags = args.get("tags") or None
    if tags is not None and not isinstance(tags, dict):
        return _json({"ok": False, "error": "tags must be an object", "node": _compact_node()})
    limit = int(args.get("limit") or 0)
    include_skills = bool(args.get("include_skills"))
    try:
        agents = manager.discover_sync(skill=skill, tags=tags, limit=limit)
        response_agents = agents if include_skills else _compact_agents(agents, skill)
        return _json({"ok": True, "agents": response_agents, "node": _compact_node()})
    except Exception as exc:
        return _json(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "requested_skill": skill,
                "tags": tags or {},
                "node": _compact_node(),
            }
        )


def a2a_send(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Send a task to an Hermes Agency peer or skill."""

    args = args or {}
    message = str(args.get("message") or "").strip()
    peer_id = str(args.get("peer_id") or "").strip() or None
    skill = str(args.get("skill") or "").strip() or None
    context_id = str(args.get("context_id") or "").strip() or None
    wait_seconds = float(args.get("wait_seconds") or 0)
    metadata = args.get("metadata") or None
    if not message:
        return _json({"ok": False, "error": "message is required", "node": _compact_node()})
    if sum(bool(item) for item in (peer_id, skill)) != 1:
        return _json(
            {
                "ok": False,
                "error": "exactly one of peer_id or skill is required",
                "node": _compact_node(),
            }
        )
    if metadata is not None and not isinstance(metadata, dict):
        return _json({"ok": False, "error": "metadata must be an object", "node": _compact_node()})
    try:
        conversation_context = {
            "summary": str(kwargs.get("user_task") or "").strip(),
            "sender": kwargs.get("profile") or "",
            "channel": kwargs.get("session_id") or "",
        }
        task = manager.send_task_sync(
            message=message,
            peer_id=peer_id,
            skill=skill,
            wait_seconds=wait_seconds,
            metadata=metadata,
            conversation_context=conversation_context,
            context_id=context_id,
        )
        return _json(
            {"ok": True, "task_id": task.get("task_id"), "task": task, "node": _compact_node()}
        )
    except Exception as exc:
        return _json(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "peer_id": peer_id,
                "skill": skill,
                "message_present": bool(message),
                "node": _compact_node(),
            }
        )


def a2a_status(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Return the latest tracked status for an Hermes Agency task."""

    args = args or {}
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return _json({"ok": False, "error": "task_id is required", "node": _compact_node()})
    try:
        task = manager.task_status_sync(task_id)
        if task is None:
            return _json(
                {
                    "ok": False,
                    "error": f"unknown task_id: {task_id}",
                    "task_id": task_id,
                    "node": _compact_node(),
                }
            )
        return _json({"ok": True, "task_id": task_id, "task": task, "node": _compact_node()})
    except Exception as exc:
        return _json(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "task_id": task_id,
                "node": _compact_node(),
            }
        )


def a2a_inbox(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Return recent incoming Hermes Agency task queue/history records."""

    args = args or {}
    limit = int(args.get("limit") or 20)
    try:
        tasks = manager.incoming_tasks_sync(limit=limit)
        return _json({"ok": True, "tasks": tasks, "node": _compact_node()})
    except Exception as exc:
        return _json(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}", "node": _compact_node()}
        )


Handler = Callable[..., str]


def _deprecation_verbose(args: dict[str, Any] | None, kwargs: dict[str, Any]) -> bool:
    if isinstance(args, dict) and bool(args.get("verbose")):
        return True
    if bool(kwargs.get("verbose")):
        return True
    return str(os.getenv("HERMES_AGENCY_VERBOSE_DEPRECATIONS", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    } or str(os.getenv("HERMES_AGENCY_DEV_MODE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "dev",
    }


def _deprecated_alias(old_name: str, new_name: str, handler: Handler) -> Handler:
    def wrapper(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
        if _deprecation_verbose(args, kwargs):
            logger.warning("%s is deprecated; use %s", old_name, new_name)
        return handler(args, **kwargs)

    wrapper.__name__ = old_name
    wrapper.__doc__ = f"Deprecated alias for {new_name}."
    return wrapper


def _schema_with_name(
    schema: dict[str, Any], name: str, description: str | None = None
) -> dict[str, Any]:
    clone = copy.deepcopy(schema)
    clone["function"]["name"] = name
    if description is not None:
        clone["function"]["description"] = description
    return clone


_a2a_info_impl = a2a_info
_a2a_start_node_impl = a2a_start_node
_a2a_stop_node_impl = a2a_stop_node
_a2a_list_peers_impl = a2a_list_peers
_a2a_discover_impl = a2a_discover
_a2a_send_impl = a2a_send
_a2a_status_impl = a2a_status
_a2a_inbox_impl = a2a_inbox

agency_info = _a2a_info_impl
agency_start_node = _a2a_start_node_impl
agency_stop_node = _a2a_stop_node_impl
agency_list_peers = _a2a_list_peers_impl
agency_discover = _a2a_discover_impl
agency_send = _a2a_send_impl
agency_status = _a2a_status_impl
agency_inbox = _a2a_inbox_impl

a2a_info = _deprecated_alias("a2a_info", "agency_info", _a2a_info_impl)
a2a_start_node = _deprecated_alias("a2a_start_node", "agency_start_node", _a2a_start_node_impl)
a2a_stop_node = _deprecated_alias("a2a_stop_node", "agency_stop_node", _a2a_stop_node_impl)
a2a_list_peers = _deprecated_alias("a2a_list_peers", "agency_list_peers", _a2a_list_peers_impl)
a2a_discover = _deprecated_alias("a2a_discover", "agency_discover", _a2a_discover_impl)
a2a_send = _deprecated_alias("a2a_send", "agency_send", _a2a_send_impl)
a2a_status = _deprecated_alias("a2a_status", "agency_status", _a2a_status_impl)
a2a_inbox = _deprecated_alias("a2a_inbox", "agency_inbox", _a2a_inbox_impl)


A2A_INFO_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_info",
        "description": "Show this Hermes profile's Hermes Agency plugin, SDK, config, and node status.",
        "parameters": {
            "type": "object",
            "properties": {
                "compact": {
                    "type": "boolean",
                    "description": "Return a small health-only payload without card, skills, or team context.",
                }
            },
            "additionalProperties": False,
        },
    },
}

A2A_START_NODE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_start_node",
        "description": "Start this Hermes profile's Hermes Agency P2P node and begin listening for incoming tasks.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

A2A_STOP_NODE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_stop_node",
        "description": "Stop this Hermes profile's Hermes Agency P2P node and daemon cleanly.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

A2A_LIST_PEERS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_list_peers",
        "description": "List Hermes Agency peers currently connected to this profile's node.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

A2A_DISCOVER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_discover",
        "description": "Discover Hermes Agency peers offering a skill via anycast routing. Starts the local node if needed.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill": {"type": "string", "description": "Skill ID to discover."},
                "tags": {"type": "object", "description": "Optional tag filters."},
                "limit": {
                    "type": "integer",
                    "description": "Maximum results; 0 means server default.",
                },
                "include_skills": {
                    "type": "boolean",
                    "description": "Include full per-agent skill lists. Defaults to false to keep tool output compact.",
                },
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
        "description": "Send a task to an Hermes Agency peer_id or skill. Starts the local node if needed and returns a task_id plus initial/latest status.",
        "parameters": {
            "type": "object",
            "properties": {
                "peer_id": {
                    "type": "string",
                    "description": "Target peer ID for direct addressing. Mutually exclusive with skill.",
                },
                "skill": {
                    "type": "string",
                    "description": "Target skill for anycast routing. Mutually exclusive with peer_id.",
                },
                "message": {"type": "string", "description": "Task message text."},
                "context_id": {
                    "type": "string",
                    "description": "Optional conversation/thread id for multi-turn continuity.",
                },
                "wait_seconds": {
                    "type": "number",
                    "description": "Optional seconds to wait for completion before returning.",
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional string metadata to attach to the task.",
                },
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
        "description": "List recent incoming Hermes Agency tasks queued/processed by this profile's safe stub handler.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum records to return; default 20.",
                }
            },
            "additionalProperties": False,
        },
    },
}

AGENCY_TOOLS = (
    (
        "agency_discover",
        _schema_with_name(
            A2A_DISCOVER_SCHEMA,
            "agency_discover",
            "Discover Hermes Agency peers offering a skill via anycast routing. Starts the local node if needed.",
        ),
        agency_discover,
        "🔎",
    ),
    (
        "agency_send",
        _schema_with_name(
            A2A_SEND_SCHEMA,
            "agency_send",
            "Send a task to a Hermes Agency peer_id or skill. Starts the local node if needed and returns a task_id plus initial/latest status.",
        ),
        agency_send,
        "📨",
    ),
    (
        "agency_status",
        _schema_with_name(
            A2A_STATUS_SCHEMA,
            "agency_status",
            "Check latest locally tracked status and artifacts for a task sent by agency_send.",
        ),
        agency_status,
        "📋",
    ),
    (
        "agency_inbox",
        _schema_with_name(
            A2A_INBOX_SCHEMA,
            "agency_inbox",
            "List recent incoming Hermes Agency tasks queued/processed by this profile's safe stub handler.",
        ),
        agency_inbox,
        "📥",
    ),
    (
        "agency_start_node",
        _schema_with_name(
            A2A_START_NODE_SCHEMA,
            "agency_start_node",
            "Start this Hermes profile's Hermes Agency P2P node and begin listening for incoming tasks.",
        ),
        agency_start_node,
        "▶️",
    ),
    (
        "agency_stop_node",
        _schema_with_name(
            A2A_STOP_NODE_SCHEMA,
            "agency_stop_node",
            "Stop this Hermes profile's Hermes Agency P2P node and daemon cleanly.",
        ),
        agency_stop_node,
        "⏹️",
    ),
    (
        "agency_list_peers",
        _schema_with_name(
            A2A_LIST_PEERS_SCHEMA,
            "agency_list_peers",
            "List Hermes Agency peers currently connected to this profile's node.",
        ),
        agency_list_peers,
        "🧭",
    ),
    (
        "agency_info",
        _schema_with_name(
            A2A_INFO_SCHEMA,
            "agency_info",
            "Show this Hermes profile's Hermes Agency plugin, SDK, config, and node status.",
        ),
        agency_info,
        "🛰️",
    ),
)

A2A_ALIAS_TOOLS = (
    (
        "a2a_discover",
        _schema_with_name(
            A2A_DISCOVER_SCHEMA,
            "a2a_discover",
            "Deprecated alias for agency_discover; kept for A2A protocol compatibility.",
        ),
        a2a_discover,
        "🔎",
    ),
    (
        "a2a_send",
        _schema_with_name(
            A2A_SEND_SCHEMA,
            "a2a_send",
            "Deprecated alias for agency_send; kept for A2A protocol compatibility.",
        ),
        a2a_send,
        "📨",
    ),
    (
        "a2a_status",
        _schema_with_name(
            A2A_STATUS_SCHEMA,
            "a2a_status",
            "Deprecated alias for agency_status; kept for A2A protocol compatibility.",
        ),
        a2a_status,
        "📋",
    ),
    (
        "a2a_inbox",
        _schema_with_name(
            A2A_INBOX_SCHEMA,
            "a2a_inbox",
            "Deprecated alias for agency_inbox; kept for A2A protocol compatibility.",
        ),
        a2a_inbox,
        "📥",
    ),
    (
        "a2a_start_node",
        _schema_with_name(
            A2A_START_NODE_SCHEMA,
            "a2a_start_node",
            "Deprecated alias for agency_start_node; kept for A2A protocol compatibility.",
        ),
        a2a_start_node,
        "▶️",
    ),
    (
        "a2a_stop_node",
        _schema_with_name(
            A2A_STOP_NODE_SCHEMA,
            "a2a_stop_node",
            "Deprecated alias for agency_stop_node; kept for A2A protocol compatibility.",
        ),
        a2a_stop_node,
        "⏹️",
    ),
    (
        "a2a_list_peers",
        _schema_with_name(
            A2A_LIST_PEERS_SCHEMA,
            "a2a_list_peers",
            "Deprecated alias for agency_list_peers; kept for A2A protocol compatibility.",
        ),
        a2a_list_peers,
        "🧭",
    ),
    (
        "a2a_info",
        _schema_with_name(
            A2A_INFO_SCHEMA,
            "a2a_info",
            "Deprecated alias for agency_info; kept for A2A protocol compatibility.",
        ),
        a2a_info,
        "🛰️",
    ),
)


def pool_roster(args: dict[str, Any] | None = None, **_: Any) -> str:
    from .pool.roster import load_roster

    args = args or {}
    roster = load_roster()
    profiles = roster["profiles"]
    query = args.get("query", "").lower()
    if query:
        profiles = [
            p
            for p in profiles
            if query in p["name"].lower()
            or any(query in s.lower() for s in p.get("skills", []))
            or query in p.get("description", "").lower()
        ]
    if args.get("online_only"):
        profiles = [p for p in profiles if p["online"]]
    lines = [f"Pool roster: {roster['online']}/{roster['total']} online"]
    for p in profiles:
        status = "ONLINE" if p["online"] else "OFFLINE"
        skills = ", ".join(p.get("skills", [])[:5])
        cnt = p.get("skill_count", 0)
        if cnt > 5:
            skills += f" +{cnt - 5}"
        line = f"  {p['name']} — skills: {skills} [{status}]"
        if p.get("online") and p.get("peer_id"):
            line += f" peer_id: {p['peer_id']}"
        elif p.get("last_seen"):
            line += f" last_seen: {p['last_seen']}"
        lines.append(line)
    return "\n".join(lines)


def pool_wake(args: dict[str, Any] | None = None, **_: Any) -> str:
    from .pool.tools import pool_wake as _pool_wake

    args = args or {}
    name = args.get("name", "")
    if not name:
        return "Error: name is required"
    return _pool_wake(name)


def pool_sleep(args: dict[str, Any] | None = None, **_: Any) -> str:
    from .pool.tools import pool_sleep as _pool_sleep

    args = args or {}
    name = args.get("name", "")
    if not name:
        return "Error: name is required"
    return _pool_sleep(name)


def pool_send(args: dict[str, Any] | None = None, **_: Any) -> str:
    from .pool.tools import pool_send as _pool_send

    args = args or {}
    name = args.get("name", "")
    message = args.get("message", "")
    if not name or not message:
        return "Error: name and message are required"
    return _pool_send(name, message)


def _pool_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


POOL_TOOLS = (
    (
        "agency_roster",
        _pool_schema(
            "agency_roster",
            "Show the agency roster — all agents, who's online, skills, peer_ids. Filter by query.",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": []},
        ),
        pool_roster,
        "📋",
    ),
    (
        "agency_wake",
        _pool_schema(
            "agency_wake",
            "Wake an agency agent — start its daemon and register it on the network.",
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        ),
        pool_wake,
        "⚡",
    ),
    (
        "agency_sleep",
        _pool_schema(
            "agency_sleep",
            "Sleep an agency agent — stop its daemon to free resources.",
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        ),
        pool_sleep,
        "💤",
    ),
    (
        "agency_pool_send",
        _pool_schema(
            "agency_pool_send",
            "Send work to an agency agent. Auto-wakes if offline and persistently queues if wake/send fails.",
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "message": {"type": "string"}},
                "required": ["name", "message"],
            },
        ),
        pool_send,
        "📬",
    ),
)


TOOLS = (
    *AGENCY_TOOLS,
    *AUTONOMOUS_TOOLS,
    *A2A_ALIAS_TOOLS,
    *POOL_TOOLS,
)
