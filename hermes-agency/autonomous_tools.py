"""Hermes tool handlers for Hermes Agency Phase 4 autonomous operations."""

from __future__ import annotations

import json
from typing import Any

from .bidding import bidding_summary, build_bid_request, choose_best_bid, record_bid
from .kanban_bridge import assign_task as kanban_assign_task
from .learning import learning_summary, log_routing_correction
from .policy import check_autonomy, policy_summary
from .proactive import create_proactive_task
from .registration import live_registrations
from .workflows import execute_workflow, workflow_templates


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def a2a_registry(args: dict[str, Any] | None = None, **_: Any) -> str:
    args = args or {}
    tenant = args.get("tenant")
    include_stale = bool(args.get("include_stale", False))
    return _json({"ok": True, "registrations": live_registrations(tenant=tenant, include_stale=include_stale)})


def a2a_bid_task(args: dict[str, Any] | None = None, **_: Any) -> str:
    args = args or {}
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return _json({"ok": False, "error": "task_id is required"})
    # Simulation/recording path: caller can provide bids directly for validation
    for bid in args.get("bids") or []:
        if isinstance(bid, dict):
            payload = {"type": "bid", "task_id": task_id, **bid}
            record_bid(payload)
    winner = choose_best_bid(task_id)
    assignment = None
    if winner and args.get("assign_winner", True):
        target = str(winner.get("agent") or "")
        if target and winner.get("status") == "available":
            assignment = kanban_assign_task(task_id, target)
    request = None
    if args.get("title"):
        request = build_bid_request(
            task_id,
            title=str(args.get("title") or ""),
            description=str(args.get("description") or ""),
            skills=[str(skill) for skill in (args.get("skills") or [])],
        )
    return _json({"ok": True, "request": request, "bidding": bidding_summary(task_id), "winner": winner, "assignment": assignment})


def a2a_execute_workflow(args: dict[str, Any] | None = None, **_: Any) -> str:
    args = args or {}
    name = str(args.get("name") or "").strip()
    if not name:
        return _json({"ok": False, "error": "name is required", "templates": workflow_templates()})
    context = args.get("context") if isinstance(args.get("context"), dict) else {}
    return _json(execute_workflow(name, context))


def a2a_create_proactive_task(args: dict[str, Any] | None = None, **_: Any) -> str:
    args = args or {}
    return _json(
        create_proactive_task(
            title=str(args.get("title") or ""),
            description=str(args.get("description") or ""),
            priority=int(args.get("priority") or 0),
            skills=[str(skill) for skill in (args.get("skills") or [])],
            assigned_to=str(args.get("assigned_to") or "").strip() or None,
        )
    )


def a2a_check_autonomy(args: dict[str, Any] | None = None, **_: Any) -> str:
    args = args or {}
    action = str(args.get("action") or "").strip()
    if not action:
        return _json({"ok": False, "error": "action is required", "policy": policy_summary()})
    return _json({"ok": True, "policy": check_autonomy(action, agent=args.get("agent"))})


def a2a_log_routing_correction(args: dict[str, Any] | None = None, **_: Any) -> str:
    args = args or {}
    result = log_routing_correction(
        task_type=str(args.get("task_type") or ""),
        wrong_target=str(args.get("wrong_target") or ""),
        correct_target=str(args.get("correct_target") or ""),
        note=str(args.get("note") or ""),
    )
    return _json({"ok": bool(result.get("ok")), "result": result, "learning": learning_summary(args.get("task_type"))})


A2A_REGISTRY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_registry",
        "description": "List live Hermes Agency self-registration records for the current tenant.",
        "parameters": {
            "type": "object",
            "properties": {
                "tenant": {"type": "string", "description": "Tenant to list; omit for configured tenant, '*' for all."},
                "include_stale": {"type": "boolean", "description": "Include stale/deregistered records."},
            },
            "additionalProperties": False,
        },
    },
}

A2A_BID_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_bid_task",
        "description": "Record/simulate bids for a task and optionally assign the best available bidder.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "skills": {"type": "array", "items": {"type": "string"}},
                "bids": {"type": "array", "items": {"type": "object"}},
                "assign_winner": {"type": "boolean"},
            },
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
}

A2A_EXECUTE_WORKFLOW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_execute_workflow",
        "description": "Start a configured Hermes Agency autonomous workflow by creating dependency-linked Kanban tasks.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "context": {"type": "object"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}

A2A_CREATE_PROACTIVE_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_create_proactive_task",
        "description": "Create a proactive agent-initiated Kanban task when proactive behavior is enabled.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "integer"},
                "skills": {"type": "array", "items": {"type": "string"}},
                "assigned_to": {"type": "string"},
            },
            "required": ["title", "description"],
            "additionalProperties": False,
        },
    },
}

A2A_CHECK_AUTONOMY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_check_autonomy",
        "description": "Check Hermes Agency autonomy policy for an action: autonomous, notify, ask, or never.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "agent": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}

A2A_LOG_ROUTING_CORRECTION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "a2a_log_routing_correction",
        "description": "Log Kyle's correction for a wrong routing decision when learning is enabled.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_type": {"type": "string"},
                "wrong_target": {"type": "string"},
                "correct_target": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["task_type", "wrong_target", "correct_target"],
            "additionalProperties": False,
        },
    },
}

AUTONOMOUS_TOOLS = (
    ("a2a_registry", A2A_REGISTRY_SCHEMA, a2a_registry, "🗂️"),
    ("a2a_bid_task", A2A_BID_TASK_SCHEMA, a2a_bid_task, "🤝"),
    ("a2a_execute_workflow", A2A_EXECUTE_WORKFLOW_SCHEMA, a2a_execute_workflow, "🔁"),
    ("a2a_create_proactive_task", A2A_CREATE_PROACTIVE_TASK_SCHEMA, a2a_create_proactive_task, "⚡"),
    ("a2a_check_autonomy", A2A_CHECK_AUTONOMY_SCHEMA, a2a_check_autonomy, "🛡️"),
    ("a2a_log_routing_correction", A2A_LOG_ROUTING_CORRECTION_SCHEMA, a2a_log_routing_correction, "🧠"),
)
