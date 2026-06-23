"""Orchestrator-layer Hermes tools for Hermes Agency collaboration.

Phase 2 deliberately keeps Kanban as a future integration point. All task
tracking here is process-local fallback state owned by ``node_manager``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .announcements import (
    announce_bid,
    announce_delegate,
    announce_error,
    announce_escalate,
    announce_policy,
    build_blocked_context,
    mark_blocked_hook,
    recent_announcements,
)
from .bidding import choose_best_bid
from .config import AgencyConfig, current_profile_name, get_config, is_current_orchestrator
from .context_packet import build_context_packet
from .kanban_bridge import (
    create_task as kanban_create_task,
)
from .kanban_bridge import (
    get_task as kanban_get_task,
)
from .kanban_bridge import (
    link_tasks as kanban_link_tasks,
)
from .kanban_bridge import (
    list_tasks as kanban_list_tasks,
)
from .kanban_bridge import (
    update_task as kanban_update_task,
)
from .node_manager import manager
from .policy import check_autonomy
from .registration import live_registrations
from .team_context import PeerCapability, filter_team_peers, get_team_state


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def check_orchestrator_enabled() -> bool:
    """Gate orch_* tools to the promoted/config-enabled orchestrator profile."""

    try:
        return is_current_orchestrator(get_config())
    except Exception:
        return False


def _clean(value: Any, *, max_len: int | None = None) -> str:
    text = " ".join(str(value or "").split()).strip()
    if max_len and len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def _normalise(value: Any) -> str:
    return _clean(value).lower()


def _peer_skills(peer: PeerCapability) -> list[str]:
    skills = peer.card_skills or peer.skills
    return [str(skill.get("id") or "").strip() for skill in skills if skill.get("id")]


def _peer_label(peer: PeerCapability) -> str:
    return peer.card_name or peer.name or peer.peer_id


def _visible_team_peers(cfg: AgencyConfig | None = None) -> list[PeerCapability]:
    """Return team peers visible to orchestrator routing/decomposition."""

    active_cfg = cfg or get_config()
    team_state = get_team_state()
    registrations = live_registrations(tenant=active_cfg.team.tenant)
    visible = filter_team_peers(team_state.peers, active_cfg, registrations)
    return list(visible.values())


def _apply_routing_hint(target_or_task: str, cfg: AgencyConfig) -> tuple[str, str | None]:
    """Return a configured routing hint when a rule matches the target/task text."""

    raw = _clean(target_or_task)
    lowered = raw.lower()
    if not cfg.routing:
        return raw, None
    if lowered in cfg.routing:
        return cfg.routing[lowered], lowered
    for key, value in sorted(cfg.routing.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", lowered):
            return value, key
    return raw, None


def _resolve_target(target_agent: str) -> dict[str, Any]:
    """Resolve a peer/profile/skill-ish target into Hermes Agency send_task args."""

    cfg = get_config()
    requested = _clean(target_agent)
    hinted, matched_rule = _apply_routing_hint(requested, cfg)
    target = hinted or requested
    lowered = target.lower()

    if lowered.startswith("peer:"):
        peer_id = target.split(":", 1)[1].strip()
        return {
            "ok": bool(peer_id),
            "peer_id": peer_id,
            "skill": None,
            "label": peer_id,
            "matched_rule": matched_rule,
        }
    if lowered.startswith("skill:"):
        skill = target.split(":", 1)[1].strip()
        return {
            "ok": bool(skill),
            "peer_id": None,
            "skill": skill,
            "label": skill,
            "matched_rule": matched_rule,
        }

    visible_peers = _visible_team_peers(cfg)
    for peer in visible_peers:
        label = _peer_label(peer)
        names = {
            peer.peer_id.lower(),
            label.lower(),
            (peer.name or "").lower(),
            (peer.card_name or "").lower(),
        }
        if lowered in names:
            return {
                "ok": True,
                "peer_id": peer.peer_id,
                "skill": None,
                "label": label,
                "matched_rule": matched_rule,
                "peer": peer.as_dict(),
            }

    for peer in visible_peers:
        for skill in _peer_skills(peer):
            if lowered == skill.lower():
                return {
                    "ok": True,
                    "peer_id": None,
                    "skill": skill,
                    "label": skill,
                    "matched_rule": matched_rule,
                    "peer": peer.as_dict(),
                }

    # Allow explicit-looking peer IDs even if discovery cache is cold. Display
    # names and arbitrary short words remain unknown and trigger escalation.
    if target.startswith("12D") or target.startswith("did:key:"):
        return {
            "ok": True,
            "peer_id": target,
            "skill": None,
            "label": target,
            "matched_rule": matched_rule,
        }

    return {
        "ok": False,
        "error": f"unknown target agent or skill: {requested}",
        "requested": requested,
        "hinted_target": target,
        "matched_rule": matched_rule,
    }


def _suggest_assignment(goal: str) -> str:
    """Best-effort advisory assignment from routing rules and capability map."""

    cfg = get_config()
    hinted, _matched = _apply_routing_hint(goal, cfg)
    if hinted != goal:
        return hinted

    lowered = goal.lower()
    visible_peers = _visible_team_peers(cfg)
    for peer in visible_peers:
        for skill in _peer_skills(peer):
            if skill.lower() in lowered:
                return _peer_label(peer)
    for peer in visible_peers:
        name = (_peer_label(peer) or "").lower()
        if name and name in lowered:
            return _peer_label(peer)
    return ""


def _skills_for_assignment(assigned_to: str, resolved: dict[str, Any] | None = None) -> list[str]:
    """Return Kanban skill names for an assignment/target when known."""

    if resolved and resolved.get("skill"):
        return [str(resolved["skill"])]
    peer_data = (resolved or {}).get("peer") if isinstance(resolved, dict) else None
    if isinstance(peer_data, dict):
        skills = [
            str(item.get("id") or "").strip()
            for item in peer_data.get("skills") or []
            if item.get("id")
        ]
        if skills:
            return skills
    lowered = _normalise(assigned_to)
    if not lowered:
        return []
    cfg = get_config()
    for peer in _visible_team_peers(cfg):
        label = _peer_label(peer)
        names = {
            peer.peer_id.lower(),
            label.lower(),
            (peer.name or "").lower(),
            (peer.card_name or "").lower(),
        }
        if lowered in names:
            return _peer_skills(peer)
    return []


def _decomposition_prompt(task_description: str) -> str:
    cfg = get_config()
    visible_peers = _visible_team_peers(cfg)
    team_lines: list[str] = []
    for peer in sorted(visible_peers, key=lambda item: _peer_label(item).lower()):
        skills = ", ".join(_peer_skills(peer)) or "unknown"
        team_lines.append(f"- {_peer_label(peer)}: peer_id={peer.peer_id}; skills={skills}")
    routing = ", ".join(f"{k}->{v}" for k, v in sorted(cfg.routing.items())) or "none"
    return (
        "Decompose the following task for Hermes Agency orchestration. Return JSON only with a "
        "subtasks array. Each subtask must include id, goal, assigned_to (peer_id, profile name, "
        "or skill), dependencies (subtask IDs), and validation. Use routing hints as advisory only.\n\n"
        f"Task: {task_description}\n"
        f"Routing hints: {routing}\n"
        "Team capability map:\n"
        f"{chr(10).join(team_lines) if team_lines else '(no peers discovered)'}"
    )


def _heuristic_subtasks(task_description: str) -> list[dict[str, Any]]:
    """Conservative local fallback decomposition when the model has not supplied one."""

    text = _clean(task_description)
    lowered = text.lower()
    candidates: list[tuple[str, str, str]] = []
    if any(word in lowered for word in ("plan", "design", "spec", "architecture")):
        candidates.append(
            (
                "plan",
                f"Plan the approach for: {text}",
                "Review the plan for clear next steps and risks.",
            )
        )
    if any(word in lowered for word in ("build", "implement", "code", "fix", "write")):
        candidates.append(
            (
                "code",
                f"Implement the code changes for: {text}",
                "Run the relevant tests or compile checks.",
            )
        )
    if any(word in lowered for word in ("test", "validate", "qa", "verify")):
        candidates.append(
            (
                "test",
                f"Validate the implementation for: {text}",
                "Report concrete test/verification results.",
            )
        )
    if any(word in lowered for word in ("deploy", "release", "ship", "rollout")):
        candidates.append(
            (
                "deploy",
                f"Handle deployment/release work for: {text}",
                "Confirm the deployed service is healthy.",
            )
        )
    if any(word in lowered for word in ("doc", "readme", "writeup", "guide")):
        candidates.append(
            (
                "docs",
                f"Document the result for: {text}",
                "Confirm the documentation is accurate and discoverable.",
            )
        )

    if not candidates:
        candidates.append(("task", text, "Verify the task is complete and summarize evidence."))

    subtasks: list[dict[str, Any]] = []
    for idx, (_kind, goal, validation) in enumerate(candidates, start=1):
        subtask_id = f"subtask-{idx}"
        dependencies = [f"subtask-{idx - 1}"] if idx > 1 else []
        assigned_to = get_config().routing.get(_kind) or _suggest_assignment(goal)
        subtasks.append(
            {
                "id": subtask_id,
                "goal": goal,
                "assigned_to": assigned_to,
                "dependencies": dependencies,
                "validation": validation,
            }
        )
    return subtasks


def orch_decompose(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Break a complex task into locally tracked subtasks with dependency hints."""

    args = args or {}
    task_description = _clean(args.get("task_description") or args.get("task") or "")
    if not task_description:
        return _json({"ok": False, "error": "task_description is required"})

    cfg = get_config()
    model_prompt = _decomposition_prompt(task_description)
    subtasks = (
        _heuristic_subtasks(task_description)
        if cfg.orchestrator.auto_decompose
        else [
            {
                "id": "subtask-1",
                "goal": task_description,
                "assigned_to": _suggest_assignment(task_description),
                "dependencies": [],
                "validation": "Verify the task is complete and summarize concrete evidence.",
            }
        ]
    )
    local_task = manager.create_orchestrator_task(
        task_description,
        kind="decomposition",
        status="decomposed",
        subtasks=subtasks,
        metadata={
            "auto_decompose": cfg.orchestrator.auto_decompose,
            "decomposition_prompt": model_prompt,
        },
    )

    kanban_parent = kanban_create_task(
        title=_clean(task_description, max_len=80),
        description=task_description,
        assigned_to=None,
        skills=[],
        dependencies=[],
        metadata={
            "agency_kind": "orchestrator_parent",
            "orchestrator_task_id": local_task["task_id"],
            "decomposition_prompt": model_prompt,
        },
    )
    kanban_children: list[dict[str, Any]] = []
    dependency_links: list[dict[str, Any]] = []
    subtask_to_kanban: dict[str, str] = {}
    if kanban_parent.get("available") and kanban_parent.get("ok"):
        parent_id = str(kanban_parent["task_id"])
        # The parent is a grouping/decomposition record. Mark it done so the
        # existing parent->child dependency semantics do not block every child.
        kanban_update_task(
            parent_id, status="done", result="Decomposed into child Hermes Agency Kanban tasks."
        )
        for subtask in subtasks:
            child = kanban_create_task(
                title=_clean(subtask.get("goal"), max_len=80),
                description=(
                    f"Goal: {subtask.get('goal')}\n\n"
                    f"Validation: {subtask.get('validation') or 'Verify completion with concrete evidence.'}\n\n"
                    f"Subtask id: {subtask.get('id')}"
                ),
                assigned_to=_clean(subtask.get("assigned_to")) or None,
                skills=_skills_for_assignment(str(subtask.get("assigned_to") or "")),
                dependencies=[parent_id],
                metadata={
                    "agency_kind": "orchestrator_child",
                    "orchestrator_task_id": local_task["task_id"],
                    "parent_kanban_task_id": parent_id,
                    "subtask_id": subtask.get("id"),
                    "validation": subtask.get("validation"),
                },
            )
            kanban_children.append(child)
            if child.get("available") and child.get("ok"):
                subtask_to_kanban[str(subtask.get("id"))] = str(child["task_id"])
        for subtask in subtasks:
            child_id = subtask_to_kanban.get(str(subtask.get("id")))
            if not child_id:
                continue
            for dep in subtask.get("dependencies") or []:
                dep_id = subtask_to_kanban.get(str(dep))
                if dep_id:
                    dependency_links.append(kanban_link_tasks(dep_id, child_id))
    else:
        parent_id = None

    updated_local = (
        manager.update_orchestrator_task(
            local_task["task_id"],
            metadata={
                "kanban_parent_task_id": parent_id,
                "kanban_child_task_ids": subtask_to_kanban,
                "kanban_available": bool(kanban_parent.get("available")),
            },
        )
        or local_task
    )
    return _json(
        {
            "ok": True,
            "task_id": parent_id or local_task["task_id"],
            "local_task_id": local_task["task_id"],
            "subtasks": subtasks,
            "local_task": updated_local,
            "decomposition_prompt_for_model": model_prompt,
            "kanban": {
                "available": bool(kanban_parent.get("available")),
                "parent": kanban_parent,
                "children": kanban_children,
                "dependency_links": dependency_links,
                "using_local_state_fallback": not bool(kanban_parent.get("available")),
            },
        }
    )


