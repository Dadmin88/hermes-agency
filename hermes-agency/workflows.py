"""Autonomous workflow templates and execution for Hermes Agency."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from hermes_cli.config import cfg_get, load_config

from .announcements import announce_workflow
from .config import get_config
from .kanban_bridge import create_task as kanban_create_task

DEFAULT_WORKFLOWS: dict[str, dict[str, Any]] = {
    "ship_feature": {
        "steps": [
            {"name": "write_code", "skill": "code", "assigned_to": "katana"},
            {
                "name": "write_tests",
                "skill": "testing",
                "assigned_to": "qa",
                "depends_on": ["write_code"],
            },
            {
                "name": "deploy",
                "skill": "deployment",
                "assigned_to": "hermes",
                "depends_on": ["write_tests"],
            },
        ]
    },
    "fix_and_deploy": {
        "steps": [
            {"name": "diagnose", "skill": "debugging", "assigned_to": "katana"},
            {"name": "fix", "skill": "code", "assigned_to": "katana", "depends_on": ["diagnose"]},
            {"name": "verify", "skill": "testing", "assigned_to": "qa", "depends_on": ["fix"]},
            {
                "name": "deploy",
                "skill": "deployment",
                "assigned_to": "hermes",
                "depends_on": ["verify"],
            },
        ]
    },
}


def workflow_templates() -> dict[str, dict[str, Any]]:
    """Return user-defined templates overlaid on shipped examples."""

    config = load_config()
    raw = cfg_get(config, "agency", "workflows", default={}) or {}
    workflows = dict(DEFAULT_WORKFLOWS)
    if isinstance(raw, dict):
        for name, template in raw.items():
            if isinstance(template, dict) and isinstance(template.get("steps"), list):
                workflows[str(name)] = template
    return workflows


def _clean(value: Any, *, max_len: int | None = None) -> str:
    text = " ".join(str(value or "").split()).strip()
    if max_len and len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def _step_description(step: dict[str, Any], context: dict[str, Any]) -> str:
    bits = [f"Workflow step: {step.get('name')}"]
    if step.get("skill"):
        bits.append(f"Required skill: {step.get('skill')}")
    if step.get("depends_on"):
        bits.append("Depends on: " + ", ".join(str(dep) for dep in step.get("depends_on") or []))
    if context:
        bits.append("Context:")
        for key, value in context.items():
            bits.append(f"- {key}: {value}")
    return "\n".join(bits)


def execute_workflow(
    name: str,
    context: dict[str, Any] | None = None,
    *,
    delegate: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Start a workflow by creating Kanban tasks and delegating ready steps.

    Kanban carries dependency blocking. Only root steps (no ``depends_on``) are
    delegated immediately; dependent steps become ready when their parents finish
    and can be picked up by dispatcher/self-serve/bidding.
    """

    templates = workflow_templates()
    template = templates.get(str(name))
    if not template:
        return {
            "ok": False,
            "error": f"unknown workflow template: {name}",
            "available_templates": sorted(templates),
        }
    cfg = get_config()
    ctx = dict(context or {})
    workflow_id = f"wf-{int(time.time())}-{_clean(name)}"
    steps = [
        step for step in template.get("steps") or [] if isinstance(step, dict) and step.get("name")
    ]
    created: list[dict[str, Any]] = []
    step_to_task: dict[str, str] = {}
    for step in steps:
        depends_on = [str(dep) for dep in (step.get("depends_on") or [])]
        parent_ids = [step_to_task[dep] for dep in depends_on if dep in step_to_task]
        task = kanban_create_task(
            title=_clean(f"{name}: {step.get('name')}", max_len=80),
            description=_step_description(step, ctx),
            assigned_to=_clean(step.get("assigned_to")) or None,
            skills=[str(step.get("skill"))] if step.get("skill") else [],
            dependencies=parent_ids,
            metadata={
                "agency_kind": "workflow_step",
                "workflow_id": workflow_id,
                "workflow_name": name,
                "step_name": step.get("name"),
                "depends_on": depends_on,
                "tenant": cfg.team.tenant,
            },
        )
        if task.get("available") and task.get("ok"):
            step_to_task[str(step["name"])] = str(task["task_id"])
        created.append({"step": step, "kanban": task})

    delegated: list[dict[str, Any]] = []
    if delegate is not None:
        for item in created:
            step = item["step"]
            if step.get("depends_on"):
                continue
            task_id = str((item.get("kanban") or {}).get("task_id") or "")
            if not task_id:
                continue
            try:
                delegated.append(delegate(step, task_id))
            except Exception as exc:
                delegated.append(
                    {"ok": False, "step": step.get("name"), "error": f"{type(exc).__name__}: {exc}"}
                )
    announcement = announce_workflow(name, workflow_id, len(created))
    return {
        "ok": True,
        "workflow_id": workflow_id,
        "template": name,
        "steps": created,
        "step_to_task": step_to_task,
        "delegated": delegated,
        "announcement": announcement,
        "summary": f"Workflow {name} started with {len(created)} Kanban step task(s). Dependent steps are blocked by Kanban until prerequisites complete.",
    }
