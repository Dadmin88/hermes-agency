"""Lifecycle manager for a per-profile Hermes Agency node.

Phase 3 owns the runtime lifecycle:

- create an Hermes Agency ``Node`` from the generated profile AgentCard
- use ``$HERMES_HOME/.agency`` as the per-profile daemon home by default
- start the SDK node and store its peer ID / DID
- keep ``serve_forever()`` running as a background task for incoming events
- stop the node cleanly on explicit stop, session hooks, or process exit

The SDK uses asyncio gRPC channels, so this manager owns a dedicated background
asyncio loop. Tool calls and plugin hooks are synchronous in Hermes; routing all
node operations through one loop avoids creating a node on an ``asyncio.run``
loop that closes immediately after startup.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from .announcements import (
    announce_complete,
    announce_delegate,
    announce_error,
    announce_registration,
    announce_start,
    recent_announcements,
)
from .card_builder import build_card, card_to_dict
from .config import AgencyConfig, current_profile_name, get_config, is_current_orchestrator
from .context_packet import (
    build_context_packet,
    packet_goal_or_text,
    packet_to_message_text,
    parse_context_packet,
)
from .conversation import build_conversation_context, build_conversation_history
from .kanban_bridge import add_comment as kanban_add_comment
from .kanban_bridge import get_task as kanban_get_task
from .kanban_bridge import list_tasks as kanban_list_tasks
from .kanban_bridge import track_delegation as kanban_track_delegation
from .kanban_bridge import update_task as kanban_update_task
from .bidding import handle_bid_message, get_bidding_state
from .learning import correction_history
from .policy import check_autonomy
from .registration import (
    deregister_agent,
    get_registration_state,
    handle_registration_message,
    parse_control_message,
    register_agent,
    update_registration,
)
from .team_context import build_team_context, get_team_state, refresh_capability_map
from .task_processor import process_incoming_task
from .trust import TrustError, store_for_config, sync_relay_allowlist, trust_summary, verify_peer_tofu

REGISTRY_REREGISTER_INTERVAL_SECONDS = 20
REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS = 1
REGISTRY_REREGISTER_MAX_BACKOFF_SECONDS = 60
REGISTRY_REREGISTER_FAILURE_LOG_EVERY = 5
REGISTRY_HEALTHY_WINDOW_SECONDS = 60

logger = logging.getLogger(__name__)


def _registry_addresses() -> list[str]:
    """Return configured Hermes Agency registry gRPC addresses.

    The daemon reads ``AGENTANYCAST_REGISTRY_ADDRS`` for initial registration.
    The relay registry TTL is currently 30s, so the plugin also uses the same
    env var for periodic refreshes while the node is alive.
    """

    raw = os.getenv("AGENTANYCAST_REGISTRY_ADDRS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _resolve_daemon_bin() -> Any | None:
    """Resolve the daemon binary path without allowing SDK overwrite of fixed builds.

    Preference order:

    1. ``agency.daemon_bin`` config override, when it exists.
    2. Protected repository copy at ``~/src/hermes-agentanycast/bin/agentanycastd``.
    3. ``None``, which lets the SDK manage/download the daemon as a fallback.
    """

    cfg = get_config()
    if cfg.daemon_bin and cfg.daemon_bin.exists():
        return cfg.daemon_bin

    protected = os.path.expanduser("~/src/hermes-agentanycast/bin/agentanycastd")
    if os.path.exists(protected):
        return protected

    return None


@dataclass
class NodeState:
    """Serializable state for the active profile's Hermes Agency node."""

    started: bool = False
    peer_id: str | None = None
    last_peer_id: str | None = None
    did_key: str | None = None
    error: str | None = None
    config: AgencyConfig = field(default_factory=get_config)
    card_name: str | None = None
    skill_count: int = 0
    serve_task_running: bool = False
    started_at: float | None = None
    stopped_at: float | None = None
    last_status: str | None = None
    incoming_task_count: int = 0
    incoming_queue_size: int = 0
    incoming_processing_count: int = 0
    incoming_completed_count: int = 0
    incoming_failed_count: int = 0
    team_context: str = ""
    team_peer_count: int = 0
    team_last_refresh: float | None = None
    team_last_error: str | None = None
    orchestrator_active_task_count: int = 0
    orchestrator_completed_task_count: int = 0
    orchestrator_failed_task_count: int = 0
    registration_count: int = 0
    bidding_request_count: int = 0
    bidding_bid_count: int = 0
    last_registration_time: float | None = None
    consecutive_failures: int = 0
    next_retry_at: float | None = None
    registration_healthy: bool = False
    registry_reregister_loop_exited: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "peer_id": self.peer_id,
            "last_peer_id": self.last_peer_id,
            "did_key": self.did_key,
            "error": self.error,
            "config": self.config.as_dict(),
            "card_name": self.card_name,
            "skill_count": self.skill_count,
            "serve_task_running": self.serve_task_running,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "last_status": self.last_status,
            "incoming_task_count": self.incoming_task_count,
            "incoming_queue_size": self.incoming_queue_size,
            "incoming_processing_count": self.incoming_processing_count,
            "incoming_completed_count": self.incoming_completed_count,
            "incoming_failed_count": self.incoming_failed_count,
            "team_context": self.team_context,
            "team_peer_count": self.team_peer_count,
            "team_last_refresh": self.team_last_refresh,
            "team_last_error": self.team_last_error,
            "orchestrator_active_task_count": self.orchestrator_active_task_count,
            "orchestrator_completed_task_count": self.orchestrator_completed_task_count,
            "orchestrator_failed_task_count": self.orchestrator_failed_task_count,
            "registration_count": self.registration_count,
            "bidding_request_count": self.bidding_request_count,
            "bidding_bid_count": self.bidding_bid_count,
            "last_registration_time": self.last_registration_time,
            "consecutive_failures": self.consecutive_failures,
            "next_retry_at": self.next_retry_at,
            "registration_healthy": self.registration_healthy,
            "registry_reregister_loop_exited": self.registry_reregister_loop_exited,
        }


@dataclass
class IncomingTaskRecord:
    """Serializable local queue/registry record for an incoming A2A task."""

    task_id: str
    sender_peer_id: str
    sender_card: dict[str, Any] | None
    target_skill_id: str
    message_text: str
    context_id: str = ""
    context_packet: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    kanban_task_id: str | None = None
    progress_updates: list[dict[str, Any]] = field(default_factory=list)
    status: str = "received"
    result_text: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "sender_peer_id": self.sender_peer_id,
            "sender_card": self.sender_card,
            "target_skill_id": self.target_skill_id,
            "message_text": self.message_text,
            "context_id": self.context_id,
            "context_packet": self.context_packet,
            "metadata": dict(self.metadata),
            "kanban_task_id": self.kanban_task_id,
            "progress_updates": list(self.progress_updates),
            "status": self.status,
            "result_text": self.result_text,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


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