def _escalation_payload(
    task_description: str,
    reason: str,
    *,
    task_id: str | None = None,
    kanban_task_id: str | None = None,
) -> dict[str, Any]:
    message = announce_escalate(task_description, reason)
    blocked = build_blocked_context(
        task_description,
        reason,
        "Kyle should choose a target agent, clarify scope, or approve a manual route.",
    )
    hook = mark_blocked_hook(
        task_description, reason, blocked["needed_from_kyle"], task_id=kanban_task_id
    )
    return {
        "task_id": task_id,
        "kanban_task_id": kanban_task_id,
        "message": message,
        "context": blocked,
        "kanban_block_hook": hook,
        "announcements": recent_announcements(limit=5),
    }


def orch_route(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Route a task to a target Hermes Agency peer or skill and track it locally."""

    args = args or {}
    task_description = _clean(args.get("task_description") or args.get("task") or "")
    target_agent = _clean(args.get("target_agent") or args.get("assigned_to") or "")
    wait_seconds = float(args.get("wait_seconds") or 0)
    dependencies = args.get("dependencies") or []
    validation = _clean(args.get("validation") or "")

    if not task_description:
        return _json({"ok": False, "error": "task_description is required"})
    policy_action = (
        "deploy"
        if any(
            word in task_description.lower() for word in ("deploy", "release", "production", "ship")
        )
        else "api_call"
    )
    policy = check_autonomy(policy_action, current_profile_name())
    announce_policy(policy_action, policy["decision"], agent=current_profile_name())
    if policy["prohibited"]:
        return _json(
            {
                "ok": False,
                "error": f"policy prohibits autonomous action: {policy_action}",
                "policy": policy,
            }
        )
    if policy["requires_approval"] and not args.get("approved", False):
        task = manager.create_orchestrator_task(task_description, kind="route", status="escalated")
        escalation = _escalation_payload(
            task_description,
            f"Autonomy policy requires Kyle approval for {policy_action}.",
            task_id=task["task_id"],
        )
        manager.update_orchestrator_task(
            task["task_id"], escalation=escalation, metadata={"policy": policy}
        )
        return _json(
            {
                "ok": False,
                "approval_required": True,
                "policy": policy,
                "escalation": escalation,
                "local_task": manager.orchestrator_task_sync(task["task_id"]),
            }
        )
    if not target_agent:
        target_agent = _suggest_assignment(task_description)
    if not target_agent and get_config().team.bidding:
        winner = choose_best_bid(str(args.get("task_id") or ""))
        if winner and winner.get("status") == "available":
            target_agent = str(winner.get("agent") or "")
            announce_bid(str(args.get("task_id") or "pending"), target_agent)
    if not target_agent:
        task = manager.create_orchestrator_task(task_description, kind="route", status="escalated")
        kanban_task = kanban_create_task(
            title=_clean(task_description, max_len=80),
            description=task_description,
            assigned_to=None,
            skills=[],
            dependencies=[],
            metadata={"agency_kind": "route_escalation", "orchestrator_task_id": task["task_id"]},
        )
        kanban_task_id = (
            str(kanban_task["task_id"])
            if kanban_task.get("available") and kanban_task.get("ok")
            else None
        )
        if kanban_task_id:
            kanban_update_task(
                kanban_task_id,
                status="blocked",
                error="No target_agent was provided and no routing hint matched.",
            )
        escalation = _escalation_payload(
            task_description,
            "No target_agent was provided and no routing hint matched.",
            task_id=task["task_id"],
            kanban_task_id=kanban_task_id,
        )
        manager.update_orchestrator_task(
            task["task_id"], escalation=escalation, metadata={"kanban_task_id": kanban_task_id}
        )
        return _json(
            {
                "ok": False,
                "error": "target_agent is required",
                "escalation": escalation,
                "local_task": manager.orchestrator_task_sync(task["task_id"]),
                "kanban": kanban_task,
            }
        )

    resolved = _resolve_target(target_agent)
    task = manager.create_orchestrator_task(
        task_description,
        kind="route",
        target_agent=target_agent,
        status="routing",
        metadata={"resolved_target": resolved, "kanban_available": True},
    )
    kanban_task = kanban_create_task(
        title=_clean(task_description, max_len=80),
        description=task_description,
        assigned_to=(resolved.get("label") or target_agent) if resolved.get("ok") else None,
        skills=_skills_for_assignment(
            target_agent, resolved if isinstance(resolved, dict) else None
        ),
        dependencies=[str(dep) for dep in dependencies if str(dep).strip()],
        metadata={
            "agency_kind": "orch_route",
            "orchestrator_task_id": task["task_id"],
            "target_agent": target_agent,
            "resolved_target": resolved,
            "validation": validation,
            "sender": current_profile_name(),
        },
    )
    kanban_task_id = (
        str(kanban_task["task_id"])
        if kanban_task.get("available") and kanban_task.get("ok")
        else None
    )
    manager.update_orchestrator_task(
        task["task_id"],
        metadata={
            "kanban_task_id": kanban_task_id,
            "kanban_available": bool(kanban_task.get("available")),
        },
    )
    if not resolved.get("ok"):
        reason = str(resolved.get("error") or "Unknown target agent")
        if kanban_task_id:
            kanban_update_task(kanban_task_id, status="blocked", error=reason)
        escalation = _escalation_payload(
            task_description, reason, task_id=task["task_id"], kanban_task_id=kanban_task_id
        )
        manager.update_orchestrator_task(
            task["task_id"], status="escalated", error=reason, escalation=escalation
        )
        return _json(
            {
                "ok": False,
                "error": reason,
                "resolution": resolved,
                "escalation": escalation,
                "local_task": manager.orchestrator_task_sync(task["task_id"]),
                "kanban": kanban_task,
            }
        )

    conversation_context = {
        "summary": str(kwargs.get("user_task") or task_description).strip(),
        "sender": kwargs.get("profile") or current_profile_name(),
        "channel": kwargs.get("session_id") or "",
        "dependencies": dependencies,
        "constraints": args.get("constraints") or [],
        "validation": validation,
        "metadata": {
            "orchestrator_task_id": task["task_id"],
            "kanban_task_id": kanban_task_id,
            "target_agent": target_agent,
        },
    }
    context_packet = build_context_packet(task_description, conversation_context)
    announce_delegate(
        task_description, resolved.get("label") or target_agent, kanban_task_id=kanban_task_id
    )
    try:
        routed = manager.send_task_sync(
            message=task_description,
            peer_id=resolved.get("peer_id"),
            skill=resolved.get("skill"),
            wait_seconds=wait_seconds,
            metadata={
                "orchestrator_task_id": task["task_id"],
                "kanban_task_id": kanban_task_id or "",
                "target_agent": target_agent,
                "routed_by": current_profile_name(),
            },
            conversation_context=conversation_context,
        )
        updated = manager.update_orchestrator_task(
            task["task_id"],
            status="delegated",
            a2a_task_id=routed.get("task_id"),
            context_packet=context_packet if isinstance(context_packet, dict) else None,
            result_text=json.dumps(routed, default=str),
        )
        return _json(
            {
                "ok": True,
                "task_id": task["task_id"],
                "a2a_task_id": routed.get("task_id"),
                "target": resolved,
                "task": routed,
                "local_task": updated,
                "kanban": routed.get("kanban") or kanban_task,
            }
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if kanban_task_id:
            kanban_update_task(kanban_task_id, status="failed", error=error)
        announce_error(task_description, error, kanban_task_id=kanban_task_id)
        escalation = _escalation_payload(
            task_description,
            f"Target unreachable or send failed: {error}",
            task_id=task["task_id"],
            kanban_task_id=kanban_task_id,
        )
        updated = manager.update_orchestrator_task(
            task["task_id"], status="escalated", error=error, escalation=escalation
        )
        return _json(
            {
                "ok": False,
                "error": error,
                "target": resolved,
                "escalation": escalation,
                "local_task": updated,
                "kanban": kanban_task,
            }
        )


def orch_status(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Return local or A2A status for an orchestrator task."""

    args = args or {}
    task_id = _clean(args.get("task_id") or "")
    if not task_id:
        return _json({"ok": False, "error": "task_id is required"})

    kanban = kanban_get_task(task_id)
    if kanban.get("available") and kanban.get("ok"):
        return _json({"ok": True, "task_id": kanban.get("task_id"), "kanban": kanban})

    local = manager.orchestrator_task_sync(task_id)
    if local is not None:
        a2a_status = None
        if local.get("a2a_task_id"):
            try:
                a2a_status = manager.task_status_sync(str(local["a2a_task_id"]))
            except Exception as exc:
                a2a_status = {"error": f"{type(exc).__name__}: {exc}"}
        return _json(
            {
                "ok": True,
                "task_id": task_id,
                "local_task": local,
                "a2a_status": a2a_status,
                "kanban": {"available": False},
            }
        )

    try:
        a2a_task = manager.task_status_sync(task_id)
    except Exception as exc:
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}", "task_id": task_id})
    if a2a_task is None:
        return _json(
            {
                "ok": False,
                "error": f"unknown task_id: {task_id}",
                "task_id": task_id,
                "kanban": {"available": False},
            }
        )
    return _json(
        {"ok": True, "task_id": task_id, "a2a_status": a2a_task, "kanban": {"available": False}}
    )


