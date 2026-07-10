"""Lifecycle manager for a per-profile Hermes Agency node.

Phase 3 owns the runtime lifecycle:

- create an Hermes Agency transport node from the generated profile AgentCard
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
import logging
import os
import sys
import threading
import time
from collections import deque
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
from .bidding import get_bidding_state, handle_bid_message
from .card_builder import build_card, card_to_dict
from .config import (
    AgencyConfig,
    add_peer_to_relay_allowlist,
    current_profile_name,
    get_config,
    is_current_orchestrator,
)
from .context_packet import (
    build_context_packet,
    packet_goal_or_text,
    packet_to_message_text,
    parse_context_packet,
)
from .conversation import build_conversation_context, build_conversation_history
from .incoming_queue import IncomingQueueMixin, IncomingTaskRecord
from .incoming_security import extract_sender_peer_id, verify_incoming_sender
from .kanban_bridge import add_comment as kanban_add_comment
from .kanban_bridge import get_task as kanban_get_task
from .kanban_bridge import list_tasks as kanban_list_tasks
from .kanban_bridge import track_delegation as kanban_track_delegation
from .kanban_bridge import update_task as kanban_update_task
from .kanban_sync import KanbanSyncMixin
from .learning import correction_history
from .node_lifecycle import NodeLifecycleMixin
from .orchestrator_state import (
    OrchestratorStateMixin,
    OrchestratorSubtaskRecord,
    OrchestratorTaskRecord,
)
from .policy import check_autonomy
from .registration import (
    deregister_agent,
    get_registration_state,
    handle_registration_message,
    parse_control_message,
    register_agent,
)
from .registry_client import (
    REGISTRY_HEALTHY_WINDOW_SECONDS,
    REGISTRY_REREGISTER_FAILURE_LOG_EVERY,
    REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS,
    REGISTRY_REREGISTER_INTERVAL_SECONDS,
    REGISTRY_REREGISTER_MAX_BACKOFF_SECONDS,
    RegistryClientMixin,
    _registry_addresses,
)
from .task_processor import process_incoming_task
from .team_context import get_team_state, visible_team_state
from .team_discovery import TeamDiscoveryMixin
from .trust import (
    handle_peer_handshake,
    handshake_due,
    record_peer_handshake_attempt,
    store_for_config,
    trust_peer_for_handshake,
    trust_summary,
    verify_peer_tofu,
)

__all__ = [
    "IncomingTaskRecord",
    "NodeManager",
    "NodeState",
    "OrchestratorSubtaskRecord",
    "OrchestratorTaskRecord",
    "REGISTRY_HEALTHY_WINDOW_SECONDS",
    "REGISTRY_REREGISTER_FAILURE_LOG_EVERY",
    "REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS",
    "REGISTRY_REREGISTER_INTERVAL_SECONDS",
    "REGISTRY_REREGISTER_MAX_BACKOFF_SECONDS",
    "add_peer_to_relay_allowlist",
    "announce_complete",
    "announce_delegate",
    "announce_error",
    "announce_registration",
    "announce_start",
    "build_card",
    "build_context_packet",
    "build_conversation_context",
    "build_conversation_history",
    "card_to_dict",
    "check_autonomy",
    "current_profile_name",
    "deregister_agent",
    "extract_sender_peer_id",
    "handle_bid_message",
    "handle_peer_handshake",
    "handle_registration_message",
    "handshake_due",
    "is_current_orchestrator",
    "kanban_add_comment",
    "kanban_get_task",
    "kanban_list_tasks",
    "kanban_track_delegation",
    "kanban_update_task",
    "manager",
    "packet_goal_or_text",
    "packet_to_message_text",
    "parse_context_packet",
    "parse_control_message",
    "process_incoming_task",
    "record_peer_handshake_attempt",
    "register_agent",
    "start_node",
    "stop_node",
    "trust_peer_for_handshake",
    "verify_incoming_sender",
    "verify_peer_tofu",
    "_registry_addresses",
]


logger = logging.getLogger(__name__)

STARTUP_TEAM_REFRESH_TIMEOUT_SECONDS = 15.0


_TRANSPORT_BACKEND_ALIASES = {
    "agent-anycast": "agentanycast",
    "agent_anycast": "agentanycast",
    "anycast": "agentanycast",
}


def _normalize_transport_backend(value: Any) -> str:
    """Normalize configured transport backend with AgentAnycast fallback."""

    backend = str(value or "agentanycast").strip().lower()
    backend = _TRANSPORT_BACKEND_ALIASES.get(backend, backend)
    if backend not in {"agentanycast", "keryx"}:
        logger.warning(
            "Unsupported agency.transport_backend=%r; falling back to agentanycast", value
        )
        return "agentanycast"
    return backend


def _transport_backend_for_config(cfg: AgencyConfig | None = None) -> str:
    """Return the configured transport backend for ``cfg`` or current config."""

    try:
        active_cfg = cfg or get_config()
        return _normalize_transport_backend(
            getattr(active_cfg, "transport_backend", "agentanycast")
        )
    except Exception:
        logger.debug("Failed to load Agency transport backend from config", exc_info=True)
        return "agentanycast"


def _configure_keryx_environment(cfg: AgencyConfig) -> None:
    """Expose Agency Keryx config through the env vars expected by the SDK."""

    keryx_cfg = getattr(cfg, "keryx", None)
    mappings = {
        "daemon_endpoint": "HERMES_KERYX_DAEMON_ENDPOINT",
        "registry_endpoint": "HERMES_KERYX_REGISTRY_ENDPOINT",
        "relay_endpoint": "HERMES_KERYX_RELAY_ENDPOINT",
        "worker_id": "HERMES_KERYX_WORKER_ID",
        "default_lease_duration_ms": "HERMES_KERYX_DEFAULT_LEASE_DURATION_MS",
        "request_timeout_ms": "HERMES_KERYX_REQUEST_TIMEOUT_MS",
    }
    for attr, env_name in mappings.items():
        value = getattr(keryx_cfg, attr, None)
        if value is None or value == "":
            continue
        os.environ.setdefault(env_name, str(value))


def _build_card_for_transport(backend: str) -> Any:
    """Build the profile card using the classes for the selected transport."""

    if backend != "keryx":
        return build_card(lazy=True)

    # card_builder imports AgentCard/Skill from agentanycast locally.  Under
    # Keryx, expose the AgentAnycast-compatible Keryx package only while the
    # card is constructed so existing AgentAnycast installs are not globally
    # overwritten after startup.
    import keryx

    had_previous = "agentanycast" in sys.modules
    previous = sys.modules.get("agentanycast")
    sys.modules["agentanycast"] = keryx
    try:
        return build_card(lazy=True)
    finally:
        if not had_previous:
            sys.modules.pop("agentanycast", None)
        elif previous is not None:
            sys.modules["agentanycast"] = previous


def _resolve_transport_node_class(cfg: AgencyConfig) -> tuple[type[Any], str]:
    """Return the configured SDK node class and effective backend name."""

    backend = _transport_backend_for_config(cfg)
    if backend == "keryx":
        try:
            _configure_keryx_environment(cfg)
            from keryx.node import KeryxNode

            return KeryxNode, "keryx"
        except Exception:
            logger.warning(
                "Keryx transport requested but SDK unavailable; falling back to agentanycast",
                exc_info=True,
            )

    from keryx import KeryxNode as Node

    return Node, "agentanycast"


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
    incoming_queue_max_size: int = 100
    incoming_dropped_count: int = 0
    incoming_processing_count: int = 0
    incoming_completed_count: int = 0
    incoming_failed_count: int = 0
    last_incoming_activity_at: float | None = None
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
            "incoming_queue_max_size": self.incoming_queue_max_size,
            "incoming_dropped_count": self.incoming_dropped_count,
            "incoming_processing_count": self.incoming_processing_count,
            "incoming_completed_count": self.incoming_completed_count,
            "incoming_failed_count": self.incoming_failed_count,
            "last_incoming_activity_at": self.last_incoming_activity_at,
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


class NodeManager(
    IncomingQueueMixin,
    RegistryClientMixin,
    TeamDiscoveryMixin,
    KanbanSyncMixin,
    OrchestratorStateMixin,
    NodeLifecycleMixin,
):
    """Singleton wrapper around a profile-scoped Hermes Agency Node."""

    def _nm(self):
        """Return the live node_manager module so mixins see monkeypatched facade names."""

        return sys.modules[self.__class__.__module__]

    def __init__(self) -> None:
        self._node: Any | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._incoming_queue: asyncio.Queue[Any] | None = None
        self._incoming_worker_task: asyncio.Task[None] | None = None
        self._team_refresh_task: asyncio.Task[None] | None = None
        self._registry_reregister_task: asyncio.Task[None] | None = None
        self._incoming_records: dict[str, IncomingTaskRecord] = {}
        self._incoming_order: deque[str] = deque()
        self._queued_incoming_task_ids: set[str] = set()
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

    def _update_pool_roster_status(self, *, online: bool, error: str | None = None) -> None:
        """Best-effort roster overlay update for profile start/stop events."""

        try:
            from .pool.roster import update_agent_status

            update_agent_status(
                current_profile_name(), online=online, peer_id=self.state.peer_id, error=error
            )
        except Exception:
            return

    def start_sync(self, timeout: float = 120) -> Any:
        state = super().start_sync(timeout=timeout)
        self._update_pool_roster_status(
            online=bool(getattr(state, "started", False) and not getattr(state, "error", None)),
            error=getattr(state, "error", None),
        )
        return state

    def stop_sync(self, timeout: float = 60) -> Any:
        state = super().stop_sync(timeout=timeout)
        self._update_pool_roster_status(online=False, error=getattr(state, "error", None))
        return state

    def _build_transport_node_kwargs(
        self,
        *,
        cfg: AgencyConfig,
        backend: str,
        card: Any,
    ) -> dict[str, Any]:
        """Build constructor kwargs for the configured transport backend."""

        kwargs: dict[str, Any] = {
            "card": card,
            "home": cfg.home,
            "status_callback": self._status_callback,
        }
        if backend == "keryx":
            keryx_cfg = getattr(cfg, "keryx", None)
            daemon_addr = getattr(keryx_cfg, "daemon_endpoint", None)
            registry_endpoint = getattr(keryx_cfg, "registry_endpoint", None)
            relay = getattr(keryx_cfg, "relay_endpoint", None) or cfg.relay
            if relay:
                kwargs["relay"] = relay
            if daemon_addr:
                kwargs["daemon_addr"] = daemon_addr
            if registry_endpoint:
                kwargs["registry_endpoint"] = registry_endpoint
            kwargs["transport"] = "keryx"
            kwargs["namespace"] = cfg.team.tenant
            endpoint_label = daemon_addr or "default daemon endpoint"
            self._status_callback(f"Using Hermes Agency Keryx transport: {endpoint_label}")
            return kwargs

        daemon_bin = self._nm()._resolve_daemon_bin()
        if daemon_bin is not None:
            self._status_callback(f"Using Hermes Agency daemon binary: {daemon_bin}")
        if cfg.relay_security.token:
            # Current protected daemon builds do not expose a token flag, but
            # exporting this keeps plugin configuration forward-compatible with
            # token-aware daemon builds without touching SDK source.
            os.environ["AGENTANYCAST_RELAY_TOKEN"] = cfg.relay_security.token
        kwargs.update(
            {
                "relay": cfg.relay,
                "daemon_bin": daemon_bin,
            }
        )
        return kwargs

    async def _start_impl(self) -> Any:
        """Start the configured Agency transport node on the lifecycle loop."""

        if self._node is not None and self.state.started:
            self._register_incoming_handler(self._node)
            self._ensure_incoming_runtime(self._nm().get_config())
            if self._serve_task is None or self._serve_task.done():
                self._serve_task = asyncio.create_task(self._node.serve_forever())
                self._serve_task.add_done_callback(self._serve_done)
                self.state.serve_task_running = True
            return self.state

        cfg = self._nm().get_config()
        self.state.config = cfg
        self.state.error = None
        self.state.last_status = None

        if cfg.home:
            cfg.home.mkdir(parents=True, exist_ok=True)

        try:
            node_cls, backend = _resolve_transport_node_class(cfg)
            card = _build_card_for_transport(backend)
            self._record_card_state(card)
            node = node_cls(
                **self._build_transport_node_kwargs(cfg=cfg, backend=backend, card=card)
            )
            await node.start()
            self._register_incoming_handler(node)

            self._node = node
            self.state.started = True
            self.state.peer_id = node.peer_id
            self.state.last_peer_id = node.peer_id
            self.state.did_key = self._peer_id_to_did_key(node.peer_id)
            self.state.started_at = time.time()
            self.state.stopped_at = None
            self.state.error = None

            self._ensure_incoming_runtime(cfg)
            self._requeue_persisted_incoming_tasks()
            self._serve_task = asyncio.create_task(node.serve_forever())
            self._serve_task.add_done_callback(self._serve_done)
            self.state.serve_task_running = True
            if cfg.team.auto_register:
                await self._nm().register_agent(node, card, current_load=self._current_load())
                registration_result = await self._register_skills_with_registries(card)
                self._handle_registry_registration_result(
                    registration_result,
                    retry_in_seconds=float(self._nm().REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS),
                )
                self._nm().announce_registration(
                    self.state.card_name or self._nm().current_profile_name(),
                    "registered",
                    peer_id=self.state.peer_id,
                )
            try:
                await asyncio.wait_for(
                    self._refresh_team_context_impl(force=True),
                    timeout=STARTUP_TEAM_REFRESH_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                self.state.team_last_error = (
                    "startup team context refresh timed out; continuing node startup"
                )
                logger.warning(
                    "Hermes Agency startup team context refresh timed out after %.1fs; "
                    "continuing node startup",
                    STARTUP_TEAM_REFRESH_TIMEOUT_SECONDS,
                )
            if cfg.team.auto_discover and self._team_refresh_task is None:
                self._team_refresh_task = asyncio.create_task(self._team_refresh_loop())
            if (
                backend in {"agentanycast", "keryx"}
                and cfg.team.auto_register
                and self._registry_reregister_task is None
            ):
                self.state.registry_reregister_loop_exited = False
                self._registry_reregister_task = asyncio.create_task(
                    self._registry_reregister_loop()
                )
                self._registry_reregister_task.add_done_callback(self._registry_reregister_done)
        except Exception as exc:
            self._node = None
            self._serve_task = None
            self.state.started = False
            self.state.peer_id = None
            self.state.serve_task_running = False
            self.state.error = f"{type(exc).__name__}: {exc}"
        return self.state

    async def _stop_impl(self) -> Any:
        """Stop whichever transport node is active and tear down runtime tasks."""

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

            if (
                self._registry_reregister_task is not None
                and not self._registry_reregister_task.done()
            ):
                self._registry_reregister_task.cancel()
                await asyncio.gather(self._registry_reregister_task, return_exceptions=True)

            if self._node is not None:
                try:
                    if self._nm().get_config().team.auto_register:
                        card = getattr(self._node, "card", None)
                        if _transport_backend_for_config(self.state.config) == "keryx" and hasattr(
                            self._node, "deregister_skills"
                        ):
                            await self._node.deregister_skills(card)
                        await self._nm().deregister_agent(self._node, card=card)
                        self._nm().announce_registration(
                            self.state.card_name or self._nm().current_profile_name(),
                            "deregistered",
                            peer_id=self.state.peer_id,
                        )
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
            self._queued_incoming_task_ids.clear()
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

    @staticmethod
    def _peer_id_to_did_key(peer_id: str) -> str | None:
        try:
            if _transport_backend_for_config() == "keryx":
                from keryx import peer_id_to_did_key
            else:
                from keryx import peer_id_to_did_key

            return peer_id_to_did_key(peer_id)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Dedicated event loop plumbing
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Lifecycle implementation (runs on the dedicated event loop)
    # ------------------------------------------------------------------

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
        return data.get("name") == "agency-progress-update" or str(
            metadata.get("agency_progress") or ""
        ).lower() in {"1", "true", "yes"}

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
            "artifacts": [
                cls._serialize_artifact(item) for item in getattr(handle, "artifacts", [])
            ],
        }

    def _refresh_autonomous_state(self) -> None:
        reg_state = get_registration_state()
        bid_state = get_bidding_state()
        self.state.registration_count = len(
            [item for item in reg_state.registrations.values() if item.alive]
        )
        self.state.bidding_request_count = len(bid_state.requests)
        self.state.bidding_bid_count = sum(len(items) for items in bid_state.bids.values())

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

    # ------------------------------------------------------------------
    # Public synchronous surface for Hermes tools/hooks
    # ------------------------------------------------------------------

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
            task_ids = list(self._incoming_order)[-max(1, limit) :]
            return [
                self._incoming_records[task_id].as_dict()
                for task_id in reversed(task_ids)
                if task_id in self._incoming_records
            ]
        return self._submit(self._incoming_tasks_impl(limit=limit), timeout=timeout)

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
                "store_path": str(self.state.config.trust.store_path)
                if self.state.config.trust.store_path
                else None,
                "tofu": self.state.config.trust.tofu,
                "peer_count": len(store_for_config(self.state.config).list_peers()),
            },
            "incoming": {
                "total": self.state.incoming_task_count,
                "queued": self.state.incoming_queue_size,
                "max_queue_size": self.state.incoming_queue_max_size,
                "dropped": self.state.incoming_dropped_count,
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
        data["team"] = visible_team_state(self.state.config)
        registration_data = get_registration_state().as_dict()
        registration_data["registry_refresh"] = self._registration_health_dict()
        data["registration"] = registration_data
        data["bidding"] = get_bidding_state().as_dict()
        data["learning_corrections"] = correction_history(limit=10)
        data["orchestrator_tasks"] = self.orchestrator_tasks_sync(limit=20)
        data["announcements"] = recent_announcements(limit=10)
        return data

    def cached_team_context(self) -> str:
        """Return the current cached team-context block, refreshing state fields first."""

        self.state.config = get_config()
        cfg = self.state.config
        team_state = get_team_state()
        stale = team_state.last_refresh is None or time.time() - team_state.last_refresh > max(
            60, cfg.team.context_refresh_minutes * 60
        )
        if (
            self.state.started
            and cfg.team.auto_discover
            and stale
            and self._loop is not None
            and self._loop.is_running()
        ):
            try:
                self._submit(self._refresh_team_context_impl(force=True), timeout=10)
            except Exception as exc:
                self.state.team_last_error = f"{type(exc).__name__}: {exc}"
        self._refresh_team_state_fields()
        return self.state.team_context


manager = NodeManager()


def start_node() -> NodeState:
    """Start the active Hermes profile's Hermes Agency node synchronously."""

    return manager.start_sync()


def stop_node() -> NodeState:
    """Stop the active Hermes profile's Hermes Agency node synchronously."""

    return manager.stop_sync()