class NodeManager:
    """Singleton wrapper around a profile-scoped Hermes Agency Node."""

    def __init__(self) -> None:
        self._node: Any | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._incoming_queue: asyncio.Queue[Any] | None = None
        self._incoming_worker_task: asyncio.Task[None] | None = None
        self._team_refresh_task: asyncio.Task[None] | None = None
        self._registry_reregister_task: asyncio.Task[None] | None = None
        self._incoming_records: dict[str, IncomingTaskRecord] = {}
        self._incoming_order: deque[str] = deque()
        self._conversation_threads: dict[str, list[dict[str, Any]]] = {}
        self._task_handles: dict[str, Any] = {}
        self._orchestrator_tasks: dict[str, OrchestratorTaskRecord] = {}
        self._orchestrator_order: deque[str] = deque()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._thread_ready = threading.Event()
        self._thread_lock = threading.RLock()
        self._start_future: Any | None = None
        self.state = NodeState()
        atexit.register(self._atexit_stop)

    # ------------------------------------------------------------------
    # Dedicated event loop plumbing
    # ------------------------------------------------------------------

    def _loop_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._thread_lock:
            self._loop = loop
            self._thread_ready.set()
        try:
            loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._thread_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            self._thread_ready.clear()
            self._thread = threading.Thread(
                target=self._loop_main,
                name="agency-node-loop",
                daemon=True,
            )
            self._thread.start()

        if not self._thread_ready.wait(timeout=10):
            raise RuntimeError("Timed out starting Hermes Agency lifecycle loop")
        assert self._loop is not None
        return self._loop

    def _submit(self, coro: Coroutine[Any, Any, Any], timeout: float = 120) -> Any:
        loop = self._ensure_loop()
        if threading.current_thread() is self._thread:
            raise RuntimeError("Cannot synchronously wait on the Hermes Agency loop thread")
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    def _stop_loop_if_idle(self) -> None:
        with self._thread_lock:
            loop = self._loop
            thread = self._thread
            if loop is None or self.state.started:
                return
            loop.call_soon_threadsafe(loop.stop)

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10)
        with self._thread_lock:
            self._loop = None
            self._thread = None
            self._thread_ready.clear()

    # ------------------------------------------------------------------
    # Lifecycle implementation (runs on the dedicated event loop)
    # ------------------------------------------------------------------

    def _status_callback(self, message: str) -> None:
        self.state.last_status = message

    def _record_card_state(self, card: Any) -> None:
        data = card_to_dict(card)
        self.state.card_name = data.get("name")
        self.state.skill_count = len(data.get("skills") or [])

    @staticmethod
    def _serialize_part(part: Any) -> dict[str, Any]:
        if hasattr(part, "to_dict"):
            return part.to_dict()
        if isinstance(part, dict):
            return part
        return {"text": str(part)}

    @classmethod
    def _serialize_artifact(cls, artifact: Any) -> dict[str, Any]:
        if hasattr(artifact, "to_dict"):
            return artifact.to_dict()
        if isinstance(artifact, dict):
            return artifact
        return {"name": str(artifact), "parts": []}

    @classmethod
    def _artifact_text(cls, artifact: Any) -> str:
        data = cls._serialize_artifact(artifact)
        if cls._is_progress_artifact(data):
            return ""
        return cls._artifact_text_without_progress_filter(data)

    @classmethod
    def _artifact_text_without_progress_filter(cls, artifact: Any) -> str:
        data = cls._serialize_artifact(artifact)
        texts: list[str] = []
        for part in data.get("parts") or []:
            part_data = cls._serialize_part(part)
            text = part_data.get("text")
            if text:
                texts.append(str(text))
        return "\n".join(texts)

    @classmethod
    def _is_progress_artifact(cls, artifact: Any) -> bool:
        data = cls._serialize_artifact(artifact)
        metadata = data.get("metadata") or {}
        return (
            data.get("name") == "agency-progress-update"
            or str(metadata.get("agency_progress") or "").lower() in {"1", "true", "yes"}
        )

    @classmethod
    def _progress_update_from_artifact(cls, artifact: Any) -> dict[str, Any] | None:
        data = cls._serialize_artifact(artifact)
        if not cls._is_progress_artifact(data):
            return None
        text = cls._artifact_text_without_progress_filter(data)
        if not text:
            return None
        metadata = data.get("metadata") or {}
        return {"timestamp": metadata.get("timestamp"), "text": text}

    @classmethod
    def _serialize_task(cls, task: Any) -> dict[str, Any]:
        status = getattr(task, "status", "")
        status_value = getattr(status, "value", str(status))
        artifacts = [cls._serialize_artifact(item) for item in getattr(task, "artifacts", [])]
        progress_updates = [
            update
            for update in (cls._progress_update_from_artifact(item) for item in artifacts)
            if update is not None
        ]
        return {
            "task_id": getattr(task, "task_id", ""),
            "context_id": getattr(task, "context_id", ""),
            "status": status_value,
            "target_skill_id": getattr(task, "target_skill_id", ""),
            "originator_peer_id": getattr(task, "originator_peer_id", ""),
            "artifacts": artifacts,
            "progress_updates": progress_updates,
            "artifact_text": "\n".join(
                text for text in (cls._artifact_text(item) for item in artifacts) if text
            ),
            "metadata": getattr(task, "metadata", None) or {},
        }

    @classmethod
    def _serialize_handle(cls, handle: Any) -> dict[str, Any]:
        task = getattr(handle, "_task", None)
        if task is not None:
            return cls._serialize_task(task)
        status = getattr(handle, "status", "")
        return {
            "task_id": getattr(handle, "task_id", ""),
            "status": getattr(status, "value", str(status)),
            "artifacts": [cls._serialize_artifact(item) for item in getattr(handle, "artifacts", [])],
        }

    async def _ensure_started_impl(self) -> None:
        if self._node is None or not self.state.started:
            await self._start_impl()
        if self._node is None or not self.state.started:
            raise RuntimeError(self.state.error or "Hermes Agency node did not start")

    @staticmethod
    def _message_text_from_incoming(task: Any) -> str:
        texts: list[str] = []
        for message in getattr(task, "messages", []) or []:
            for part in getattr(message, "parts", []) or []:
                text = getattr(part, "text", None)
                if text:
                    texts.append(str(text))
        return "\n".join(texts)

    def _sender_card_to_dict(self, task: Any) -> dict[str, Any] | None:
        sender_card = getattr(task, "sender_card", None)
        if sender_card is None:
            return None
        try:
            return card_to_dict(sender_card)
        except Exception:
            return {"name": getattr(sender_card, "name", ""), "description": getattr(sender_card, "description", "")}

    @staticmethod
    def _metadata_to_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return {str(k): v for k, v in value.items()}
        if value is None:
            return {}
        if hasattr(value, "to_dict"):
            try:
                data = value.to_dict()
                return {str(k): v for k, v in data.items()} if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}

    @staticmethod
    def _kanban_task_id_from_metadata(metadata: dict[str, Any], context_packet: dict[str, Any] | None = None) -> str | None:
        for key in ("kanban_task_id", "agency_kanban_task_id"):
            value = metadata.get(key)
            if value:
                return str(value)
        if context_packet:
            nested = context_packet.get("metadata")
            if isinstance(nested, dict):
                value = nested.get("kanban_task_id") or nested.get("agency_kanban_task_id")
                if value:
                    return str(value)
        return None

    @staticmethod
    def _is_duplicate_working_transition(exc: Exception) -> bool:
        """Return True for idempotent incoming WORKING status updates.

        Some daemon builds may mark an inbound task WORKING before the Python
        handler gets its first chance to call ``IncomingTask.update_status``.
        Treating that as fatal converts an otherwise valid remote task into a
        FAILED task and breaks the completion return path.
        """

        text = str(exc)
        return "invalid transition" in text and "WORKING -> WORKING" in text

    @staticmethod
    def _is_terminal_completed_error(exc: Exception) -> bool:
        """Return True when completion already won the daemon state race."""

        text = str(exc)
        return "terminal state COMPLETED" in text

    def _refresh_incoming_state(self) -> None:
        queue_size = self._incoming_queue.qsize() if self._incoming_queue is not None else 0
        records = list(self._incoming_records.values())
        self.state.incoming_task_count = len(records)
        self.state.incoming_queue_size = queue_size
        self.state.incoming_processing_count = sum(1 for item in records if item.status == "processing")
        self.state.incoming_completed_count = sum(1 for item in records if item.status == "completed")
        self.state.incoming_failed_count = sum(1 for item in records if item.status == "failed")

    def _refresh_orchestrator_state(self) -> None:
        records = list(self._orchestrator_tasks.values())
        terminal = {"completed", "failed", "escalated", "cancelled"}
        self.state.orchestrator_active_task_count = sum(1 for item in records if item.status not in terminal)
        self.state.orchestrator_completed_task_count = sum(1 for item in records if item.status == "completed")
        self.state.orchestrator_failed_task_count = sum(1 for item in records if item.status in {"failed", "escalated"})

    def _current_load(self) -> int:
        return sum(1 for item in self._incoming_records.values() if item.status in {"queued", "processing"}) + self.state.orchestrator_active_task_count

    def _refresh_autonomous_state(self) -> None:
        reg_state = get_registration_state()
        bid_state = get_bidding_state()
        self.state.registration_count = len([item for item in reg_state.registrations.values() if item.alive])
        self.state.bidding_request_count = len(bid_state.requests)
        self.state.bidding_bid_count = sum(len(items) for items in bid_state.bids.values())

    def _refresh_registration_health(self) -> None:
        last_success = self.state.last_registration_time
        self.state.registration_healthy = bool(
            self.state.started
            and last_success is not None
            and time.time() - last_success < REGISTRY_HEALTHY_WINDOW_SECONDS
        )

    def _registration_health_dict(self) -> dict[str, Any]:
        self._refresh_registration_health()
        return {
            "last_registration_time": self.state.last_registration_time,
            "consecutive_failures": self.state.consecutive_failures,
            "next_retry_at": self.state.next_retry_at,
            "registration_healthy": self.state.registration_healthy,
            "registry_reregister_loop_exited": self.state.registry_reregister_loop_exited,
            "loop_running": bool(
                self._registry_reregister_task is not None
                and not self._registry_reregister_task.done()
            ),
            "healthy_window_seconds": REGISTRY_HEALTHY_WINDOW_SECONDS,
            "normal_interval_seconds": REGISTRY_REREGISTER_INTERVAL_SECONDS,
        }

    def _record_registry_registration_success(self) -> None:
        now = time.time()
        previous_failures = self.state.consecutive_failures
        self.state.last_registration_time = now
        self.state.consecutive_failures = 0
        self.state.next_retry_at = now + REGISTRY_REREGISTER_INTERVAL_SECONDS
        self.state.registry_reregister_loop_exited = False
        self._refresh_registration_health()
        if previous_failures:
            logger.warning(
                "Hermes Agency relay skill re-registration recovered after %s consecutive failures",
                previous_failures,
            )

    def _record_registry_registration_failure(self, details: str, retry_in_seconds: float) -> None:
        now = time.time()
        self.state.consecutive_failures += 1
        self.state.next_retry_at = now + retry_in_seconds
        self._refresh_registration_health()
        self.state.last_status = f"Registry refresh failed: {details}"
        logger.warning(
            "Hermes Agency relay skill re-registration failed "
            "(consecutive_failures=%s, retry_in=%.1fs): %s",
            self.state.consecutive_failures,
            retry_in_seconds,
            details,
        )
        if self.state.consecutive_failures % REGISTRY_REREGISTER_FAILURE_LOG_EVERY == 0:
            logger.warning(
                "Hermes Agency relay skill re-registration still failing after %s consecutive failures; "
                "last_success=%s next_retry_at=%s",
                self.state.consecutive_failures,
                self.state.last_registration_time,
                self.state.next_retry_at,
            )

    def _handle_registry_registration_result(
        self,
        result: dict[str, Any],
        *,
        retry_in_seconds: float,
    ) -> bool | None:
        if result.get("skipped"):
            self._refresh_registration_health()
            return None
        if result.get("ok"):
            self._record_registry_registration_success()
            return True
        errors = result.get("errors") or [result.get("error") or "unknown registry refresh failure"]
        self._record_registry_registration_failure("; ".join(str(item) for item in errors), retry_in_seconds)
        return False

    def _refresh_team_state_fields(self) -> None:
        team_state = get_team_state()
        self.state.team_peer_count = len(team_state.peers)
        self.state.team_last_refresh = team_state.last_refresh
        self.state.team_last_error = team_state.last_error
        self.state.team_context = build_team_context(self.state.config)

    def effective_relay_allowlist(self, config: AgencyConfig | None = None) -> list[str]:
        """Return configured relay allowlist plus team peers when enabled.

        Empty configured allowlist still means allow-all at the relay. This helper
        is for reporting/syncing; it never converts an empty allowlist into a
        default-deny list unless explicit configured/team peers exist.
        """

        cfg = config or get_config()
        seen: set[str] = set()
        allowlist: list[str] = []
        for peer_id in cfg.relay_security.allowlist:
            clean = str(peer_id or "").strip()
            if clean and clean not in seen:
                seen.add(clean)
                allowlist.append(clean)
        if cfg.relay_security.auto_allow_team:
            for peer_id in sorted(get_team_state().peers):
                clean = str(peer_id or "").strip()
                if clean and clean not in seen:
                    seen.add(clean)
                    allowlist.append(clean)
        return allowlist

    def _peer_allowed_by_effective_allowlist(self, cfg: AgencyConfig, peer_id: str) -> bool:
        configured = set(cfg.relay_security.allowlist)
        if not configured:
            return True
        return str(peer_id or "").strip() in set(self.effective_relay_allowlist(cfg))

    def _verify_team_peers(self, cfg: AgencyConfig) -> None:
        for peer in get_team_state().peers.values():
            try:
                verify_peer_tofu(
                    cfg,
                    peer.peer_id,
                    name=peer.card_name or peer.name,
                    card={"name": peer.card_name or peer.name},
                    source="team_discovery",
                    trust_level="full",
                )
            except TrustError as exc:
                logger.warning("Hermes Agency TOFU rejected discovered peer: %s", exc)

    async def _sync_effective_relay_allowlist(self, cfg: AgencyConfig) -> dict[str, Any]:
        return await asyncio.to_thread(sync_relay_allowlist, cfg, self.effective_relay_allowlist(cfg))

    async def _refresh_team_context_impl(self, *, force: bool = False) -> None:
        cfg = get_config()
        self.state.config = cfg
        if not cfg.team.auto_discover:
            self._refresh_team_state_fields()
            return
        now = time.time()
        team_state = get_team_state()
        refresh_seconds = max(60, cfg.team.context_refresh_minutes * 60)
        if not force and team_state.last_refresh and now - team_state.last_refresh < refresh_seconds:
            self._refresh_team_state_fields()
            return
        if self._node is None or not self.state.started:
            self._refresh_team_state_fields()
            return
        try:
            await refresh_capability_map(
                self._node,
                local_peer_id=self.state.peer_id,
                local_card=build_card(),
            )
            if cfg.team.auto_register:
                await update_registration(
                    self._node,
                    build_card(),
                    current_load=self._current_load(),
                )
            if cfg.relay_security.auto_allow_team:
                self._verify_team_peers(cfg)
                relay_result = await self._sync_effective_relay_allowlist(cfg)
                if not relay_result.get("ok") and not relay_result.get("skipped"):
                    logger.warning("Hermes Agency relay allowlist sync failed: %s", relay_result)
        finally:
            self._refresh_team_state_fields()
            self._refresh_autonomous_state()

    async def _team_refresh_loop(self) -> None:
        while True:
            cfg = get_config()
            await asyncio.sleep(max(60, cfg.team.context_refresh_minutes * 60))
            await self._refresh_team_context_impl(force=True)

    @staticmethod
    def _registry_skill_id(skill: Any) -> str:
        if isinstance(skill, dict):
            return str(skill.get("id") or skill.get("skill_id") or skill.get("name") or "").strip()
        return str(getattr(skill, "id", "") or getattr(skill, "skill_id", "") or getattr(skill, "name", "")).strip()

    @staticmethod
    def _registry_skill_description(skill: Any) -> str:
        if isinstance(skill, dict):
            return str(skill.get("description") or "").strip()
        return str(getattr(skill, "description", "") or "").strip()

    async def _register_skills_with_registries(self, card: Any) -> dict[str, Any]:
        """Refresh this node's relay skill-registry TTL.

        The Go daemon currently registers skills once shortly after startup. The
        relay expires registry entries after 30 seconds, so long-lived Hermes
        gateways need an application-level refresh until the daemon owns this
        heartbeat itself.
        """

        if not self.state.peer_id:
            return {"ok": False, "skipped": True, "reason": "peer_id is not set"}
        addresses = _registry_addresses()
        if not addresses:
            return {"ok": False, "skipped": True, "reason": "AGENTANYCAST_REGISTRY_ADDRS is not set"}

        import importlib

        import grpc

        registry_pb2 = importlib.import_module(
            "agentanycast._generated.agentanycast.v1.registry_service_pb2"
        )
        registry_grpc = importlib.import_module(
            "agentanycast._generated.agentanycast.v1.registry_service_pb2_grpc"
        )
        skills = []
        for item in getattr(card, "skills", []) or []:
            skill_id = self._registry_skill_id(item)
            if not skill_id:
                continue
            skills.append(
                registry_pb2.SkillInfo(
                    skill_id=skill_id,
                    description=self._registry_skill_description(item),
                )
            )
        if not skills:
            return {"ok": False, "skipped": True, "reason": "card has no registry skill IDs"}

        request = registry_pb2.RegisterSkillsRequest(
            peer_id=self.state.peer_id,
            agent_name=str(getattr(card, "name", "") or self.state.card_name or current_profile_name()),
            agent_description=str(getattr(card, "description", "") or ""),
            skills=skills,
        )

        errors: list[str] = []
        for addr in addresses:
            channel = grpc.aio.insecure_channel(addr)
            try:
                stub = registry_grpc.RegistryServiceStub(channel)
                call_metadata = None
                if self.state.config.relay_security.token:
                    call_metadata = (
                        ("authorization", f"Bearer {self.state.config.relay_security.token}"),
                        ("x-agency-relay-token", self.state.config.relay_security.token),
                    )
                if call_metadata:
                    await stub.RegisterSkills(request, timeout=5, metadata=call_metadata)
                else:
                    await stub.RegisterSkills(request, timeout=5)
            except Exception as exc:  # keep node alive; report in status
                errors.append(f"{addr}: {type(exc).__name__}: {exc}")
            finally:
                await channel.close()
        if errors:
            self.state.last_status = "Registry refresh failed: " + "; ".join(errors)
            return {
                "ok": False,
                "skipped": False,
                "errors": errors,
                "addresses": addresses,
                "skill_count": len(skills),
            }
        self.state.last_status = f"Registry refreshed ({len(skills)} skills)."
        return {
            "ok": True,
            "skipped": False,
            "errors": [],
            "addresses": addresses,
            "skill_count": len(skills),
        }

    async def _registry_reregister_loop(self) -> None:
        next_delay = float(REGISTRY_REREGISTER_INTERVAL_SECONDS)
        backoff = float(REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS)
        cancelled = False
        try:
            while True:
                self.state.next_retry_at = time.time() + next_delay
                await asyncio.sleep(next_delay)
                try:
                    cfg = get_config()
                    if not cfg.team.auto_register:
                        next_delay = float(REGISTRY_REREGISTER_INTERVAL_SECONDS)
                        self._refresh_registration_health()
                        continue
                    if self._node is None or not self.state.started:
                        next_delay = float(REGISTRY_REREGISTER_INTERVAL_SECONDS)
                        self._refresh_registration_health()
                        continue
                    result = await self._register_skills_with_registries(build_card())
                    outcome = self._handle_registry_registration_result(
                        result,
                        retry_in_seconds=backoff,
                    )
                    if outcome is False:
                        next_delay = backoff
                        backoff = min(backoff * 2, REGISTRY_REREGISTER_MAX_BACKOFF_SECONDS)
                    else:
                        next_delay = float(REGISTRY_REREGISTER_INTERVAL_SECONDS)
                        backoff = float(REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS)
                except asyncio.CancelledError:
                    cancelled = True
                    raise
                except Exception as exc:
                    self._record_registry_registration_failure(
                        f"{type(exc).__name__}: {exc}",
                        backoff,
                    )
                    next_delay = backoff
                    backoff = min(backoff * 2, REGISTRY_REREGISTER_MAX_BACKOFF_SECONDS)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except BaseException as exc:
            self.state.registry_reregister_loop_exited = True
            self._refresh_registration_health()
            logger.critical(
                "Hermes Agency relay skill re-registration loop exited unexpectedly: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise
        finally:
            if not cancelled and self.state.started:
                self.state.registry_reregister_loop_exited = True
                self._refresh_registration_health()
                logger.critical("Hermes Agency relay skill re-registration loop exited unexpectedly")

    def _remember_incoming_record(self, record: IncomingTaskRecord) -> None:
        cfg = get_config()
        self._incoming_records[record.task_id] = record
        self._incoming_order.append(record.task_id)
        while len(self._incoming_order) > cfg.incoming_queue_limit:
            old_task_id = self._incoming_order.popleft()
            self._incoming_records.pop(old_task_id, None)
        self._refresh_incoming_state()

    async def _handle_incoming_task(self, task: Any) -> None:
        """Queue an incoming remote task and mark it working immediately."""

        message_text = self._message_text_from_incoming(task)
        control_payload = parse_control_message(message_text)
        if control_payload:
            control_result = handle_registration_message(control_payload) or handle_bid_message(control_payload)
            if control_result is None:
                control_result = {"ok": False, "ignored": True, "type": control_payload.get("type")}
            self._refresh_autonomous_state()
            try:
                if control_payload.get("type") == "registration":
                    agent = (control_payload.get("agent") or {}).get("name") if isinstance(control_payload.get("agent"), dict) else control_payload.get("peer_id")
                    announce_registration(agent or control_payload.get("peer_id"), str(control_payload.get("event") or "received"), peer_id=str(control_payload.get("peer_id") or ""))
                await task.complete(
                    artifacts=[
                        {
                            "artifact_id": f"agency-control-{getattr(task, 'task_id', 'unknown')}",
                            "name": "agency-control-ack",
                            "parts": [{"text": json.dumps(control_result, sort_keys=True, default=str)}],
                        }
                    ]
                )
            except Exception:
                pass
            return
        context_packet = parse_context_packet(message_text)
        metadata = self._metadata_to_dict(getattr(task, "metadata", None))
        sender_peer_id = str(getattr(task, "peer_id", "") or "").strip()
        sender_card = self._sender_card_to_dict(task)
        cfg = get_config()
        if sender_peer_id and not self._peer_allowed_by_effective_allowlist(cfg, sender_peer_id):
            reason = f"sender peer {sender_peer_id} is not in effective agency.relay.allowlist"
            try:
                await task.fail(reason)
            except Exception:
                pass
            logger.warning("Hermes Agency rejected incoming task: %s", reason)
            return
        try:
            verify_peer_tofu(
                cfg,
                sender_peer_id,
                card=sender_card,
                source="incoming_task",
            )
        except TrustError as exc:
            reason = str(exc)
            try:
                await task.fail(reason)
            except Exception:
                pass
            logger.warning("Hermes Agency rejected incoming task: %s", reason)
            return
        context_id = ""
        if context_packet:
            context_id = str(context_packet.get("context_id") or "").strip()
        if not context_id:
            context_id = str(metadata.get("context_id") or "").strip()
        if context_id:
            if context_packet is None:
                cfg = get_config()
                local_history = self._conversation_threads.get(context_id, [])
                ttl = max(0, int(cfg.incoming_conversation_ttl or 0))
                now = time.time()
                filtered_history = [
                    item
                    for item in local_history
                    if not ttl or now - float(item.get("created_at") or now) <= ttl
                ]
                context_text = build_conversation_context(
                    context_id,
                    max_turns=cfg.incoming_conversation_max_turns,
                    ttl=cfg.incoming_conversation_ttl,
                    local_history=filtered_history,
                )
                context_packet = {
                    "context_id": context_id,
                    "conversation_history": list(filtered_history) if context_text else [],
                }
            elif not context_packet.get("conversation_history"):
                cfg = get_config()
                local_history = self._conversation_threads.get(context_id, [])
                ttl = max(0, int(cfg.incoming_conversation_ttl or 0))
                now = time.time()
                filtered_history = [
                    item
                    for item in local_history
                    if not ttl or now - float(item.get("created_at") or now) <= ttl
                ]
                context_text = build_conversation_context(
                    context_id,
                    max_turns=cfg.incoming_conversation_max_turns,
                    ttl=cfg.incoming_conversation_ttl,
                    local_history=filtered_history,
                )
                if context_text:
                    context_packet["conversation_history"] = list(filtered_history)
        kanban_task_id = self._kanban_task_id_from_metadata(metadata, context_packet)
        record = IncomingTaskRecord(
            task_id=task.task_id,
            sender_peer_id=sender_peer_id,
            sender_card=sender_card,
            target_skill_id=getattr(task, "target_skill_id", ""),
            message_text=packet_goal_or_text(message_text),
            context_id=context_id,
            context_packet=context_packet,
            metadata=metadata,
            kanban_task_id=kanban_task_id,
        )
        self._remember_incoming_record(record)
        if not kanban_task_id:
            incoming_kanban = kanban_track_delegation(
                message=record.message_text,
                assigned_to=current_profile_name(),
                skills=[record.target_skill_id] if record.target_skill_id else [],
                a2a_task_id=record.task_id,
                metadata={
                    "direction": "incoming",
                    "sender_peer_id": record.sender_peer_id,
                    "receiver": current_profile_name(),
                    "target_skill_id": record.target_skill_id,
                    "context_id": record.context_id,
                    "message": record.message_text,
                },
                description=message_text,
            )
            if incoming_kanban.get("available") and incoming_kanban.get("task_id"):
                kanban_task_id = str(incoming_kanban["task_id"])
                record.kanban_task_id = kanban_task_id
        if kanban_task_id:
            kanban_update_task(kanban_task_id, status="running")
            kanban_add_comment(kanban_task_id, f"A2A task {record.task_id} received by {current_profile_name()} and queued for work.")
        try:
            try:
                await task.update_status("working")
            except Exception as exc:
                if not self._is_duplicate_working_transition(exc):
                    raise
            record.status = "queued"
            record.updated_at = time.time()
            if self._incoming_queue is None:
                raise RuntimeError("Incoming queue is not initialized")
            await self._incoming_queue.put((task, record.task_id))
            self._refresh_incoming_state()
        except Exception as exc:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
            record.updated_at = time.time()
            record.completed_at = time.time()
            if record.kanban_task_id:
                kanban_update_task(record.kanban_task_id, status="blocked", error=record.error)
            self._refresh_incoming_state()
            try:
                await task.fail(record.error)
            except Exception:
                pass

    def _safe_stub_response(self, record: IncomingTaskRecord) -> str:
        cfg = get_config()
        trusted = not cfg.trusted_peers or record.sender_peer_id in cfg.trusted_peers
        return (
            f"Hermes Agency safe stub on profile '{self.state.card_name or 'unknown'}' "
            f"received task {record.task_id} from {record.sender_peer_id or 'unknown peer'}.\n"
            f"Target skill: {record.target_skill_id or '(none)'}\n"
            f"Message:\n{record.message_text or '(empty)'}\n\n"
            "No Hermes tools, terminal commands, file edits, or live conversation injection were executed. "
            f"allow_remote_tasks={cfg.allow_remote_tasks}; trusted_peer={trusted}."
        )

    def _generate_response(self, record: IncomingTaskRecord) -> str:
        """Generate a conversational response based on the agent's profile."""
        card_name = self.state.card_name or "unknown"
        skill_count = self.state.skill_count

        # Build a response based on the message
        msg = record.message_text or ""
        response_parts = [
            f"Hi! I'm {card_name}, running as an Hermes Agency node on this machine.",
            f"I have {skill_count} skills installed.",
        ]

        # Try to answer common questions
        msg_lower = msg.lower()
        if "name" in msg_lower:
            response_parts.append(f"My name is {card_name}.")
        if "skill" in msg_lower:
            response_parts.append(f"I currently have {skill_count} skills available.")
        if "hear" in msg_lower or "there" in msg_lower:
            response_parts.append("Yes, I can hear you loud and clear! The P2P channel is working.")
        if "introduce" in msg_lower or "who are you" in msg_lower:
            response_parts.append(
                f"I'm {card_name}, an AI agent on a remote machine. "
                f"I talk to other agents via encrypted P2P relay."
            )

        return "\n".join(response_parts)

    async def _send_progress_update(self, task: Any, record: IncomingTaskRecord, text: str) -> None:
        message = str(text or "").strip()
        if not message:
            return
        timestamp = time.time()
        update = {"timestamp": timestamp, "text": message}
        record.progress_updates.append(update)
        record.updated_at = timestamp
        artifact = {
            "artifact_id": f"progress-{record.task_id}-{len(record.progress_updates)}",
            "name": "agency-progress-update",
            "metadata": {"agency_progress": True, "timestamp": timestamp},
            "parts": [{"text": message}],
        }
        if not hasattr(task, "send_artifact"):
            return
        await task.send_artifact([artifact])

    def _progress_callback_for_task(self, task: Any, record: IncomingTaskRecord):
        loop = asyncio.get_running_loop()

        def callback(text: str) -> None:
            future = asyncio.run_coroutine_threadsafe(
                self._send_progress_update(task, record, text),
                loop,
            )
            try:
                future.result(timeout=10)
            except Exception:
                pass

        return callback

    def _remember_conversation_turn(self, record: IncomingTaskRecord, response: str) -> None:
        context_id = str(record.context_id or "").strip()
        if not context_id:
            return
        cfg = get_config()
        thread = self._conversation_threads.setdefault(context_id, [])
        now = time.time()
        ttl = max(0, int(cfg.incoming_conversation_ttl or 0))
        if ttl:
            thread[:] = [
                item
                for item in thread
                if now - float(item.get("created_at") or now) <= ttl
            ]
        thread.append(
            {
                "task_id": record.task_id,
                "created_at": record.created_at,
                "user": record.message_text,
                "agent": response,
            }
        )
        max_turns = max(1, int(cfg.incoming_conversation_max_turns or 20))
        del thread[:-max_turns]

    async def _incoming_worker(self) -> None:
        """Process queued incoming tasks."""

        assert self._incoming_queue is not None
        while True:
            task, task_id = await self._incoming_queue.get()
            record = self._incoming_records.get(task_id)
            try:
                if record is None:
                    continue
                record.status = "processing"
                record.updated_at = time.time()
                if record.kanban_task_id:
                    kanban_update_task(record.kanban_task_id, status="running")
                announce_start(record.message_text)
                self._refresh_incoming_state()
                cfg = get_config()
                if not cfg.allow_remote_tasks:
                    response = self._safe_stub_response(record)
                elif cfg.incoming_mode in {"delegation", "subprocess"}:
                    try:
                        process_args = [record, cfg, self._generate_response]
                        process_kwargs = {}
                        if cfg.incoming_send_progress:
                            process_kwargs["progress_callback"] = self._progress_callback_for_task(
                                task,
                                record,
                            )
                        response = await asyncio.wait_for(
                            asyncio.to_thread(
                                process_incoming_task,
                                *process_args,
                                **process_kwargs,
                            ),
                            timeout=cfg.delegation_timeout,
                        )
                    except TimeoutError:
                        response = self._generate_response(record)
                else:
                    response = self._generate_response(record)
                # The daemon can deliver the WORKING status update and the
                # subsequent completion on adjacent ticks. A very short yield
                # keeps the receiver-side state machine from racing a just-sent
                # status update, which otherwise intermittently marks the task
                # FAILED before CompleteTask is accepted in bidirectional flows.
                await asyncio.sleep(0.05)
                try:
                    await task.complete(
                        artifacts=[
                            {
                                "artifact_id": f"safe-stub-{record.task_id}",
                                "name": "agency-safe-stub-response",
                                "parts": [{"text": response}],
                            }
                        ]
                    )
                except Exception as exc:
                    if not self._is_terminal_completed_error(exc):
                        raise
                record.status = "completed"
                record.result_text = response
                record.updated_at = time.time()
                record.completed_at = time.time()
                self._remember_conversation_turn(record, response)
                if record.kanban_task_id:
                    kanban_update_task(record.kanban_task_id, status="done", result=response)
                announce_complete(record.message_text, response, kanban_task_id=record.kanban_task_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if record is not None:
                    record.status = "failed"
                    record.error = f"{type(exc).__name__}: {exc}"
                    record.updated_at = time.time()
                    record.completed_at = time.time()
                    if record.kanban_task_id:
                        kanban_update_task(record.kanban_task_id, status="blocked", error=record.error)
                    announce_error(record.message_text, record.error, kanban_task_id=record.kanban_task_id)
                try:
                    await task.fail(record.error if record is not None else f"{type(exc).__name__}: {exc}")
                except Exception:
                    pass
            finally:
                self._incoming_queue.task_done()
                self._refresh_incoming_state()

    async def _start_impl(self) -> NodeState:
        if self._node is not None and self.state.started:
            return self.state

        cfg = get_config()
        self.state.config = cfg
        self.state.error = None
        self.state.last_status = None

        if cfg.home:
            cfg.home.mkdir(parents=True, exist_ok=True)

        try:
            from agentanycast import Node

            card = build_card()
            self._record_card_state(card)
            daemon_bin = _resolve_daemon_bin()
            if daemon_bin is not None:
                self._status_callback(f"Using Hermes Agency daemon binary: {daemon_bin}")
            if cfg.relay_security.token:
                # Current protected daemon builds do not expose a token flag, but
                # exporting this keeps plugin configuration forward-compatible
                # with token-aware daemon builds without touching SDK source.
                os.environ["AGENTANYCAST_RELAY_TOKEN"] = cfg.relay_security.token
            node = Node(
                card=card,
                relay=cfg.relay,
                home=cfg.home,
                daemon_bin=daemon_bin,
                status_callback=self._status_callback,
            )
            node.on_task(self._handle_incoming_task)
            await node.start()

            self._node = node
            self.state.started = True
            self.state.peer_id = node.peer_id
            self.state.last_peer_id = node.peer_id
            self.state.did_key = self._peer_id_to_did_key(node.peer_id)
            self.state.started_at = time.time()
            self.state.stopped_at = None
            self.state.error = None

            self._incoming_queue = asyncio.Queue()
            self._incoming_worker_task = asyncio.create_task(self._incoming_worker())
            self._serve_task = asyncio.create_task(node.serve_forever())
            self._serve_task.add_done_callback(self._serve_done)
            self.state.serve_task_running = True
            if cfg.team.auto_register:
                await register_agent(node, card, current_load=self._current_load())
                registration_result = await self._register_skills_with_registries(card)
                self._handle_registry_registration_result(
                    registration_result,
                    retry_in_seconds=float(REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS),
                )
                announce_registration(self.state.card_name or current_profile_name(), "registered", peer_id=self.state.peer_id)
            await self._refresh_team_context_impl(force=True)
            if cfg.team.auto_discover and self._team_refresh_task is None:
                self._team_refresh_task = asyncio.create_task(self._team_refresh_loop())
            if cfg.team.auto_register and self._registry_reregister_task is None:
                self.state.registry_reregister_loop_exited = False
                self._registry_reregister_task = asyncio.create_task(self._registry_reregister_loop())
                self._registry_reregister_task.add_done_callback(self._registry_reregister_done)
        except Exception as exc:
            self._node = None
            self._serve_task = None
            self.state.started = False
            self.state.peer_id = None
            self.state.serve_task_running = False
            self.state.error = f"{type(exc).__name__}: {exc}"
        return self.state

    async def _stop_impl(self) -> NodeState:
        try:
            if self._serve_task is not None and not self._serve_task.done():
                self._serve_task.cancel()
                await asyncio.gather(self._serve_task, return_exceptions=True)

            if self._incoming_worker_task is not None and not self._incoming_worker_task.done():
                self._incoming_worker_task.cancel()
                await asyncio.gather(self._incoming_worker_task, return_exceptions=True)

            if self._team_refresh_task is not None and not self._team_refresh_task.done():
                self._team_refresh_task.cancel()
                await asyncio.gather(self._team_refresh_task, return_exceptions=True)

            if self._registry_reregister_task is not None and not self._registry_reregister_task.done():
                self._registry_reregister_task.cancel()
                await asyncio.gather(self._registry_reregister_task, return_exceptions=True)

            if self._node is not None:
                try:
                    if get_config().team.auto_register:
                        await deregister_agent(self._node, card=build_card())
                        announce_registration(self.state.card_name or current_profile_name(), "deregistered", peer_id=self.state.peer_id)
                except Exception:
                    pass
                await self._node.stop()
        except Exception as exc:
            self.state.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._serve_task = None
            self._incoming_worker_task = None
            self._team_refresh_task = None
            self._registry_reregister_task = None
            self._incoming_queue = None
            self._node = None
            self._task_handles.clear()
            self.state.started = False
            self.state.peer_id = None
            self.state.serve_task_running = False
            self.state.next_retry_at = None
            self._refresh_registration_health()
            self.state.stopped_at = time.time()
            self._refresh_incoming_state()
        return self.state

    async def _list_peers_impl(self) -> list[dict[str, Any]]:
        if self._node is None or not self.state.started:
            return []
        return await self._node.list_peers()

    async def _discover_impl(
        self,
        skill: str,
        tags: dict[str, str] | None = None,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        await self._ensure_started_impl()
        assert self._node is not None
        return await self._node.discover(
            skill=skill,
            tags={str(k): str(v) for k, v in (tags or {}).items()} or None,
            limit=limit,
        )

    async def _send_task_impl(
        self,
        message: str,
        *,
        peer_id: str | None = None,
        skill: str | None = None,
        wait_seconds: float = 0,
        metadata: dict[str, str] | None = None,
        conversation_context: Any = None,
        context_id: str | None = None,
    ) -> dict[str, Any]:
        await self._ensure_started_impl()
        assert self._node is not None

        targets = sum(bool(item) for item in (peer_id, skill))
        if targets != 1:
            raise ValueError("Exactly one of peer_id or skill is required")

        cfg = get_config()
        if peer_id:
            if not self._peer_allowed_by_effective_allowlist(cfg, peer_id):
                raise PermissionError(f"target peer {peer_id} is not in effective agency.relay.allowlist")
            verify_peer_tofu(cfg, peer_id, source="outgoing_task")

        if isinstance(conversation_context, dict):
            packet_context = dict(conversation_context)
            if metadata:
                packet_context.setdefault("metadata", metadata)
        else:
            packet_context = {"summary": str(conversation_context or "").strip(), "metadata": metadata or {}}
        clean_context_id = str(context_id or packet_context.get("context_id") or "").strip()
        if clean_context_id:
            packet_context["context_id"] = clean_context_id
            packet_context.setdefault(
                "conversation_history",
                build_conversation_history(
                    clean_context_id,
                    os.getenv("HERMES_HOME") or os.path.expanduser("~/.hermes"),
                    max_turns=cfg.incoming_conversation_max_turns,
                    ttl=cfg.incoming_conversation_ttl,
                ),
            )
            metadata = dict(metadata or {})
            metadata.setdefault("context_id", clean_context_id)
        packet_context.setdefault("metadata", metadata or {})
        if clean_context_id:
            packet_context["metadata"].setdefault("context_id", clean_context_id)
            packet_context["metadata"].setdefault("message", message)
        packet_or_message = build_context_packet(message, packet_context)
        message_text = packet_to_message_text(packet_or_message)
        target_label = peer_id or skill or "unknown target"
        clean_metadata = {str(k): str(v) for k, v in (metadata or {}).items()} or None
        kanban_task_id = (clean_metadata or {}).get("kanban_task_id") or (clean_metadata or {}).get("agency_kanban_task_id")
        announce_delegate(message, target_label, kanban_task_id=kanban_task_id)
        payload = {"role": "user", "parts": [{"text": message_text}]}
        if isinstance(packet_or_message, dict):
            clean_metadata = dict(clean_metadata or {})
            clean_metadata.setdefault("agency_context_packet", "v1")
        kanban_metadata = {
            **(dict(clean_metadata or {})),
            "target_peer_id": peer_id,
            "target_skill": skill,
            "sender": current_profile_name(),
        }
        kanban_result = kanban_track_delegation(
            message=message,
            assigned_to=peer_id or None,
            skills=[skill] if skill else [],
            a2a_task_id=None,
            kanban_task_id=kanban_task_id,
            metadata=kanban_metadata,
            description=message_text,
        )
        if kanban_result.get("available") and kanban_result.get("task_id"):
            kanban_task_id = str(kanban_result["task_id"])
        try:
            handle = await self._node.send_task(
                message=payload,
                peer_id=peer_id,
                skill=skill,
                metadata=clean_metadata,
            )
        except Exception as exc:
            send_error = f"{type(exc).__name__}: {exc}"
            if kanban_task_id:
                kanban_update_task(kanban_task_id, status="blocked", error=send_error)
                kanban_add_comment(kanban_task_id, f"A2A task send failed before remote acceptance: {send_error}")
            announce_error(message, send_error, kanban_task_id=kanban_task_id)
            raise
        self._task_handles[handle.task_id] = handle
        kanban_result = kanban_track_delegation(
            message=message,
            assigned_to=peer_id or None,
            skills=[skill] if skill else [],
            a2a_task_id=handle.task_id,
            kanban_task_id=kanban_task_id,
            metadata=kanban_metadata,
            description=message_text,
        )
        if kanban_result.get("available") and kanban_result.get("task_id"):
            kanban_task_id = str(kanban_result["task_id"])

        wait_error: str | None = None
        wait_started_at = time.time()
        if wait_seconds and wait_seconds > 0:
            try:
                await handle.wait(timeout=wait_seconds)
            except Exception as exc:
                # Timeout or remote failure should not erase the task handle;
                # callers can still poll a2a_status for the latest state.
                wait_error = f"{type(exc).__name__}: {exc}"
                if kanban_task_id:
                    kanban_add_comment(kanban_task_id, f"A2A wait returned before completion: {wait_error}")
                announce_error(message, wait_error, kanban_task_id=kanban_task_id)

        data = self._serialize_handle(handle)
        if (
            wait_error
            and wait_seconds
            and peer_id
            and data.get("status") == "failed"
            and not data.get("artifact_text")
            and time.time() - wait_started_at < 2
        ):
            # A local daemon race can report an immediate artifact-free FAILED
            # state in bidirectional same-process flows even though a retry over
            # the same P2P return path succeeds milliseconds later. Retry once;
            # real remote work still surfaces as failed if the second attempt
            # fails or times out.
            await asyncio.sleep(0.5)
            handle = await self._node.send_task(
                message=payload,
                peer_id=peer_id,
                skill=skill,
                metadata=clean_metadata,
            )
            self._task_handles[handle.task_id] = handle
            kanban_result = kanban_track_delegation(
                message=message,
                assigned_to=peer_id or None,
                skills=[skill] if skill else [],
                a2a_task_id=handle.task_id,
                kanban_task_id=kanban_task_id,
                metadata={
                    **(dict(clean_metadata or {})),
                    "target_peer_id": peer_id,
                    "target_skill": skill,
                    "sender": current_profile_name(),
                    "retry_of": data.get("task_id"),
                },
                description=message_text,
            )
            wait_error = None
            try:
                await handle.wait(timeout=wait_seconds)
            except Exception as exc:
                wait_error = f"{type(exc).__name__}: {exc}"
                if kanban_task_id:
                    kanban_add_comment(kanban_task_id, f"A2A retry wait returned before completion: {wait_error}")
                announce_error(message, wait_error, kanban_task_id=kanban_task_id)
            data = self._serialize_handle(handle)
        if not wait_error and wait_seconds and wait_seconds > 0:
            result_text = data.get("artifact_text") or data.get("status") or "completed"
            if kanban_task_id:
                kanban_update_task(kanban_task_id, status="done", result=str(result_text))
            announce_complete(message, result_text, kanban_task_id=kanban_task_id)
        elif wait_error:
            if kanban_task_id:
                kanban_update_task(kanban_task_id, status="blocked", result=wait_error)
        elif kanban_task_id:
            kanban_update_task(kanban_task_id, status="running")
            kanban_add_comment(kanban_task_id, "A2A task sent, not waiting for completion")
        if isinstance(packet_or_message, dict):
            data["context_packet"] = packet_or_message
        data["kanban"] = kanban_result
        data["announcements"] = recent_announcements(limit=5)
        if wait_error:
            data["wait_error"] = wait_error
        return data

    async def _task_status_impl(self, task_id: str) -> dict[str, Any] | None:
        handle = self._task_handles.get(task_id)
        kanban = kanban_get_task(task_id)
        if handle is None:
            if kanban.get("available") and kanban.get("ok"):
                task = kanban.get("task", {})
                return {
                    "task_id": task_id,
                    "status": task.get("plugin_status") or task.get("status"),
                    "kanban_status": task.get("plugin_status") or task.get("status"),
                    "kanban_task_id": kanban.get("task_id"),
                    "result": task.get("result"),
                    "kanban": kanban,
                }
            return None
        data = self._serialize_handle(handle)
        if kanban.get("available"):
            data["kanban"] = kanban
        if kanban.get("available") and kanban.get("ok"):
            task = kanban.get("task", {})
            kanban_task_id = kanban.get("task_id")
            kanban_status = task.get("plugin_status") or task.get("status")
            if (
                data.get("status") == "completed"
                and data.get("artifact_text")
                and kanban_task_id
                and kanban_status not in {"done", "blocked", "failed"}
            ):
                # Fire-and-forget sends return to the caller before the remote
                # artifact arrives, so _send_task_impl intentionally leaves the
                # outbound Kanban task running. The next explicit status poll is
                # the safe reconciliation point: if the SDK handle now contains
                # the completion artifact, close the Kanban task with that result
                # and re-read it so a2a_status reflects board truth.
                updated = kanban_update_task(
                    str(kanban_task_id),
                    status="done",
                    result=str(data.get("artifact_text") or "completed"),
                )
                if updated.get("available") and updated.get("ok"):
                    kanban = kanban_get_task(str(kanban_task_id))
                    data["kanban"] = kanban
                    task = kanban.get("task", {}) if kanban.get("ok") else task
                    kanban_status = task.get("plugin_status") or task.get("status")
            if kanban_status:
                data["kanban_status"] = kanban_status
                data["kanban_task_id"] = kanban_task_id
            if kanban_status in {"done", "blocked", "failed"} and data.get("status") not in {"failed", "cancelled"}:
                data["a2a_status"] = data.get("status")
                data["status"] = kanban_status
                if task.get("result") is not None:
                    data["result"] = task.get("result")
        return data

    async def _incoming_tasks_impl(self, limit: int = 20) -> list[dict[str, Any]]:
        self._refresh_incoming_state()
        task_ids = list(self._incoming_order)[-max(1, limit):]
        return [
            self._incoming_records[task_id].as_dict()
            for task_id in reversed(task_ids)
            if task_id in self._incoming_records
        ]

    def _serve_done(self, task: asyncio.Task[None]) -> None:
        self.state.serve_task_running = False
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            self.state.error = f"serve_forever failed: {type(exc).__name__}: {exc}"

    def _registry_reregister_done(self, task: asyncio.Task[None]) -> None:
        """Record and restart any unexpected relay re-registration task exit."""

        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        self.state.registry_reregister_loop_exited = True
        self._refresh_registration_health()
        if exc is not None:
            self.state.error = f"registry re-registration loop failed: {type(exc).__name__}: {exc}"
            logger.critical(
                "Hermes Agency relay skill re-registration task exited; restarting: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        else:
            self.state.error = "registry re-registration loop exited unexpectedly"
            logger.critical("Hermes Agency relay skill re-registration task exited; restarting")
        if self.state.started and self._loop is not None and self._loop.is_running():
            self._registry_reregister_task = self._loop.create_task(self._registry_reregister_loop())
            self._registry_reregister_task.add_done_callback(self._registry_reregister_done)

    @staticmethod
    def _peer_id_to_did_key(peer_id: str) -> str | None:
        try:
            from agentanycast import peer_id_to_did_key

            return peer_id_to_did_key(peer_id)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public synchronous surface for Hermes tools/hooks
    # ------------------------------------------------------------------

    def start_sync(self, timeout: float = 120) -> NodeState:
        return self._submit(self._start_impl(), timeout=timeout)

    def stop_sync(self, timeout: float = 60) -> NodeState:
        try:
            return self._submit(self._stop_impl(), timeout=timeout)
        finally:
            self._stop_loop_if_idle()

    def list_peers_sync(self, timeout: float = 30) -> list[dict[str, Any]]:
        if not self.state.started:
            return []
        return self._submit(self._list_peers_impl(), timeout=timeout)

    def discover_sync(
        self,
        skill: str,
        tags: dict[str, str] | None = None,
        limit: int = 0,
        timeout: float = 60,
    ) -> list[dict[str, Any]]:
        return self._submit(self._discover_impl(skill, tags=tags, limit=limit), timeout=timeout)

    def send_task_sync(
        self,
        message: str,
        *,
        peer_id: str | None = None,
        skill: str | None = None,
        wait_seconds: float = 0,
        metadata: dict[str, str] | None = None,
        conversation_context: Any = None,
        context_id: str | None = None,
        timeout: float = 120,
    ) -> dict[str, Any]:
        effective_timeout = max(timeout, wait_seconds + 30 if wait_seconds else timeout)
        return self._submit(
            self._send_task_impl(
                message,
                peer_id=peer_id,
                skill=skill,
                wait_seconds=wait_seconds,
                metadata=metadata,
                conversation_context=conversation_context,
                context_id=context_id,
            ),
            timeout=effective_timeout,
        )

    def task_status_sync(self, task_id: str, timeout: float = 30) -> dict[str, Any] | None:
        return self._submit(self._task_status_impl(task_id), timeout=timeout)

    def incoming_tasks_sync(self, limit: int = 20, timeout: float = 30) -> list[dict[str, Any]]:
        if self._loop is None or not self._loop.is_running():
            self._refresh_incoming_state()
            task_ids = list(self._incoming_order)[-max(1, limit):]
            return [
                self._incoming_records[task_id].as_dict()
                for task_id in reversed(task_ids)
                if task_id in self._incoming_records
            ]
        return self._submit(self._incoming_tasks_impl(limit=limit), timeout=timeout)

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
        """Update a local orchestrator task record."""

        record = self._orchestrator_tasks.get(task_id)
        if record is None:
            return None
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
        if record.status in {"completed", "failed", "escalated", "cancelled"} and record.completed_at is None:
            record.completed_at = time.time()
        record.updated_at = time.time()
        self._refresh_orchestrator_state()
        return record.as_dict()

    def orchestrator_task_sync(self, task_id: str) -> dict[str, Any] | None:
        record = self._orchestrator_tasks.get(task_id)
        return record.as_dict() if record is not None else None

    def orchestrator_tasks_sync(self, limit: int = 50) -> list[dict[str, Any]]:
        self._refresh_orchestrator_state()
        task_ids = list(self._orchestrator_order)[-max(1, limit):]
        return [
            self._orchestrator_tasks[task_id].as_dict()
            for task_id in reversed(task_ids)
            if task_id in self._orchestrator_tasks
        ]

    def start_background(self) -> None:
        """Kick off startup without blocking the caller.

        Used by plugin lifecycle hooks. If startup fails, ``state.error`` is
        populated by ``_background_start_done``.
        """

        if self.state.started or self._start_future is not None:
            return
        loop = self._ensure_loop()
        self._start_future = asyncio.run_coroutine_threadsafe(self._start_impl(), loop)
        self._start_future.add_done_callback(self._background_start_done)

    def stop_background(self) -> None:
        if not self.state.started and self._node is None:
            return
        try:
            self.stop_sync(timeout=60)
        except Exception as exc:
            self.state.error = f"{type(exc).__name__}: {exc}"

    def _background_start_done(self, future: Any) -> None:
        self._start_future = None
        try:
            future.result()
        except Exception as exc:
            self.state.error = f"{type(exc).__name__}: {exc}"

    def compact_info(self) -> dict[str, Any]:
        """Return a small health-only status payload safe for frequent checks."""

        self.state.config = get_config()
        if self._serve_task is not None:
            self.state.serve_task_running = not self._serve_task.done()
        self._refresh_incoming_state()
        self._refresh_orchestrator_state()
        self._refresh_autonomous_state()
        registration = self._registration_health_dict()
        return {
            "ok": self.state.error is None,
            "node_started": self.state.started,
            "peer_id": self.state.peer_id,
            "card_name": self.state.card_name,
            "serve_task_running": self.state.serve_task_running,
            "registration": {
                "healthy": registration["registration_healthy"],
                "last_registration_time": registration["last_registration_time"],
                "consecutive_failures": registration["consecutive_failures"],
                "next_retry_at": registration["next_retry_at"],
                "loop_running": registration["loop_running"],
                "loop_exited": registration["registry_reregister_loop_exited"],
                "healthy_window_seconds": registration["healthy_window_seconds"],
                "normal_interval_seconds": registration["normal_interval_seconds"],
            },
            "team": {
                "peer_count": self.state.team_peer_count,
                "last_refresh": self.state.team_last_refresh,
                "last_error": self.state.team_last_error,
            },
            "relay_security": {
                "allowlist_configured": bool(self.state.config.relay_security.allowlist),
                "effective_allowlist_count": len(self.effective_relay_allowlist(self.state.config)),
                "auto_allow_team": self.state.config.relay_security.auto_allow_team,
                "token_configured": bool(self.state.config.relay_security.token),
            },
            "trust": {
                "store_path": str(self.state.config.trust.store_path) if self.state.config.trust.store_path else None,
                "tofu": self.state.config.trust.tofu,
                "peer_count": len(store_for_config(self.state.config).list_peers()),
            },
            "incoming": {
                "total": self.state.incoming_task_count,
                "queued": self.state.incoming_queue_size,
                "processing": self.state.incoming_processing_count,
                "completed": self.state.incoming_completed_count,
                "failed": self.state.incoming_failed_count,
            },
        }

    def info(self) -> dict[str, Any]:
        self.state.config = get_config()
        if self._serve_task is not None:
            self.state.serve_task_running = not self._serve_task.done()
        self._refresh_incoming_state()
        self._refresh_orchestrator_state()
        self._refresh_team_state_fields()
        self._refresh_autonomous_state()
        data = self.state.as_dict()
        data["relay_security"] = {
            **self.state.config.relay_security.as_dict(),
            "effective_allowlist": self.effective_relay_allowlist(self.state.config),
        }
        data["trust"] = trust_summary(self.state.config)
        data["team"] = get_team_state().as_dict()
        registration_data = get_registration_state().as_dict()
        registration_data["registry_refresh"] = self._registration_health_dict()
        data["registration"] = registration_data
        data["bidding"] = get_bidding_state().as_dict()
        data["learning_corrections"] = correction_history(limit=10)
        data["orchestrator_tasks"] = self.orchestrator_tasks_sync(limit=20)
        data["announcements"] = recent_announcements(limit=10)
        return data

    def auto_start_if_configured(self) -> None:
        cfg = get_config()
        self.state.config = cfg
        if cfg.enabled and (cfg.auto_start or cfg.team.auto_discover):
            self.start_background()

    def cached_team_context(self) -> str:
        """Return the current cached team-context block, refreshing state fields first."""

        self.state.config = get_config()
        cfg = self.state.config
        team_state = get_team_state()
        stale = (
            team_state.last_refresh is None
            or time.time() - team_state.last_refresh > max(60, cfg.team.context_refresh_minutes * 60)
        )
        if self.state.started and cfg.team.auto_discover and stale and self._loop is not None and self._loop.is_running():
            try:
                self._submit(self._refresh_team_context_impl(force=True), timeout=10)
            except Exception as exc:
                self.state.team_last_error = f"{type(exc).__name__}: {exc}"
        self._refresh_team_state_fields()
        return self.state.team_context

    def cached_orchestrator_context(self) -> str:
        """Return enhanced context for the promoted orchestrator profile."""

        cfg = get_config()
        self.state.config = cfg
        if not is_current_orchestrator(cfg):
            return ""
        team_state = get_team_state()
        kanban_tasks_result = kanban_list_tasks({"limit": 12, "include_archived": False, "sort": "created-desc"})
        tasks = kanban_tasks_result.get("tasks") if kanban_tasks_result.get("available") else self.orchestrator_tasks_sync(limit=12)
        lines = [
            "Hermes Agency orchestrator context:",
            f"Current orchestrator profile: {current_profile_name()}",
            f"Tenant: {cfg.team.tenant}",
            f"Bidding enabled: {cfg.team.bidding}; proactive enabled: {cfg.team.proactive}; learning enabled: {cfg.team.learning}",
            "You are promoted as the routing layer. Decompose complex work and delegate; do not do routed subtasks yourself unless Kyle explicitly asks.",
        ]
        if cfg.routing:
            lines.append("Configured routing hints (advisory, not hard rules):")
            for key, value in sorted(cfg.routing.items()):
                lines.append(f"- {key}: {value}")
        else:
            lines.append("Configured routing hints: none.")
        if team_state.peers:
            lines.append("Full team capability map:")
            for peer in sorted(team_state.peers.values(), key=lambda item: (item.card_name or item.name or item.peer_id).lower()):
                label = peer.card_name or peer.name or f"{peer.peer_id[:20]}... (skills unknown)"
                lines.append(f"- {label} — peer_id: {peer.peer_id}")
                description = peer.card_description or peer.description
                if description:
                    lines.append(f"  Description: {description}")
                skills = peer.card_skills or peer.skills
                if skills:
                    skill_text = ", ".join(
                        f"{skill.get('id', '')}" + (f" ({skill.get('description')})" if skill.get("description") else "")
                        for skill in skills
                        if skill.get("id")
                    )
                    lines.append(f"  Skills: {skill_text}")
                else:
                    lines.append("  Skills: unknown from peer discovery.")
        else:
            lines.append("Full team capability map: no peers currently discovered.")
        if kanban_tasks_result.get("available"):
            lines.append("Current Kanban state: available; Kanban is the source of truth for Hermes Agency work.")
        else:
            lines.append("Current Kanban state: unavailable; using local orchestrator state fallback.")
        if tasks:
            lines.append("Recent Kanban/local task history:")
            for task in tasks:
                lines.append(
                    f"- {task.get('id') or task.get('task_id')} [{task.get('plugin_status') or task.get('status')}] {task.get('title') or task.get('description')} -> {task.get('assignee') or task.get('target_agent') or 'unassigned'}"
                )
        else:
            lines.append("Recent local task history: none.")
        policy_read = check_autonomy("read", current_profile_name())
        policy_deploy = check_autonomy("deploy", current_profile_name())
        lines.append(f"Autonomy policy examples: read={policy_read['decision']}; deploy={policy_deploy['decision']}.")
        corrections = correction_history(limit=5)
        if corrections:
            lines.append("Recent routing corrections to consider:")
            for item in corrections:
                lines.append(f"- {item.get('task_type')}: avoid {item.get('wrong_target')} -> prefer {item.get('correct_target')}")
        lines.append(
            "Use orch_decompose for complex work, orch_route to delegate via A2A, orch_status/orch_list_tasks for Kanban-backed tracking, and orch_escalate when no suitable/reachable agent exists."
        )
        return "\n".join(lines)

    def _atexit_stop(self) -> None:
        self.stop_background()


manager = NodeManager()


def start_node() -> NodeState:
    """Start the active Hermes profile's Hermes Agency node synchronously."""

    return manager.start_sync()


def stop_node() -> NodeState:
    """Stop the active Hermes profile's Hermes Agency node synchronously."""

    return manager.stop_sync()