def orch_list_tasks(args: dict[str, Any] | None = None, **_: Any) -> str:
    """List active/recent orchestrator tasks from local fallback state."""

    args = args or {}
    limit = int(args.get("limit") or 50)
    include_completed = bool(args.get("include_completed", True))
    filters: dict[str, Any] = {
        "limit": limit,
        "include_archived": False,
        "sort": args.get("sort") or "created-desc",
    }
    if args.get("status"):
        filters["status"] = args.get("status")
    if args.get("assignee") or args.get("assigned_to"):
        filters["assignee"] = args.get("assignee") or args.get("assigned_to")
    kanban = kanban_list_tasks(filters)
    if kanban.get("available") and kanban.get("ok"):
        tasks = kanban.get("tasks") or []
        if not include_completed:
            tasks = [
                task
                for task in tasks
                if task.get("plugin_status") not in {"done", "blocked", "failed"}
                and task.get("status") not in {"archived"}
            ]
        return _json(
            {
                "ok": True,
                "tasks": tasks,
                "kanban": {"available": True, "source_of_truth": True},
                "announcements": recent_announcements(limit=5),
            }
        )

    tasks = manager.orchestrator_tasks_sync(limit=limit)
    if not include_completed:
        tasks = [
            task
            for task in tasks
            if task.get("status") not in {"completed", "failed", "escalated", "cancelled"}
        ]
    return _json(
        {
            "ok": True,
            "tasks": tasks,
            "kanban": {"available": False, "using_local_state_fallback": True},
            "announcements": recent_announcements(limit=5),
        }
    )


