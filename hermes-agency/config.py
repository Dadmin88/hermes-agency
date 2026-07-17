"""Configuration helpers for the Hermes Agency Hermes plugin.

Config schema and defaults::

    agency:
      enabled: true               # plugin-level runtime gate; plugin loading remains opt-in
      transport_backend: keryx    # primary transport; agentanycast is legacy fallback
      relay: null                 # legacy AgentAnycast relay multiaddr for rollback
      auto_start: false           # true = start node on session start
      skills_from_profile: true   # auto-generate AgentCard skills from installed Hermes skills
      allow_remote_tasks: false   # false = safe stub; true = process according to incoming.mode
      incoming:
        mode: delegation          # template, delegation, subprocess
        delegation_timeout: 600   # seconds allowed for delegated specialist reasoning
        max_queue_size: 100       # max queued inbound tasks before newest is rejected
        persist_queue: true       # persist incoming queue state across restarts
        queue_persistence_path: null # optional path (default: <agency.home>/incoming_queue.json)
        handler_timeout_seconds: 900 # max seconds one incoming worker handler may run
        tool_access: safe         # safe, full, none
        max_iterations: 25        # max subagent turns
        subprocess_profile: null  # optional Hermes profile override for subprocess fallback
        allow_subprocess: false   # true = permit remote tasks to use subprocess mode
        allow_subprocess_fallback: false # true = delegation failure may try subprocess
        min_subprocess_trust: full # minimum trust level required for subprocess
        allow_hooks_for_remote: false # true = set HERMES_ACCEPT_HOOKS=1 for remote subprocess
        reject_unmatched_skills: false  # true = fail if requested skill is not installed
        send_progress: false      # true = send intermediate A2A progress artifacts
        conversation_ttl: 3600    # seconds to preserve A2A conversation continuity
        conversation_max_turns: 20 # max previous turns to include
        idle_timeout_seconds: 120 # seconds a pool runner stays alive after last task
      workspace:
        root: null                # shared workspace root (default: <root-hermes-home>/.agency/workspace)
      proactive:
        enabled: false            # enable trigger-driven routing
        triggers: []              # file-watch, kanban-tag, blocker escalation definitions
      trusted_peers: []           # peer_id allowlist (future)
      incoming_queue_limit: 100   # max incoming task records to keep
      card_name: null             # optional display name for this node's AgentCard
      home: null                  # override daemon home dir (default: $HERMES_HOME/.agency)
      daemon_bin: null            # explicit daemon binary path; prevents SDK auto-download/overwrite
      keryx:
        daemon_endpoint: null     # e.g. unix:///tmp/keryx-daemon.sock or 127.0.0.1:50051
        registry_endpoint: null   # optional Keryx registry endpoint
        relay_endpoint: null      # diagnostics/compat only; live relay topology is owned by keryxd/keryx-relay
        relay_config: {}          # Keryx relay-specific config payload
        worker_id: null           # optional worker identity for daemon task leasing
        default_lease_duration_ms: 0
        request_timeout_ms: null
      relay:
        allowlist: []           # peer_ids allowed to reserve relay slots; empty = deny unless allow_all
        auto_allow_team: false  # auto-add discovered teammates only after local trust verification
        allow_all: false        # explicit allow-all for trusted dev/local networks
        token: null             # shared secret for relay allowlist/token control plane
      registry:
        allow_insecure_token_transport: false  # true = send registry token over insecure gRPC
      outbound:
        url_validation: warn      # warn or strict for send_task(url=...) SSRF checks
        url_allowlist: []         # optional URL/host patterns allowed for outbound HTTP bridge
      trust:
        store_path: null        # custom trust store path (default: $HERMES_HOME/agency/trust.json)
        tofu: true              # trust-on-first-use for new peers
      team:
        auto_discover: true
        inject_context: true
        kanban_integration: true
        self_serve: true
        announce_progress: false
        context_refresh_minutes: 5
        context_filter: agency-only # agency-only or all; agency-only hides personal profiles
        max_context_peers: 100    # max peers included in injected prompt context
        max_context_skills: 8     # max skills shown per peer in injected context
        context_max_chars: 20000  # hard character budget for injected context block
      kanban:
        preserve_workspaces: true # keep scratch task artifact dirs after completion
        board_cleanup_days: 7     # archive signed-off Agency boards older than this
      orchestrator:
        enabled: false
        agent: null
        auto_start: false          # true = active orchestrator may start its node on gateway/session startup
        auto_decompose: true
      pool:
        max_online_agents: 3       # cap pool-managed specialist runners; 0 = queue all wakes
        max_total_rss_mb: 2048     # cap total pool runner/daemon RSS before new wakes are queued
      moa:
        enabled: true             # Agency policy only; native presets remain under top-level moa:
        default_preset: null       # null = use native moa.default_preset
        allow_auto_moa: false      # recommend-only unless explicitly enabled
        require_confirmation: true # do not silently run high-leverage MoA
        kanban_tracking: true
        attach_trace_to_cards: true
        recommend_for_triggers:
          - architecture
          - security
          - release
          - destructive_change
          - blocker
      routing: {}
"""

from __future__ import annotations

import copy
import logging
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes_cli.config import cfg_get, load_config
from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)
_WARNED_EMPTY_ALLOWLIST_MIGRATION = False
_WORKSPACE_DIR_MODE = 0o700


_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "bearer",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
_REDACTED = "<redacted>"


def _is_secret_key(key: object) -> bool:
    normalized = str(key).replace("-", "_").lower()
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    return copy.deepcopy(value)


def _redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _REDACTED if _is_secret_key(key) else _redact_value(value)
        for key, value in mapping.items()
    }


@dataclass(frozen=True)
class RelaySecurityConfig:
    """Resolved relay-side security configuration."""

    allowlist: tuple[str, ...] = ()
    auto_allow_team: bool = False
    allow_all: bool = False
    token: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowlist": list(self.allowlist),
            "auto_allow_team": self.auto_allow_team,
            "allow_all": self.allow_all,
            "mode": "allow_all" if self.allow_all else "allowlist",
            "token_configured": bool(self.token),
        }


@dataclass(frozen=True)
class KeryxTransportConfig:
    """Resolved Keryx transport/runtime configuration."""

    daemon_endpoint: str | None = None
    registry_endpoint: str | None = None
    relay_endpoint: str | None = None
    relay_config: dict[str, Any] = field(default_factory=dict)
    worker_id: str | None = None
    default_lease_duration_ms: int = 0
    request_timeout_ms: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "daemon_endpoint": self.daemon_endpoint,
            "registry_endpoint": self.registry_endpoint,
            "relay_endpoint": self.relay_endpoint,
            "relay_config": _redact_mapping(self.relay_config),
            "worker_id": self.worker_id,
            "default_lease_duration_ms": self.default_lease_duration_ms,
            "request_timeout_ms": self.request_timeout_ms,
        }


