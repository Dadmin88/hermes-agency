"""Local orchestrator task state and context rendering."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


_ROUTE_TERMINAL_STATUSES = {"completed", "failed", "blocked", "escalated", "cancelled"}
_ROUTE_FAILED_STATUSES = {"failed", "blocked", "escalated"}


def _delegated_route_result(updates: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a serialized route result when ``orch_route`` reports delegation."""

    if updates.get("status") != "delegated":
        return None
    raw = updates.get("result_text")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        result = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def _route_status(result: dict[str, Any]) -> str:
    """Map a transport result to the local orchestrator lifecycle."""

    status = " ".join(str(result.get("status") or "").split()).strip().lower()
    if result.get("queued") or status == "queued":
        return "queued"
    if status in {"completed", "done"}:
        return "completed"
    if status in {"failed", "blocked", "cancelled"}:
        return status
    return "delegated"


@dataclass
class OrchestratorSubtaskRecord:
    """Serializable local record for an orchestrator-created subtask."""

    subtask_id: str
    goal: str
    assigned_to: str = ""
    dependencies: list[str] = field(default_factory=list)
    validation: str = ""
    status: str = "pending"
    a2a_task_id: str | None = None
    result_text: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "subtask_id": self.subtask_id,
            "goal": self.goal,
            "assigned_to": self.assigned_to,
            "dependencies": list(self.dependencies),
            "validation": self.validation,
            "status": self.status,
            "a2a_task_id": self.a2a_task_id,
            "result_text": self.result_text,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


@dataclass
class OrchestratorTaskRecord:
    """Serializable local fallback tracking record for orchestrator work."""

    task_id: str
    description: str
    kind: str = "task"
    target_agent: str = ""
    status: str = "active"
    parent_task_id: str | None = None
    a2a_task_id: str | None = None
    subtasks: list[OrchestratorSubtaskRecord] = field(default_factory=list)
    context_packet: dict[str, Any] | None = None
    result_text: str | None = None
    error: str | None = None
    escalation: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "kind": self.kind,
            "target_agent": self.target_agent,
            "status": self.status,
            "parent_task_id": self.parent_task_id,
            "a2a_task_id": self.a2a_task_id,
            "subtasks": [item.as_dict() for item in self.subtasks],
            "context_packet": self.context_packet,
            "result_text": self.result_text,
            "error": self.error,
            "escalation": self.escalation,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


