"""Configuration helpers for the AgentAnycast Hermes plugin."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


from hermes_constants import get_hermes_home
from hermes_cli.config import cfg_get, load_config


@dataclass(frozen=True)
class AgentAnycastConfig:
    """Resolved AgentAnycast plugin configuration."""

    enabled: bool = False
    relay: str | None = None
    auto_start: bool = False
    skills_from_profile: bool = True
    allow_remote_tasks: bool = False
    trusted_peers: tuple[str, ...] = ()
    incoming_queue_limit: int = 100
    home: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "relay": self.relay,
            "auto_start": self.auto_start,
            "skills_from_profile": self.skills_from_profile,
            "allow_remote_tasks": self.allow_remote_tasks,
            "trusted_peers": list(self.trusted_peers),
            "incoming_queue_limit": self.incoming_queue_limit,
            "home": str(self.home) if self.home else None,
        }


def get_config() -> AgentAnycastConfig:
    """Load ``agentanycast.*`` settings from the active Hermes profile config."""

    config = load_config()
    raw_home = cfg_get(config, "agentanycast", "home", default="") or ""
    home = Path(raw_home).expanduser() if raw_home else get_hermes_home() / ".agentanycast"
    relay = cfg_get(config, "agentanycast", "relay", default="") or None
    raw_trusted_peers = cfg_get(config, "agentanycast", "trusted_peers", default=[]) or []
    if isinstance(raw_trusted_peers, str):
        trusted_peers = tuple(item.strip() for item in raw_trusted_peers.split(",") if item.strip())
    else:
        trusted_peers = tuple(str(item) for item in raw_trusted_peers)
    incoming_queue_limit = int(
        cfg_get(config, "agentanycast", "incoming_queue_limit", default=100) or 100
    )
    return AgentAnycastConfig(
        enabled=bool(cfg_get(config, "agentanycast", "enabled", default=False)),
        relay=relay,
        auto_start=bool(cfg_get(config, "agentanycast", "auto_start", default=False)),
        skills_from_profile=bool(
            cfg_get(config, "agentanycast", "skills_from_profile", default=True)
        ),
        allow_remote_tasks=bool(
            cfg_get(config, "agentanycast", "allow_remote_tasks", default=False)
        ),
        trusted_peers=trusted_peers,
        incoming_queue_limit=max(1, incoming_queue_limit),
        home=home,
    )