def orch_escalate(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Create a platform-native escalation message for Kyle."""

    args = args or {}
    task_description = _clean(args.get("task_description") or args.get("task") or "")
    reason = _clean(args.get("reason") or "")
    existing_task_id = _clean(args.get("task_id") or "")
    if not task_description and existing_task_id:
        existing = kanban_get_task(existing_task_id)
        if existing.get("available") and existing.get("ok"):
            task_description = str(existing.get("task", {}).get("title") or existing_task_id)
    if not task_description:
        return _json({"ok": False, "error": "task_description is required"})
    if not reason:
        return _json({"ok": False, "error": "reason is required"})
    kanban_task_id = existing_task_id or None
    kanban_task = None
    if kanban_task_id:
        blocked = kanban_update_task(kanban_task_id, status="blocked", error=reason)
        if not (blocked.get("available") and blocked.get("ok")):
            kanban_task_id = None
            kanban_task = blocked
    if not kanban_task_id:
        kanban_task = kanban_create_task(
            title=_clean(task_description, max_len=80),
            description=task_description,
            assigned_to=None,
            skills=[],
            dependencies=[],
            metadata={"agency_kind": "escalation", "reason": reason},
        )
        kanban_task_id = (
            str(kanban_task["task_id"])
            if kanban_task.get("available") and kanban_task.get("ok")
            else None
        )
        if kanban_task_id:
            kanban_update_task(kanban_task_id, status="blocked", error=reason)
    task = manager.create_orchestrator_task(task_description, kind="escalation", status="escalated")
    escalation = _escalation_payload(
        task_description, reason, task_id=task["task_id"], kanban_task_id=kanban_task_id
    )
    updated = manager.update_orchestrator_task(
        task["task_id"],
        escalation=escalation,
        error=reason,
        metadata={"kanban_task_id": kanban_task_id},
    )
    return _json(
        {
            "ok": True,
            "task_id": kanban_task_id or task["task_id"],
            "local_task_id": task["task_id"],
            "escalation_message": escalation["message"],
            "escalation": escalation,
            "local_task": updated,
            "kanban": kanban_task or (kanban_get_task(kanban_task_id) if kanban_task_id else None),
        }
    )


ORCH_ROUTE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "orch_route",
        "description": "Delegate a task to a specific Hermes Agency peer/profile/skill and track it in Kanban when available.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {"type": "string", "description": "Task to assign."},
                "target_agent": {
                    "type": "string",
                    "description": "Target peer_id, profile/name, or skill. Prefix with peer: or skill: for explicit mode.",
                },
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional dependency task IDs.",
                },
                "validation": {
                    "type": "string",
                    "description": "How the target should verify completion.",
                },
                "wait_seconds": {
                    "type": "number",
                    "description": "Optional seconds to wait for immediate completion.",
                },
                "approved": {
                    "type": "boolean",
                    "description": "Set true only when Kyle has approved a policy-gated action.",
                },
            },
            "required": ["task_description", "target_agent"],
            "additionalProperties": False,
        },
    },
}

ORCH_DECOMPOSE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "orch_decompose",
        "description": "Break a complex task into structured subtasks with assigned_to, dependencies, and validation. Creates linked Kanban tasks when available.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {"type": "string", "description": "Complex task to decompose."}
            },
            "required": ["task_description"],
            "additionalProperties": False,
        },
    },
}

ORCH_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "orch_status",
        "description": "Check progress for a local orchestrator task or sent Hermes Agency task.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Local orch-* task ID or A2A task ID."}
            },
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
}

ORCH_LIST_TASKS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "orch_list_tasks",
        "description": "List active/recent orchestrator work from Kanban when available, with local fallback.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum records to return; default 50.",
                },
                "include_completed": {
                    "type": "boolean",
                    "description": "Include terminal records; default true.",
                },
                "status": {
                    "type": "string",
                    "description": "Optional Kanban/plugin status filter.",
                },
                "assignee": {"type": "string", "description": "Optional assignee/profile filter."},
            },
            "additionalProperties": False,
        },
    },
}

ORCH_ESCALATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "orch_escalate",
        "description": "Escalate a blocked routing/delegation decision to Kyle via platform-native final response text.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {"type": "string", "description": "Task needing Kyle's input."},
                "task_id": {
                    "type": "string",
                    "description": "Optional existing Kanban/local task ID to mark blocked.",
                },
                "reason": {"type": "string", "description": "Why escalation is needed."},
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
}

ORCHESTRATOR_TOOLS = (
    ("orch_route", ORCH_ROUTE_SCHEMA, orch_route, "🧭"),
    ("orch_decompose", ORCH_DECOMPOSE_SCHEMA, orch_decompose, "🧩"),
    ("orch_status", ORCH_STATUS_SCHEMA, orch_status, "📊"),
    ("orch_list_tasks", ORCH_LIST_TASKS_SCHEMA, orch_list_tasks, "📚"),
    ("orch_escalate", ORCH_ESCALATE_SCHEMA, orch_escalate, "🚨"),
)