@dataclass(frozen=True)
class TrustConfig:
    """Resolved peer trust configuration."""

    store_path: Path | None = None
    tofu: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"store_path": str(self.store_path) if self.store_path else None, "tofu": self.tofu}


@dataclass(frozen=True)
class TeamConfig:
    """Resolved team-collaboration configuration."""

    auto_discover: bool = True
    auto_register: bool = True
    inject_context: bool = True
    kanban_integration: bool = True
    self_serve: bool = True
    announce_progress: bool = False
    bidding: bool = False
    proactive: bool = False
    learning: bool = False
    tenant: str = "default"
    context_refresh_minutes: int = 5
    context_filter: str = "agency-only"
    max_context_peers: int = 100
    max_context_skills: int = 8
    context_max_chars: int = 20000

    def as_dict(self) -> dict[str, Any]:
        return {
            "auto_discover": self.auto_discover,
            "auto_register": self.auto_register,
            "inject_context": self.inject_context,
            "kanban_integration": self.kanban_integration,
            "self_serve": self.self_serve,
            "announce_progress": self.announce_progress,
            "bidding": self.bidding,
            "proactive": self.proactive,
            "learning": self.learning,
            "tenant": self.tenant,
            "context_refresh_minutes": self.context_refresh_minutes,
            "context_filter": self.context_filter,
            "max_context_peers": self.max_context_peers,
            "max_context_skills": self.max_context_skills,
            "context_max_chars": self.context_max_chars,
        }


@dataclass(frozen=True)
class WorkspaceConfig:
    """Resolved shared Agency workspace paths."""

    root: Path

    @property
    def deliverables(self) -> Path:
        return self.root / "deliverables"

    @property
    def scratch(self) -> Path:
        return self.root / "scratch"

    @property
    def shared(self) -> Path:
        return self.root / "shared"

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "deliverables": str(self.deliverables),
            "scratch": str(self.scratch),
            "shared": str(self.shared),
        }


@dataclass(frozen=True)
class OrchestratorConfig:
    """Resolved orchestrator-layer configuration."""

    enabled: bool = False
    agent: str | None = None
    auto_start: bool = False
    auto_decompose: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "agent": self.agent,
            "auto_start": self.auto_start,
            "auto_decompose": self.auto_decompose,
        }


@dataclass(frozen=True)
class PoolConfig:
    """Resolved pool/wake-on-demand safety configuration."""

    max_online_agents: int = 3
    max_total_rss_mb: int = 2048
    min_free_mem_mb: int = 2048
    idle_sleep_after_seconds: int = 300
    busy_recent_activity_seconds: int = 120
    allow_discovery_wake: bool = False
    allow_handshake_wake: bool = True
    allow_sleep_for_wake: bool = True
    allowed_wake_reasons: tuple[str, ...] = ("manual", "task", "handshake")
    permanent_agents: tuple[str, ...] = ("agency-orchestrator",)

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_online_agents": self.max_online_agents,
            "max_total_rss_mb": self.max_total_rss_mb,
            "min_free_mem_mb": self.min_free_mem_mb,
            "idle_sleep_after_seconds": self.idle_sleep_after_seconds,
            "busy_recent_activity_seconds": self.busy_recent_activity_seconds,
            "allow_discovery_wake": self.allow_discovery_wake,
            "allow_handshake_wake": self.allow_handshake_wake,
            "allow_sleep_for_wake": self.allow_sleep_for_wake,
            "allowed_wake_reasons": list(self.allowed_wake_reasons),
            "permanent_agents": list(self.permanent_agents),
        }


@dataclass(frozen=True)
class KanbanConfig:
    """Resolved Kanban integration configuration."""

    preserve_workspaces: bool = True
    board_cleanup_days: int = 7

    def as_dict(self) -> dict[str, Any]:
        return {
            "preserve_workspaces": self.preserve_workspaces,
            "board_cleanup_days": self.board_cleanup_days,
        }


@dataclass(frozen=True)
class AgencyMoAConfig:
    """Resolved Agency policy for native Hermes Agent MoA integration."""

    enabled: bool = True
    default_preset: str | None = None
    allow_auto_moa: bool = False
    require_confirmation: bool = True
    kanban_tracking: bool = True
    attach_trace_to_cards: bool = True
    recommend_for_triggers: tuple[str, ...] = (
        "architecture",
        "security",
        "release",
        "destructive_change",
        "blocker",
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "default_preset": self.default_preset,
            "allow_auto_moa": self.allow_auto_moa,
            "require_confirmation": self.require_confirmation,
            "kanban_tracking": self.kanban_tracking,
            "attach_trace_to_cards": self.attach_trace_to_cards,
            "recommend_for_triggers": list(self.recommend_for_triggers),
        }


@dataclass(frozen=True)
class IncomingConfig:
    """Resolved incoming-task LLM processing configuration."""

    mode: str = "delegation"
    delegation_timeout: int = 600
    max_queue_size: int = 100
    persist_queue: bool = True
    queue_persistence_path: Path | None = None
    handler_timeout_seconds: float = 900
    tool_access: str = "safe"
    max_iterations: int = 25
    subprocess_profile: str | None = None
    allow_subprocess: bool = False
    allow_subprocess_fallback: bool = False
    min_subprocess_trust: str = "full"
    allow_hooks_for_remote: bool = False
    reject_unmatched_skills: bool = False
    send_progress: bool = False
    conversation_ttl: int = 3600
    conversation_max_turns: int = 20
    idle_timeout_seconds: float = 120

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "delegation_timeout": self.delegation_timeout,
            "max_queue_size": self.max_queue_size,
            "persist_queue": self.persist_queue,
            "queue_persistence_path": str(self.queue_persistence_path)
            if self.queue_persistence_path
            else None,
            "handler_timeout_seconds": self.handler_timeout_seconds,
            "tool_access": self.tool_access,
            "max_iterations": self.max_iterations,
            "subprocess_profile": self.subprocess_profile,
            "allow_subprocess": self.allow_subprocess,
            "allow_subprocess_fallback": self.allow_subprocess_fallback,
            "min_subprocess_trust": self.min_subprocess_trust,
            "allow_hooks_for_remote": self.allow_hooks_for_remote,
            "reject_unmatched_skills": self.reject_unmatched_skills,
            "send_progress": self.send_progress,
            "conversation_ttl": self.conversation_ttl,
            "conversation_max_turns": self.conversation_max_turns,
            "idle_timeout_seconds": self.idle_timeout_seconds,
        }


@dataclass(frozen=True)
class OutboundConfig:
    """Resolved outbound HTTP bridge policy."""

    url_validation: str = "warn"
    url_allowlist: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "url_validation": self.url_validation,
            "url_allowlist": list(self.url_allowlist),
        }