class OrchestratorStateMixin:
    """Local fallback state and context for orchestrator profiles."""

    def _refresh_orchestrator_state(self) -> None:
        records = list(self._orchestrator_tasks.values())
        self.state.orchestrator_active_task_count = sum(
            1 for item in records if item.status not in _ROUTE_TERMINAL_STATUSES
        )
        self.state.orchestrator_completed_task_count = sum(
            1 for item in records if item.status == "completed"
        )
        self.state.orchestrator_failed_task_count = sum(
            1 for item in records if item.status in _ROUTE_FAILED_STATUSES
        )

    def _current_load(self) -> int:
        return (
            sum(
                1
                for item in self._incoming_records.values()
                if item.status in {"queued", "processing"}
            )
            + self.state.orchestrator_active_task_count
        )

    def create_orchestrator_task(
        self,
        description: str,
        *,
        kind: str = "task",
        target_agent: str = "",
        status: str = "active",
        parent_task_id: str | None = None,
        subtasks: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a local fallback tracking record for orchestrator work."""

        task_id = f"orch-{uuid.uuid4().hex[:12]}"
        subtask_records = [
            OrchestratorSubtaskRecord(
                subtask_id=str(item.get("id") or item.get("subtask_id") or f"subtask-{idx}"),
                goal=str(item.get("goal") or "").strip(),
                assigned_to=str(item.get("assigned_to") or "").strip(),
                dependencies=[str(dep) for dep in (item.get("dependencies") or [])],
                validation=str(item.get("validation") or "").strip(),
                status=str(item.get("status") or "pending"),
            )
            for idx, item in enumerate(subtasks or [], start=1)
            if str(item.get("goal") or "").strip()
        ]
        record = OrchestratorTaskRecord(
            task_id=task_id,
            description=str(description or "").strip(),
            kind=kind,
            target_agent=str(target_agent or "").strip(),
            status=status,
            parent_task_id=parent_task_id,
            subtasks=subtask_records,
            metadata=dict(metadata or {}),
        )
        self._orchestrator_tasks[task_id] = record
        self._orchestrator_order.append(task_id)
        while len(self._orchestrator_order) > 200:
            old_task_id = self._orchestrator_order.popleft()
            self._orchestrator_tasks.pop(old_task_id, None)
        self._refresh_orchestrator_state()
        return record.as_dict()

    def update_orchestrator_task(self, task_id: str, **updates: Any) -> dict[str, Any] | None:
        """Update a local orchestrator task record and reconcile routed outcomes."""

        record = self._orchestrator_tasks.get(task_id)
        if record is None:
            return None

        route_result = _delegated_route_result(updates)
        if route_result is not None:
            updates = dict(updates)
            updates["status"] = _route_status(route_result)
            artifact_text = str(route_result.get("artifact_text") or "").strip()
            if artifact_text:
                updates["result_text"] = artifact_text
            if updates["status"] == "queued":
                kanban_task_id = str(record.metadata.get("kanban_task_id") or "").strip()
                if kanban_task_id:
                    try:
                        self._nm().kanban_update_task(
                            kanban_task_id,
                            status="running",
                            result="Queued for offline agent",
                        )
                    except Exception:
                        pass

        for key in (
            "kind",
            "target_agent",
            "status",
            "parent_task_id",
            "a2a_task_id",
            "context_packet",
            "result_text",
            "error",
            "escalation",
        ):
            if key in updates:
                setattr(record, key, updates[key])
        if "metadata" in updates and isinstance(updates["metadata"], dict):
            record.metadata.update(updates["metadata"])
        if "subtasks" in updates and isinstance(updates["subtasks"], list):
            record.subtasks = [
                OrchestratorSubtaskRecord(
                    subtask_id=str(item.get("id") or item.get("subtask_id") or f"subtask-{idx}"),
                    goal=str(item.get("goal") or "").strip(),
                    assigned_to=str(item.get("assigned_to") or "").strip(),
                    dependencies=[str(dep) for dep in (item.get("dependencies") or [])],
                    validation=str(item.get("validation") or "").strip(),
                    status=str(item.get("status") or "pending"),
                    a2a_task_id=item.get("a2a_task_id"),
                    result_text=item.get("result_text"),
                    error=item.get("error"),
                )
                for idx, item in enumerate(updates["subtasks"], start=1)
                if str(item.get("goal") or "").strip()
            ]
        if record.status in _ROUTE_TERMINAL_STATUSES and record.completed_at is None:
            record.completed_at = time.time()
        record.updated_at = time.time()
        self._refresh_orchestrator_state()
        return record.as_dict()

    def orchestrator_task_sync(self, task_id: str) -> dict[str, Any] | None:
        record = self._orchestrator_tasks.get(task_id)
        return record.as_dict() if record is not None else None

    def orchestrator_tasks_sync(self, limit: int = 50) -> list[dict[str, Any]]:
        self._refresh_orchestrator_state()
        task_ids = list(self._orchestrator_order)[-max(1, limit) :]
        return [
            self._orchestrator_tasks[task_id].as_dict()
            for task_id in reversed(task_ids)
            if task_id in self._orchestrator_tasks
        ]

    def cached_orchestrator_context(self) -> str:
        """Return enhanced context for the promoted orchestrator profile."""

        cfg = self._nm().get_config()
        self.state.config = cfg
        if not self._nm().is_current_orchestrator(cfg):
            return ""
        team_state = self._nm().get_team_state()
        kanban_tasks_result = self._nm().kanban_list_tasks(
            {"limit": 12, "include_archived": False, "sort": "created-desc"}
        )
        tasks = (
            kanban_tasks_result.get("tasks")
            if kanban_tasks_result.get("available")
            else self.orchestrator_tasks_sync(limit=12)
        )
        lines = [
            "Hermes Agency orchestrator context:",
            f"Current orchestrator profile: {self._nm().current_profile_name()}",
            f"Tenant: {cfg.team.tenant}",
            f"Bidding enabled: {cfg.team.bidding}; proactive enabled: {cfg.team.proactive}; learning enabled: {cfg.team.learning}",
            "You are promoted as the routing layer. Decompose complex work and delegate; do not do routed subtasks yourself unless the operator explicitly asks.",
        ]
        if cfg.routing:
            lines.append("Configured routing hints (advisory, not hard rules):")
            for key, value in sorted(cfg.routing.items()):
                lines.append(f"- {key}: {value}")
        else:
            lines.append("Configured routing hints: none.")
        if team_state.peers:
            lines.append("Full team capability map:")
            for peer in sorted(
                team_state.peers.values(),
                key=lambda item: (item.card_name or item.name or item.peer_id).lower(),
            ):
                label = peer.card_name or peer.name or f"{peer.peer_id[:20]}... (skills unknown)"
                lines.append(f"- {label} — peer_id: {peer.peer_id}")
                description = peer.card_description or peer.description
                if description:
                    lines.append(f"  Description: {description}")
                skills = peer.card_skills or peer.skills
                if skills:
                    skill_text = ", ".join(
                        f"{skill.get('id', '')}"
                        + (f" ({skill.get('description')})" if skill.get("description") else "")
                        for skill in skills
                        if skill.get("id")
                    )
                    lines.append(f"  Skills: {skill_text}")
                else:
                    lines.append("  Skills: unknown from peer discovery.")
        else:
            lines.append("Full team capability map: no peers currently discovered.")
        if kanban_tasks_result.get("available"):
            lines.append(
                "Current Kanban state: available; Kanban is the source of truth for Hermes Agency work."
            )
        else:
            lines.append(
                "Current Kanban state: unavailable; using local orchestrator state fallback."
            )
        if tasks:
            lines.append("Recent Kanban/local task history:")
            for task in tasks:
                lines.append(
                    f"- {task.get('id') or task.get('task_id')} [{task.get('plugin_status') or task.get('status')}] {task.get('title') or task.get('description')} -> {task.get('assignee') or task.get('target_agent') or 'unassigned'}"
                )
        else:
            lines.append("Recent local task history: none.")
        policy_read = self._nm().check_autonomy("read", self._nm().current_profile_name())
        policy_deploy = self._nm().check_autonomy("deploy", self._nm().current_profile_name())
        lines.append(
            f"Autonomy policy examples: read={policy_read['decision']}; deploy={policy_deploy['decision']}."
        )
        corrections = self._nm().correction_history(limit=5)
        if corrections:
            lines.append("Recent routing corrections to consider:")
            for item in corrections:
                lines.append(
                    f"- {item.get('task_type')}: avoid {item.get('wrong_target')} -> prefer {item.get('correct_target')}"
                )
        lines.append(
            "Use orch_decompose for complex work, orch_route to delegate via A2A, orch_status/orch_list_tasks for Kanban-backed tracking, and orch_escalate when no suitable/reachable agent exists."
        )
        return "\n".join(lines)
