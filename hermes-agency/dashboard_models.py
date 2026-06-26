"""Pydantic response models for the Hermes Agency dashboard API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Health & warnings
# ---------------------------------------------------------------------------


class DashboardWarning(BaseModel):
    id: str
    label: str
    status: str
    message: str
    remediation: str | None = None


class DashboardHealth(BaseModel):
    ok: bool
    profile_home: str = ""
    active_profile: str = ""
    active_model_set: str = ""
    daemon_running: bool = False
    registry_configured: bool = False
    kanban_available: bool = False
    incoming_queue_count: int = 0
    warnings: list[DashboardWarning] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------


class DashboardDoctorSummary(BaseModel):
    summary: dict[str, int] = Field(default_factory=dict)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    exit_code: int = 0


# ---------------------------------------------------------------------------
# Agents & departments
# ---------------------------------------------------------------------------


class DashboardAgent(BaseModel):
    name: str
    label: str = ""
    department: str = ""
    skills: list[str] = Field(default_factory=list)
    description: str = ""
    discoverable: bool = False
    peer_id: str | None = None


class DashboardDepartment(BaseModel):
    name: str
    agent_count: int = 0
    agents: list[DashboardAgent] = Field(default_factory=list)


class DashboardSkill(BaseModel):
    name: str
    description: str = ""
    agent_count: int = 0


# ---------------------------------------------------------------------------
# Tasks (unified view of agency incoming + kanban)
# ---------------------------------------------------------------------------


class DashboardTask(BaseModel):
    """Unified task representation.

    ``id`` is always the canonical ID for the *source* system:
    - source='agency_incoming' → id is the A2A task_id (IncomingTaskRecord.task_id)
    - source='kanban'         → id is the Kanban task row id

    ``kanban_task_id`` is the *optional* cross-reference from agency records
    to their Kanban mirror; it is NEVER the primary ID for agency records.
    """

    id: str
    source: str = "agency_incoming"  # 'agency_incoming' | 'kanban'
    title: str = ""
    status: str = ""
    created_at: float | None = None
    updated_at: float | None = None
    message_text: str = ""
    result_text: str | None = None
    error_text: str | None = None
    kanban_task_id: str | None = None
    linked_kanban_status: str = "none"  # 'present' | 'missing' | 'unknown' | 'none'
    available_actions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class DashboardEvent(BaseModel):
    id: str
    severity: str = "info"  # 'info' | 'success' | 'warning' | 'error'
    source: str = ""
    message: str = ""
    timestamp: float | None = None
    related_task_id: str | None = None
    related_agent: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Config & model sets
# ---------------------------------------------------------------------------


class DashboardConfig(BaseModel):
    active_model_set: str = ""
    available_model_sets: list[str] = Field(default_factory=list)
    profile_home: str = ""
    daemon_status: str = "unknown"
    security: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class DashboardDispatchRequest(BaseModel):
    message: str
    skill: str | None = None
    department: str | None = None
    target_agent: str | None = None
    priority: int = 0
    create_kanban_task: bool = True


class DashboardDispatchResponse(BaseModel):
    ok: bool = False
    task_id: str | None = None
    kanban_task_id: str | None = None
    target: str | None = None
    result_text: str | None = None
    error_text: str | None = None


# ---------------------------------------------------------------------------
# Settings (server metadata)
# ---------------------------------------------------------------------------


class DashboardSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    local_only: bool = True
    server_start_time: float | None = None
    version: str = "0.1.0"
    frontend_build_timestamp: str | None = None