@dataclass(frozen=True)
class SkillGovernanceConfig:
    """Disabled-by-default Agency shared-skill governance settings."""

    enabled: bool = False
    auto_promote_after_reviews: bool = False
    poll_interval_seconds: int = 30
    max_pending_bytes: int = 1572864
    state_path: Path | None = None
    shared_skills_path: Path | None = None
    hub_acquisition_enabled: bool = False
    hub_max_results: int = 25
    hub_inspection_ttl_seconds: int = 600

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "auto_promote_after_reviews": self.auto_promote_after_reviews,
            "poll_interval_seconds": self.poll_interval_seconds,
            "max_pending_bytes": self.max_pending_bytes,
            "state_path": str(self.state_path) if self.state_path else None,
            "shared_skills_path": str(self.shared_skills_path) if self.shared_skills_path else None,
            "hub_acquisition_enabled": self.hub_acquisition_enabled,
            "hub_max_results": self.hub_max_results,
            "hub_inspection_ttl_seconds": self.hub_inspection_ttl_seconds,
        }


@dataclass(frozen=True)
class AgencyConfig:
    """Resolved Hermes Agency plugin configuration."""

    enabled: bool = True
    transport_backend: str = "keryx"
    relay: str | None = None
    auto_start: bool = False
    skills_from_profile: bool = True
    allow_remote_tasks: bool = False
    trusted_peers: tuple[str, ...] = ()
    incoming_queue_limit: int = 100
    card_name: str | None = None
    home: Path | None = None
    daemon_bin: Path | None = None
    incoming: IncomingConfig = field(default_factory=IncomingConfig)
    keryx: KeryxTransportConfig = field(default_factory=KeryxTransportConfig)
    relay_security: RelaySecurityConfig = field(default_factory=RelaySecurityConfig)
    registry_allow_insecure_token_transport: bool = False
    outbound: OutboundConfig = field(default_factory=OutboundConfig)
    trust: TrustConfig = field(default_factory=TrustConfig)
    team: TeamConfig = field(default_factory=TeamConfig)
    kanban: KanbanConfig = field(default_factory=KanbanConfig)
    workspace: WorkspaceConfig = field(
        default_factory=lambda: WorkspaceConfig(_default_workspace_root())
    )
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    pool: PoolConfig = field(default_factory=PoolConfig)
    moa: AgencyMoAConfig = field(default_factory=AgencyMoAConfig)
    skill_governance: SkillGovernanceConfig = field(default_factory=SkillGovernanceConfig)
    routing: dict[str, str] = field(default_factory=dict)
    proactive: dict[str, Any] = field(default_factory=dict)
    autonomy: dict[str, Any] = field(default_factory=dict)
    workflows: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "transport_backend": self.transport_backend,
            "relay": self.relay,
            "auto_start": self.auto_start,
            "skills_from_profile": self.skills_from_profile,
            "allow_remote_tasks": self.allow_remote_tasks,
            "trusted_peers": list(self.trusted_peers),
            "incoming_queue_limit": self.incoming_queue_limit,
            "card_name": self.card_name,
            "home": str(self.home) if self.home else None,
            "daemon_bin": str(self.daemon_bin) if self.daemon_bin else None,
            "incoming": self.incoming.as_dict(),
            "keryx": self.keryx.as_dict(),
            "relay_security": self.relay_security.as_dict(),
            "registry_allow_insecure_token_transport": self.registry_allow_insecure_token_transport,
            "outbound": self.outbound.as_dict(),
            "trust": self.trust.as_dict(),
            "incoming_mode": self.incoming_mode,
            "delegation_timeout": self.delegation_timeout,
            "incoming_max_queue_size": self.incoming_max_queue_size,
            "incoming_persist_queue": self.incoming_persist_queue,
            "incoming_queue_persistence_path": str(self.incoming_queue_persistence_path)
            if self.incoming_queue_persistence_path
            else None,
            "incoming_handler_timeout_seconds": self.incoming_handler_timeout_seconds,
            "incoming_tool_access": self.incoming_tool_access,
            "incoming_max_iterations": self.incoming_max_iterations,
            "incoming_subprocess_profile": self.incoming_subprocess_profile,
            "incoming_allow_subprocess": self.incoming_allow_subprocess,
            "incoming_allow_subprocess_fallback": self.incoming_allow_subprocess_fallback,
            "incoming_min_subprocess_trust": self.incoming_min_subprocess_trust,
            "incoming_allow_hooks_for_remote": self.incoming_allow_hooks_for_remote,
            "incoming_reject_unmatched_skills": self.incoming_reject_unmatched_skills,
            "incoming_send_progress": self.incoming_send_progress,
            "incoming_conversation_ttl": self.incoming_conversation_ttl,
            "incoming_conversation_max_turns": self.incoming_conversation_max_turns,
            "team": self.team.as_dict(),
            "kanban": self.kanban.as_dict(),
            "workspace": self.workspace.as_dict(),
            "orchestrator": self.orchestrator.as_dict(),
            "pool": self.pool.as_dict(),
            "moa": self.moa.as_dict(),
            "skill_governance": self.skill_governance.as_dict(),
            "routing": dict(self.routing),
            "proactive": dict(self.proactive),
            "autonomy": dict(self.autonomy),
            "workflows": dict(self.workflows),
        }

    @property
    def incoming_mode(self) -> str:
        return self.incoming.mode

    @property
    def delegation_timeout(self) -> int:
        return self.incoming.delegation_timeout

    @property
    def incoming_max_queue_size(self) -> int:
        return self.incoming.max_queue_size

    @property
    def incoming_persist_queue(self) -> bool:
        return self.incoming.persist_queue

    @property
    def incoming_queue_persistence_path(self) -> Path | None:
        if self.incoming.queue_persistence_path:
            return self.incoming.queue_persistence_path
        if self.home:
            return self.home / "incoming_queue.json"
        return None

    @property
    def incoming_handler_timeout_seconds(self) -> float:
        return self.incoming.handler_timeout_seconds

    @property
    def incoming_tool_access(self) -> str:
        return self.incoming.tool_access

    @property
    def incoming_max_iterations(self) -> int:
        return self.incoming.max_iterations

    @property
    def incoming_subprocess_profile(self) -> str | None:
        return self.incoming.subprocess_profile

    @property
    def incoming_allow_subprocess(self) -> bool:
        return self.incoming.allow_subprocess

    @property
    def incoming_allow_subprocess_fallback(self) -> bool:
        return self.incoming.allow_subprocess_fallback

    @property
    def incoming_min_subprocess_trust(self) -> str:
        return self.incoming.min_subprocess_trust

    @property
    def incoming_allow_hooks_for_remote(self) -> bool:
        return self.incoming.allow_hooks_for_remote

    @property
    def incoming_reject_unmatched_skills(self) -> bool:
        return self.incoming.reject_unmatched_skills

    @property
    def incoming_send_progress(self) -> bool:
        return self.incoming.send_progress

    @property
    def incoming_conversation_ttl(self) -> int:
        return self.incoming.conversation_ttl

    @property
    def incoming_conversation_max_turns(self) -> int:
        return self.incoming.conversation_max_turns

    @property
    def incoming_idle_timeout_seconds(self) -> float:
        return self.incoming.idle_timeout_seconds

    @property
    def workspace_root(self) -> Path:
        return self.workspace.root


