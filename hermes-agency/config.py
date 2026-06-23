"""Configuration helpers for the Hermes Agency Hermes plugin.

Config schema and defaults::

    agency:
      enabled: true               # plugin-level runtime gate; plugin loading remains opt-in
      relay: null                 # relay multiaddr for cross-network
      auto_start: false           # true = start node on session start
      skills_from_profile: true   # auto-generate AgentCard skills from installed Hermes skills
      allow_remote_tasks: false   # false = safe stub; true = process according to incoming.mode
      incoming:
        mode: delegation          # template, delegation, subprocess
        delegation_timeout: 120   # seconds before falling back to template
        tool_access: safe         # safe, full, none
        max_iterations: 25        # max subagent turns
        subprocess_profile: null  # optional Hermes profile override for subprocess fallback
        reject_unmatched_skills: false  # true = fail if requested skill is not installed
        send_progress: false      # true = send intermediate A2A progress artifacts
        conversation_ttl: 3600    # seconds to preserve A2A conversation continuity
        conversation_max_turns: 20 # max previous turns to include
      trusted_peers: []           # peer_id allowlist (future)
      incoming_queue_limit: 100   # max incoming task records to keep
      card_name: null             # optional display name for this node's AgentCard
      home: null                  # override daemon home dir (default: $HERMES_HOME/.agency)
      daemon_bin: null            # explicit daemon binary path; prevents SDK auto-download/overwrite
      relay:
        allowlist: []           # peer_ids allowed to reserve relay slots; empty = allow all
        auto_allow_team: true   # auto-add discovered teammates to relay allowlist
        token: null             # shared secret for relay allowlist/token control plane
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
        max_context_peers: 5      # max peers included in injected prompt context
        max_context_skills: 5     # max skills shown per peer in injected context
        context_max_chars: 4000   # hard character budget for injected context block
      orchestrator:
        enabled: false
        agent: null
        auto_decompose: true
      routing: {}
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes_cli.config import cfg_get, load_config
from hermes_constants import get_hermes_home


@dataclass(frozen=True)
class RelaySecurityConfig:
    """Resolved relay-side security configuration."""

    allowlist: tuple[str, ...] = ()
    auto_allow_team: bool = True
    token: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowlist": list(self.allowlist),
            "auto_allow_team": self.auto_allow_team,
            "token_configured": bool(self.token),
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
    max_context_peers: int = 5
    max_context_skills: int = 5
    context_max_chars: int = 4000

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
            "max_context_peers": self.max_context_peers,
            "max_context_skills": self.max_context_skills,
            "context_max_chars": self.context_max_chars,
        }


@dataclass(frozen=True)
class OrchestratorConfig:
    """Resolved orchestrator-layer configuration."""

    enabled: bool = False
    agent: str | None = None
    auto_decompose: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "agent": self.agent,
            "auto_decompose": self.auto_decompose,
        }


@dataclass(frozen=True)
class IncomingConfig:
    """Resolved incoming-task LLM processing configuration."""

    mode: str = "delegation"
    delegation_timeout: int = 120
    tool_access: str = "safe"
    max_iterations: int = 25
    subprocess_profile: str | None = None
    reject_unmatched_skills: bool = False
    send_progress: bool = False
    conversation_ttl: int = 3600
    conversation_max_turns: int = 20

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "delegation_timeout": self.delegation_timeout,
            "tool_access": self.tool_access,
            "max_iterations": self.max_iterations,
            "subprocess_profile": self.subprocess_profile,
            "reject_unmatched_skills": self.reject_unmatched_skills,
            "send_progress": self.send_progress,
            "conversation_ttl": self.conversation_ttl,
            "conversation_max_turns": self.conversation_max_turns,
        }


@dataclass(frozen=True)
class AgencyConfig:
    """Resolved Hermes Agency plugin configuration."""

    enabled: bool = True
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
    relay_security: RelaySecurityConfig = field(default_factory=RelaySecurityConfig)
    trust: TrustConfig = field(default_factory=TrustConfig)
    team: TeamConfig = field(default_factory=TeamConfig)
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    routing: dict[str, str] = field(default_factory=dict)
    autonomy: dict[str, Any] = field(default_factory=dict)
    workflows: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
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
            "relay_security": self.relay_security.as_dict(),
            "trust": self.trust.as_dict(),
            "incoming_mode": self.incoming_mode,
            "delegation_timeout": self.delegation_timeout,
            "incoming_tool_access": self.incoming_tool_access,
            "incoming_max_iterations": self.incoming_max_iterations,
            "incoming_subprocess_profile": self.incoming_subprocess_profile,
            "incoming_reject_unmatched_skills": self.incoming_reject_unmatched_skills,
            "incoming_send_progress": self.incoming_send_progress,
            "incoming_conversation_ttl": self.incoming_conversation_ttl,
            "incoming_conversation_max_turns": self.incoming_conversation_max_turns,
            "team": self.team.as_dict(),
            "orchestrator": self.orchestrator.as_dict(),
            "routing": dict(self.routing),
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
    def incoming_tool_access(self) -> str:
        return self.incoming.tool_access

    @property
    def incoming_max_iterations(self) -> int:
        return self.incoming.max_iterations

    @property
    def incoming_subprocess_profile(self) -> str | None:
        return self.incoming.subprocess_profile

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


def _cfg_get(config: dict[str, Any], *path: str, default: Any = None) -> Any:
    """Small wrapper so nested plugin keys stay readable."""

    return cfg_get(config, *path, default=default)


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
        max_context_peers=_int_cfg(
            config,
            "agency",
            "team",
            "max_context_peers",
            default=5,
        ),
        max_context_skills=_int_cfg(
            config,
            "agency",
            "team",
            "max_context_skills",
            default=5,
        ),
        context_max_chars=_int_cfg(
            config,
            "agency",
            "team",
            "context_max_chars",
            default=4000,
            floor=240,
        ),
    )


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
        auto_decompose=_bool_cfg(
            config,
            "agency",
            "orchestrator",
            "auto_decompose",
            default=True,
        ),
    )


def _int_cfg(config: dict[str, Any], *path: str, default: int, floor: int = 1) -> int:
    raw = _cfg_get(config, *path, default=default)
    try:
        value = int(raw if raw is not None else default)
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
    return RelaySecurityConfig(
        allowlist=_string_tuple(allowlist_raw),
        auto_allow_team=_bool_cfg(
            config,
            "agency",
            "relay",
            "auto_allow_team",
            default=bool(relay_map.get("auto_allow_team", True)) if relay_map else True,
        ),
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
    return IncomingConfig(
        mode=mode,
        delegation_timeout=_int_cfg(
            config,
            "agency",
            "incoming",
            "delegation_timeout",
            default=120,
            floor=1,
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

    config = load_config()
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
        relay_security=_relay_security_config(config),
        trust=_trust_config(config),
        team=_team_config(config),
        orchestrator=_orchestrator_config(config),
        routing=_routing_config(config),
        autonomy=_dict_config(config, "autonomy"),
        workflows=_dict_config(config, "workflows"),
    )