def _cfg_get(config: dict[str, Any], *path: str, default: Any = None) -> Any:
    """Small wrapper so nested plugin keys stay readable."""

    return cfg_get(config, *path, default=default)


def _value_missing(value: Any) -> bool:
    """Return True when a profile value is absent for inheritance purposes."""

    return value is None or (isinstance(value, str) and not value.strip())


_RELAY_ADDRESS_KEYS = ("address", "addr", "multiaddr", "url")


def _relay_address_from(raw_relay: Any) -> Any:
    """Extract the effective relay address from supported config shapes."""

    if isinstance(raw_relay, dict):
        for key in _RELAY_ADDRESS_KEYS:
            value = raw_relay.get(key)
            if not _value_missing(value):
                return value
        return None
    return raw_relay if not _value_missing(raw_relay) else None


def _profile_root_home() -> Path | None:
    """Return the default Hermes home when running inside a named profile."""

    home = Path(get_hermes_home()).expanduser()
    if home.parent.name != "profiles":
        return None
    return home.parent.parent


def _default_workspace_root() -> Path:
    root_home = _profile_root_home() or Path(get_hermes_home()).expanduser()
    return root_home / ".agency" / "workspace"


def _is_link_path(path: Path) -> bool:
    """Return True when path is a symlink or platform-specific link."""

    is_junction = getattr(path, "is_junction", lambda: False)
    return path.is_symlink() or is_junction()


def _ensure_private_workspace_dir(path: Path) -> None:
    """Create a workspace directory without following or chmodding links."""

    if _is_link_path(path):
        raise OSError(f"Agency workspace path must not be a link: {path}")

    path.mkdir(parents=True, exist_ok=True)

    if _is_link_path(path):
        raise OSError(f"Agency workspace path must not be a link: {path}")

    path.chmod(_WORKSPACE_DIR_MODE)
    mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
    if mode != _WORKSPACE_DIR_MODE:
        logger.debug("Agency workspace path %s mode is %s", path, oct(mode))


def ensure_workspace(config: AgencyConfig | None = None) -> WorkspaceConfig:
    """Create and return the shared Agency workspace directories."""

    workspace = (config or get_config()).workspace
    for path in (workspace.root, workspace.deliverables, workspace.scratch, workspace.shared):
        try:
            _ensure_private_workspace_dir(path)
        except OSError:
            logger.debug("Unable to secure Agency workspace path %s", path, exc_info=True)
            raise
    return workspace


def _load_profile_root_config() -> dict[str, Any]:
    """Load the root Hermes config used as a fallback for agency-* profiles."""

    root_home = _profile_root_home()
    if root_home is None:
        return {}
    config_path = root_home / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.debug("Failed to load Hermes root config for Agency inheritance", exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def _merge_relay_config(profile_relay: Any, root_relay: Any) -> Any:
    """Inherit only the root relay address into profile relay config."""

    root_address = _relay_address_from(root_relay)
    if _value_missing(root_address):
        return profile_relay
    if isinstance(profile_relay, dict):
        merged = dict(profile_relay)
        if _value_missing(_relay_address_from(profile_relay)):
            merged["address"] = root_address
        return merged
    if _value_missing(profile_relay):
        return {"address": root_address} if isinstance(root_relay, dict) else root_address
    return profile_relay


def _merge_missing_mapping(profile_value: Any, root_value: Any) -> Any:
    """Merge root mapping keys when the profile mapping omits them."""

    if not isinstance(root_value, dict):
        return profile_value
    if not isinstance(profile_value, dict):
        return copy.deepcopy(root_value)
    merged = copy.deepcopy(profile_value)
    for key, value in root_value.items():
        if key not in merged or _value_missing(merged.get(key)):
            merged[key] = copy.deepcopy(value)
    return merged


def _transport_backend_config(config: dict[str, Any]) -> str:
    """Return the configured Agency transport backend with Keryx-first defaults."""

    raw_backend = (
        str(_cfg_get(config, "agency", "transport_backend", default="keryx") or "keryx")
        .strip()
        .lower()
    )
    aliases = {
        "agent-anycast": "agentanycast",
        "agent_anycast": "agentanycast",
        "anycast": "agentanycast",
    }
    backend = aliases.get(raw_backend, raw_backend)
    if backend not in {"agentanycast", "keryx"}:
        logger.warning(
            "Unsupported agency.transport_backend=%r; falling back to keryx", raw_backend
        )
        return "keryx"
    return backend


def _clean_optional_str(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _first_env_value(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _first_csv_value(value: Any) -> str | None:
    for item in str(value or "").split(","):
        cleaned = item.strip()
        if cleaned:
            return cleaned
    return None


def _optional_int_value(value: Any, *, floor: int = 0) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return max(floor, int(value))
    except (TypeError, ValueError):
        return None


def _keryx_transport_config(config: dict[str, Any]) -> KeryxTransportConfig:
    raw = _cfg_get(config, "agency", "keryx", default={}) or {}
    raw_map = raw if isinstance(raw, dict) else {}
    maybe_raw_relay = raw_map.get("relay")
    raw_relay: dict[str, Any] = maybe_raw_relay if isinstance(maybe_raw_relay, dict) else {}
    relay_config = raw_map.get("relay_config") or raw_relay.get("config") or {}
    if not isinstance(relay_config, dict):
        relay_config = {}
    registry_endpoint = _clean_optional_str(raw_map.get("registry_endpoint"))
    if registry_endpoint is None:
        registry_endpoint = _first_env_value(
            "HERMES_KERYX_REGISTRY_ENDPOINT",
            "KERYX_REGISTRY_ENDPOINT",
            "HERMES_KERYX_RELAY_REGISTRY_ENDPOINT",
            "KERYX_RELAY_REGISTRY_ENDPOINT",
        ) or _first_csv_value(os.getenv("AGENTANYCAST_REGISTRY_ADDRS"))
    return KeryxTransportConfig(
        daemon_endpoint=_clean_optional_str(raw_map.get("daemon_endpoint")),
        registry_endpoint=registry_endpoint,
        relay_endpoint=_clean_optional_str(
            raw_map.get("relay_endpoint") or raw_relay.get("endpoint") or raw_relay.get("url")
        ),
        relay_config=copy.deepcopy(relay_config),
        worker_id=_clean_optional_str(raw_map.get("worker_id")),
        default_lease_duration_ms=_optional_int_value(
            raw_map.get("default_lease_duration_ms"), floor=0
        )
        or 0,
        request_timeout_ms=_optional_int_value(raw_map.get("request_timeout_ms"), floor=1),
    )


def _merge_profile_root_agency_config(
    config: dict[str, Any], root_config: dict[str, Any]
) -> dict[str, Any]:
    """Apply root ``agency`` fallbacks that should be shared by all profiles.

    Pool-managed ``agency-*`` profiles carry profile-local identity/runtime
    settings, but the daemon binary, relay connection, and transport backend are
    installation-level settings. Inherit only those shared fields so per-profile
    safety gates such as ``allow_remote_tasks`` and ``auto_start`` remain isolated.
    """

    root_agency = root_config.get("agency") if isinstance(root_config, dict) else None
    if not isinstance(root_agency, dict):
        return config

    merged_config = copy.deepcopy(config) if isinstance(config, dict) else {}
    profile_agency = merged_config.get("agency")
    if not isinstance(profile_agency, dict):
        profile_agency = {}
        merged_config["agency"] = profile_agency

    root_backend = root_agency.get("transport_backend")
    if _value_missing(profile_agency.get("transport_backend")) and not _value_missing(root_backend):
        profile_agency["transport_backend"] = root_backend

    root_daemon_bin = root_agency.get("daemon_bin")
    if _value_missing(profile_agency.get("daemon_bin")) and not _value_missing(root_daemon_bin):
        profile_agency["daemon_bin"] = root_daemon_bin

    root_relay = root_agency.get("relay")
    profile_relay = profile_agency.get("relay")
    inherited_relay = _merge_relay_config(profile_relay, root_relay)
    if inherited_relay is not profile_relay:
        profile_agency["relay"] = inherited_relay

    root_keryx = root_agency.get("keryx")
    profile_keryx = profile_agency.get("keryx")
    inherited_keryx = _merge_missing_mapping(profile_keryx, root_keryx)
    if inherited_keryx is not profile_keryx:
        profile_agency["keryx"] = inherited_keryx

    return merged_config


def _load_config_with_profile_inheritance() -> dict[str, Any]:
    """Load active config plus root fallbacks for shared Agency runtime settings."""

    config = load_config()
    root_config = _load_profile_root_config()
    if root_config:
        return _merge_profile_root_agency_config(config, root_config)
    return config


def _bool_cfg(config: dict[str, Any], *path: str, default: bool) -> bool:
    value = _cfg_get(config, *path, default=default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _team_config(config: dict[str, Any]) -> TeamConfig:
    refresh_minutes_raw = _cfg_get(
        config,
        "agency",
        "team",
        "context_refresh_minutes",
        default=5,
    )
    try:
        refresh_minutes = int(refresh_minutes_raw or 5)
    except (TypeError, ValueError):
        refresh_minutes = 5
    context_filter = (
        str(
            _cfg_get(
                config,
                "agency",
                "team",
                "context_filter",
                default="agency-only",
            )
            or "agency-only"
        )
        .strip()
        .lower()
    )
    if context_filter not in {"agency-only", "all"}:
        context_filter = "agency-only"

    return TeamConfig(
        auto_discover=_bool_cfg(
            config,
            "agency",
            "team",
            "auto_discover",
            default=True,
        ),
        auto_register=_bool_cfg(
            config,
            "agency",
            "team",
            "auto_register",
            default=True,
        ),
        inject_context=_bool_cfg(
            config,
            "agency",
            "team",
            "inject_context",
            default=True,
        ),
        kanban_integration=_bool_cfg(
            config,
            "agency",
            "team",
            "kanban_integration",
            default=True,
        ),
        self_serve=_bool_cfg(
            config,
            "agency",
            "team",
            "self_serve",
            default=True,
        ),
        announce_progress=_bool_cfg(
            config,
            "agency",
            "team",
            "announce_progress",
            default=False,
        ),
        bidding=_bool_cfg(
            config,
            "agency",
            "team",
            "bidding",
            default=False,
        ),
        proactive=_bool_cfg(
            config,
            "agency",
            "team",
            "proactive",
            default=False,
        ),
        learning=_bool_cfg(
            config,
            "agency",
            "team",
            "learning",
            default=False,
        ),
        tenant=(
            str(
                _cfg_get(config, "agency", "team", "tenant", default="default") or "default"
            ).strip()
            or "default"
        ),
        context_refresh_minutes=max(1, refresh_minutes),
        context_filter=context_filter,
        max_context_peers=_int_cfg(
            config,
            "agency",
            "team",
            "max_context_peers",
            default=100,
        ),
        max_context_skills=_int_cfg(
            config,
            "agency",
            "team",
            "max_context_skills",
            default=8,
        ),
        context_max_chars=_int_cfg(
            config,
            "agency",
            "team",
            "context_max_chars",
            default=20000,
            floor=240,
        ),
    )


def _workspace_config(config: dict[str, Any]) -> WorkspaceConfig:
    raw_root = str(_cfg_get(config, "agency", "workspace", "root", default="") or "").strip()
    return WorkspaceConfig(Path(raw_root).expanduser() if raw_root else _default_workspace_root())


def _orchestrator_config(config: dict[str, Any]) -> OrchestratorConfig:
    agent = str(_cfg_get(config, "agency", "orchestrator", "agent", default="") or "").strip()
    return OrchestratorConfig(
        enabled=_bool_cfg(
            config,
            "agency",
            "orchestrator",
            "enabled",
            default=False,
        ),
        agent=agent or None,
        auto_start=_bool_cfg(
            config,
            "agency",
            "orchestrator",
            "auto_start",
            default=False,
        ),
        auto_decompose=_bool_cfg(
            config,
            "agency",
            "orchestrator",
            "auto_decompose",
            default=True,
        ),
    )


def _pool_config(config: dict[str, Any]) -> PoolConfig:
    return PoolConfig(
        max_online_agents=_int_cfg(
            config,
            "agency",
            "pool",
            "max_online_agents",
            default=3,
            floor=0,
        ),
        max_total_rss_mb=_int_cfg(
            config,
            "agency",
            "pool",
            "max_total_rss_mb",
            default=2048,
            floor=0,
        ),
        min_free_mem_mb=_int_cfg(
            config,
            "agency",
            "pool",
            "min_free_mem_mb",
            default=2048,
            floor=0,
        ),
        idle_sleep_after_seconds=_int_cfg(
            config,
            "agency",
            "pool",
            "idle_sleep_after_seconds",
            default=300,
            floor=0,
        ),
        busy_recent_activity_seconds=_int_cfg(
            config,
            "agency",
            "pool",
            "busy_recent_activity_seconds",
            default=120,
            floor=0,
        ),
        allow_discovery_wake=_bool_cfg(
            config,
            "agency",
            "pool",
            "allow_discovery_wake",
            default=False,
        ),
        allow_handshake_wake=_bool_cfg(
            config,
            "agency",
            "pool",
            "allow_handshake_wake",
            default=True,
        ),
        allow_sleep_for_wake=_bool_cfg(
            config,
            "agency",
            "pool",
            "allow_sleep_for_wake",
            default=True,
        ),
        allowed_wake_reasons=_string_tuple(
            _cfg_get(
                config,
                "agency",
                "pool",
                "allowed_wake_reasons",
                default=("manual", "task", "handshake"),
            )
        )
        or ("manual", "task", "handshake"),
        permanent_agents=_string_tuple(
            _cfg_get(
                config,
                "agency",
                "pool",
                "permanent_agents",
                default=("agency-orchestrator",),
            )
        )
        or ("agency-orchestrator",),
    )


def _agency_moa_config(config: dict[str, Any]) -> AgencyMoAConfig:
    raw_default = str(_cfg_get(config, "agency", "moa", "default_preset", default="") or "").strip()
    triggers = _string_tuple(
        _cfg_get(
            config,
            "agency",
            "moa",
            "recommend_for_triggers",
            default=(
                "architecture",
                "security",
                "release",
                "destructive_change",
                "blocker",
            ),
        )
    ) or (
        "architecture",
        "security",
        "release",
        "destructive_change",
        "blocker",
    )
    return AgencyMoAConfig(
        enabled=_bool_cfg(config, "agency", "moa", "enabled", default=True),
        default_preset=raw_default or None,
        allow_auto_moa=_bool_cfg(config, "agency", "moa", "allow_auto_moa", default=False),
        require_confirmation=_bool_cfg(
            config, "agency", "moa", "require_confirmation", default=True
        ),
        kanban_tracking=_bool_cfg(config, "agency", "moa", "kanban_tracking", default=True),
        attach_trace_to_cards=_bool_cfg(
            config, "agency", "moa", "attach_trace_to_cards", default=True
        ),
        recommend_for_triggers=triggers,
    )


def _kanban_config(config: dict[str, Any]) -> KanbanConfig:
    return KanbanConfig(
        preserve_workspaces=_bool_cfg(
            config,
            "agency",
            "kanban",
            "preserve_workspaces",
            default=True,
        ),
        board_cleanup_days=_int_cfg(
            config,
            "agency",
            "kanban",
            "board_cleanup_days",
            default=7,
            floor=0,
        ),
    )


def _int_cfg(config: dict[str, Any], *path: str, default: int, floor: int = 1) -> int:
    raw = _cfg_get(config, *path, default=default)
    try:
        value = int(raw if raw is not None else default)
    except (TypeError, ValueError):
        value = default
    return max(floor, value)


def _float_cfg(config: dict[str, Any], *path: str, default: float, floor: float = 0.001) -> float:
    raw = _cfg_get(config, *path, default=default)
    try:
        value = float(raw if raw is not None else default)
    except (TypeError, ValueError):
        value = default
    return max(floor, value)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        return ()
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in items:
        peer_id = str(item or "").strip()
        if peer_id and peer_id not in seen:
            seen.add(peer_id)
            cleaned.append(peer_id)
    return tuple(cleaned)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _add_peer_to_relay_allowlist_text(clean_peer_id: str) -> dict[str, Any]:
    """Best-effort allowlist append when PyYAML is unavailable.

    This fallback intentionally handles the common Hermes shape only. It avoids
    dropping unrelated config when the standalone agency test/runtime venv does
    not have PyYAML installed.
    """

    from hermes_cli.config import get_config_path

    path = Path(get_config_path()).expanduser()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if clean_peer_id in text:
        return {
            "ok": True,
            "changed": False,
            "reason": "already present",
            "peer_id": clean_peer_id,
            "allowlist": [clean_peer_id],
            "path": str(path),
        }
    lines = text.splitlines()
    item_line = f"      - {clean_peer_id}"
    if not lines:
        lines = ["agency:", "  relay:", "    allowlist:", item_line]
    else:
        inserted = False
        for index, line in enumerate(lines):
            if line.strip() == "allowlist: []":
                indent = line[: len(line) - len(line.lstrip())]
                lines[index] = f"{indent}allowlist:"
                lines.insert(index + 1, f"{indent}  - {clean_peer_id}")
                inserted = True
                break
            if line.strip() == "allowlist:":
                indent = line[: len(line) - len(line.lstrip())]
                lines.insert(index + 1, f"{indent}  - {clean_peer_id}")
                inserted = True
                break
        if not inserted:
            for index, line in enumerate(lines):
                if line.strip() == "relay:":
                    indent = line[: len(line) - len(line.lstrip())]
                    lines[index + 1 : index + 1] = [
                        f"{indent}  allowlist:",
                        f"{indent}    - {clean_peer_id}",
                    ]
                    inserted = True
                    break
        if not inserted:
            lines.extend(["", "agency:", "  relay:", "    allowlist:", item_line])
    _write_text_atomic(path, "\n".join(lines).rstrip() + "\n")
    return {
        "ok": True,
        "changed": True,
        "peer_id": clean_peer_id,
        "allowlist": [clean_peer_id],
        "path": str(path),
        "fallback": "text",
    }


def _load_raw_user_config() -> tuple[dict[str, Any], Path]:
    """Load the active profile's raw config.yaml without merged defaults."""

    try:
        import yaml
    except Exception as exc:  # pragma: no cover - Hermes depends on PyYAML
        raise RuntimeError("PyYAML is required to update config.yaml") from exc

    from hermes_cli.config import get_config_path

    path = Path(get_config_path()).expanduser()
    if not path.exists():
        return {}, path
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}, path


def _save_raw_user_config(config: dict[str, Any], path: Path) -> None:
    """Atomically persist the active profile config."""

    try:
        from hermes_cli.config import ensure_hermes_home

        ensure_hermes_home()
    except Exception:
        path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from utils import atomic_yaml_write

        atomic_yaml_write(path, config, sort_keys=False)
        return
    except Exception:
        pass

    try:
        import yaml
    except Exception as exc:  # pragma: no cover - Hermes depends on PyYAML
        raise RuntimeError("PyYAML is required to update config.yaml") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def add_peer_to_relay_allowlist(peer_id: str) -> dict[str, Any]:
    """Persistently add ``peer_id`` to ``agency.relay.allowlist``.

    The send path checks the effective relay allowlist before attempting direct
    peer sends. Auto-handshake uses this helper so discovery/trust changes are
    reflected both in the next in-memory ``get_config()`` resolution and in the
    profile's ``config.yaml`` for future sessions.

    Returns a small idempotent result with ``changed=false`` when the peer is
    already present or when ``agency.relay.allow_all=true`` makes the append
    unnecessary.
    """

    clean_peer_id = str(peer_id or "").strip()
    if not clean_peer_id:
        raise ValueError("peer_id is required")

    try:
        raw_config, path = _load_raw_user_config()
    except RuntimeError as exc:
        if "PyYAML" in str(exc):
            return _add_peer_to_relay_allowlist_text(clean_peer_id)
        raise
    agency = raw_config.setdefault("agency", {})
    if not isinstance(agency, dict):
        agency = {}
        raw_config["agency"] = agency

    relay_raw = agency.get("relay")
    if isinstance(relay_raw, dict):
        relay = relay_raw
    else:
        relay = {}
        if relay_raw not in (None, ""):
            relay["address"] = relay_raw
        agency["relay"] = relay

    if bool(relay.get("allow_all")):
        allowlist = list(_string_tuple(relay.get("allowlist") or []))
        return {
            "ok": True,
            "changed": False,
            "reason": "allow_all enabled",
            "peer_id": clean_peer_id,
            "allowlist": allowlist,
            "path": str(path),
        }

    allowlist = list(_string_tuple(relay.get("allowlist") or []))
    if clean_peer_id in allowlist:
        return {
            "ok": True,
            "changed": False,
            "reason": "already present",
            "peer_id": clean_peer_id,
            "allowlist": allowlist,
            "path": str(path),
        }

    allowlist.append(clean_peer_id)
    relay["allowlist"] = allowlist
    _save_raw_user_config(raw_config, path)
    return {
        "ok": True,
        "changed": True,
        "peer_id": clean_peer_id,
        "allowlist": allowlist,
        "path": str(path),
    }


def _env_truthy(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on", "dev"}


def _warn_empty_allowlist_migration(
    relay_map: dict[str, Any], allowlist: tuple[str, ...], allow_all: bool
) -> None:
    global _WARNED_EMPTY_ALLOWLIST_MIGRATION
    if _WARNED_EMPTY_ALLOWLIST_MIGRATION or allowlist or allow_all:
        return
    if relay_map and "allow_all" not in relay_map:
        logger.warning(
            "Hermes Agency relay allowlist is empty and agency.relay.allow_all is not set; "
            "empty allowlist now means deny. Set agency.relay.allow_all=true only for "
            "trusted development/local networks."
        )
        _WARNED_EMPTY_ALLOWLIST_MIGRATION = True


def _relay_security_config(config: dict[str, Any]) -> RelaySecurityConfig:
    raw_relay = _cfg_get(config, "agency", "relay", default=None)
    relay_map = raw_relay if isinstance(raw_relay, dict) else {}
    allowlist_raw = (
        relay_map.get("allowlist")
        if relay_map
        else _cfg_get(
            config,
            "agency",
            "relay",
            "allowlist",
            default=[],
        )
    )
    token_raw = (
        relay_map.get("token")
        if relay_map
        else _cfg_get(
            config,
            "agency",
            "relay",
            "token",
            default=None,
        )
    )
    token = str(token_raw or "").strip()
    allowlist = _string_tuple(allowlist_raw)
    allow_all = _bool_cfg(
        config,
        "agency",
        "relay",
        "allow_all",
        default=bool(relay_map.get("allow_all", False)) if relay_map else False,
    )
    if not allowlist and not allow_all and _env_truthy("HERMES_AGENCY_DEV_MODE"):
        logger.warning(
            "HERMES_AGENCY_DEV_MODE enabled legacy empty-allowlist allow-all behavior; "
            "set agency.relay.allow_all=true explicitly before relying on this outside dev"
        )
        allow_all = True
    _warn_empty_allowlist_migration(relay_map, allowlist, allow_all)
    return RelaySecurityConfig(
        allowlist=allowlist,
        auto_allow_team=_bool_cfg(
            config,
            "agency",
            "relay",
            "auto_allow_team",
            default=bool(relay_map.get("auto_allow_team", False)) if relay_map else False,
        ),
        allow_all=allow_all,
        token=token or None,
    )


def _trust_config(config: dict[str, Any]) -> TrustConfig:
    raw_path = _cfg_get(config, "agency", "trust", "store_path", default="") or ""
    store_path = (
        Path(str(raw_path)).expanduser()
        if raw_path
        else get_hermes_home() / "agency" / "trust.json"
    )
    return TrustConfig(
        store_path=store_path,
        tofu=_bool_cfg(config, "agency", "trust", "tofu", default=True),
    )


def _incoming_config(config: dict[str, Any]) -> IncomingConfig:
    mode = (
        str(_cfg_get(config, "agency", "incoming", "mode", default="delegation") or "delegation")
        .strip()
        .lower()
    )
    if mode not in {"template", "delegation", "subprocess"}:
        mode = "delegation"
    tool_access = (
        str(_cfg_get(config, "agency", "incoming", "tool_access", default="safe") or "safe")
        .strip()
        .lower()
    )
    if tool_access not in {"safe", "full", "none"}:
        tool_access = "safe"
    subprocess_profile = str(
        _cfg_get(config, "agency", "incoming", "subprocess_profile", default="") or ""
    ).strip()
    min_subprocess_trust = (
        str(
            _cfg_get(config, "agency", "incoming", "min_subprocess_trust", default="full") or "full"
        )
        .strip()
        .lower()
    )
    if min_subprocess_trust not in {"full", "limited"}:
        min_subprocess_trust = "full"
    raw_persistence_path = str(
        _cfg_get(
            config,
            "agency",
            "incoming",
            "queue_persistence_path",
            default="",
        )
        or ""
    ).strip()
    return IncomingConfig(
        mode=mode,
        delegation_timeout=_int_cfg(
            config,
            "agency",
            "incoming",
            "delegation_timeout",
            default=600,
            floor=1,
        ),
        max_queue_size=_int_cfg(
            config,
            "agency",
            "incoming",
            "max_queue_size",
            default=100,
            floor=1,
        ),
        persist_queue=_bool_cfg(
            config,
            "agency",
            "incoming",
            "persist_queue",
            default=True,
        ),
        queue_persistence_path=Path(raw_persistence_path).expanduser()
        if raw_persistence_path
        else None,
        handler_timeout_seconds=_float_cfg(
            config,
            "agency",
            "incoming",
            "handler_timeout_seconds",
            default=900,
            floor=0.001,
        ),
        tool_access=tool_access,
        max_iterations=_int_cfg(
            config,
            "agency",
            "incoming",
            "max_iterations",
            default=25,
            floor=1,
        ),
        subprocess_profile=subprocess_profile or None,
        allow_subprocess=_bool_cfg(
            config,
            "agency",
            "incoming",
            "allow_subprocess",
            default=False,
        ),
        allow_subprocess_fallback=_bool_cfg(
            config,
            "agency",
            "incoming",
            "allow_subprocess_fallback",
            default=False,
        ),
        min_subprocess_trust=min_subprocess_trust,
        allow_hooks_for_remote=_bool_cfg(
            config,
            "agency",
            "incoming",
            "allow_hooks_for_remote",
            default=False,
        ),
        reject_unmatched_skills=_bool_cfg(
            config,
            "agency",
            "incoming",
            "reject_unmatched_skills",
            default=False,
        ),
        send_progress=_bool_cfg(
            config,
            "agency",
            "incoming",
            "send_progress",
            default=False,
        ),
        conversation_ttl=_int_cfg(
            config,
            "agency",
            "incoming",
            "conversation_ttl",
            default=3600,
            floor=0,
        ),
        conversation_max_turns=_int_cfg(
            config,
            "agency",
            "incoming",
            "conversation_max_turns",
            default=20,
            floor=1,
        ),
        idle_timeout_seconds=_float_cfg(
            config,
            "agency",
            "incoming",
            "idle_timeout_seconds",
            default=120,
            floor=0,
        ),
    )


def _routing_config(config: dict[str, Any]) -> dict[str, str]:
    raw = _cfg_get(config, "agency", "routing", default={}) or {}
    if not isinstance(raw, dict):
        return {}
    rules: dict[str, str] = {}
    for key, value in raw.items():
        clean_key = str(key).strip().lower()
        clean_value = str(value).strip()
        if clean_key and clean_value:
            rules[clean_key] = clean_value
    return rules


def _outbound_config(config: dict[str, Any]) -> OutboundConfig:
    validation = (
        str(_cfg_get(config, "agency", "outbound", "url_validation", default="warn") or "warn")
        .strip()
        .lower()
    )
    if validation not in {"warn", "strict"}:
        validation = "warn"
    return OutboundConfig(
        url_validation=validation,
        url_allowlist=_string_tuple(
            _cfg_get(config, "agency", "outbound", "url_allowlist", default=[])
        ),
    )


def _skill_governance_config(config: dict[str, Any]) -> SkillGovernanceConfig:
    root_home = _profile_root_home() or Path(get_hermes_home()).expanduser()
    raw_state = _clean_optional_str(
        _cfg_get(config, "agency", "skill_governance", "state_path", default=None)
    )
    raw_shared = _clean_optional_str(
        _cfg_get(config, "agency", "skill_governance", "shared_skills_path", default=None)
    )
    return SkillGovernanceConfig(
        enabled=_bool_cfg(config, "agency", "skill_governance", "enabled", default=False),
        auto_promote_after_reviews=_bool_cfg(
            config,
            "agency",
            "skill_governance",
            "auto_promote_after_reviews",
            default=False,
        ),
        poll_interval_seconds=_int_cfg(
            config, "agency", "skill_governance", "poll_interval_seconds", default=30, floor=5
        ),
        max_pending_bytes=_int_cfg(
            config, "agency", "skill_governance", "max_pending_bytes", default=1572864, floor=1
        ),
        state_path=Path(raw_state).expanduser()
        if raw_state
        else root_home / ".agency" / "skill-governance",
        shared_skills_path=Path(raw_shared).expanduser()
        if raw_shared
        else root_home / "skills" / "shared",
        hub_acquisition_enabled=_bool_cfg(
            config, "agency", "skill_governance", "hub_acquisition_enabled", default=False
        ),
        hub_max_results=_int_cfg(
            config, "agency", "skill_governance", "hub_max_results", default=25, floor=1
        ),
        hub_inspection_ttl_seconds=_int_cfg(
            config,
            "agency",
            "skill_governance",
            "hub_inspection_ttl_seconds",
            default=600,
            floor=60,
        ),
    )


def _dict_config(config: dict[str, Any], key: str) -> dict[str, Any]:
    raw = _cfg_get(config, "agency", key, default={}) or {}
    return dict(raw) if isinstance(raw, dict) else {}


def current_profile_name() -> str:
    """Return the active Hermes profile name without reading SOUL.md."""

    env_profile = os.getenv("HERMES_PROFILE", "").strip()
    if env_profile:
        return env_profile
    home = Path(get_hermes_home()).expanduser()
    if home.parent.name == "profiles":
        return home.name
    return "default"


def is_current_orchestrator(config: AgencyConfig | None = None) -> bool:
    """Return True when orchestrator tools/context should be active here.

    ``agency.orchestrator.enabled`` is the hard gate. When
    ``agency.orchestrator.agent`` is unset, the enabled profile is treated
    as the active orchestrator; when it is set, it must match the current Hermes
    profile name.
    """

    cfg = config or get_config()
    if not cfg.enabled or not cfg.orchestrator.enabled:
        return False
    configured_agent = (cfg.orchestrator.agent or "").strip().lower()
    if not configured_agent:
        return True
    return configured_agent == current_profile_name().strip().lower()


def get_config() -> AgencyConfig:
    """Load ``agency.*`` settings from the active Hermes profile config."""

    config = _load_config_with_profile_inheritance()
    raw_home = _cfg_get(config, "agency", "home", default="") or ""
    home = Path(raw_home).expanduser() if raw_home else get_hermes_home() / ".agency"
    raw_daemon_bin = _cfg_get(config, "agency", "daemon_bin", default="") or ""
    daemon_bin = Path(str(raw_daemon_bin)).expanduser() if raw_daemon_bin else None
    raw_relay = _cfg_get(config, "agency", "relay", default="") or None
    if isinstance(raw_relay, dict):
        relay = (
            raw_relay.get("address")
            or raw_relay.get("addr")
            or raw_relay.get("multiaddr")
            or raw_relay.get("url")
            or None
        )
    else:
        relay = raw_relay
    raw_trusted_peers = _cfg_get(config, "agency", "trusted_peers", default=[]) or []
    trusted_peers = _string_tuple(raw_trusted_peers)
    incoming_queue_limit = int(
        _cfg_get(config, "agency", "incoming_queue_limit", default=100) or 100
    )
    card_name = str(_cfg_get(config, "agency", "card_name", default="") or "").strip()
    return AgencyConfig(
        enabled=_bool_cfg(config, "agency", "enabled", default=True),
        transport_backend=_transport_backend_config(config),
        relay=relay,
        auto_start=_bool_cfg(config, "agency", "auto_start", default=False),
        skills_from_profile=_bool_cfg(
            config,
            "agency",
            "skills_from_profile",
            default=True,
        ),
        allow_remote_tasks=_bool_cfg(
            config,
            "agency",
            "allow_remote_tasks",
            default=False,
        ),
        trusted_peers=trusted_peers,
        incoming_queue_limit=max(1, incoming_queue_limit),
        card_name=card_name or None,
        home=home,
        daemon_bin=daemon_bin,
        incoming=_incoming_config(config),
        keryx=_keryx_transport_config(config),
        relay_security=_relay_security_config(config),
        registry_allow_insecure_token_transport=_bool_cfg(
            config,
            "agency",
            "registry",
            "allow_insecure_token_transport",
            default=False,
        ),
        outbound=_outbound_config(config),
        trust=_trust_config(config),
        team=_team_config(config),
        kanban=_kanban_config(config),
        workspace=_workspace_config(config),
        orchestrator=_orchestrator_config(config),
        pool=_pool_config(config),
        moa=_agency_moa_config(config),
        skill_governance=_skill_governance_config(config),
        routing=_routing_config(config),
        proactive=_dict_config(config, "proactive"),
        autonomy=_dict_config(config, "autonomy"),
        workflows=_dict_config(config, "workflows"),
    )
