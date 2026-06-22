"""Autonomy policy engine for Hermes Agency autonomous operations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from hermes_cli.config import cfg_get, load_config

from .config import current_profile_name

AUTONOMOUS = "autonomous"
NOTIFY = "notify"
ASK = "ask"
NEVER = "never"
VALID_DECISIONS = {AUTONOMOUS, NOTIFY, ASK, NEVER}

DEFAULT_POLICY = {
    AUTONOMOUS: {"read", "search", "list", "query", "research"},
    NOTIFY: {"create_file", "run_test", "api_call"},
    ASK: {"deploy", "delete", "send_external", "modify_production"},
    NEVER: {"security_change", "billing", "user_facing_change"},
}

ALIASES = {
    "always": AUTONOMOUS,
    "autonomous": AUTONOMOUS,
    "allow": AUTONOMOUS,
    "notify": NOTIFY,
    "ask": ASK,
    "approval": ASK,
    "never": NEVER,
    "deny": NEVER,
}


def _clean_action(action: Any) -> str:
    text = str(action or "").strip().lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"[^a-z0-9_.]+", "_", text).strip("_")


def _decision(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return ALIASES.get(normalized) if normalized in ALIASES else (normalized if normalized in VALID_DECISIONS else None)


def _config_override(config: dict[str, Any], action: str, agent: str) -> str | None:
    root = cfg_get(config, "agency", "autonomy", default={}) or {}
    if not isinstance(root, dict):
        return None
    # Per-agent direct shape: agency.autonomy.<agent>.<action>: decision
    agent_policy = root.get(agent) or root.get(agent.lower())
    if isinstance(agent_policy, dict):
        direct = _decision(agent_policy.get(action))
        if direct:
            return direct
    # Global direct shape: agency.autonomy.<action>: decision
    direct = _decision(root.get(action))
    if direct:
        return direct
    # Group shape: agency.autonomy.always/notify/ask/never: [actions]
    for group, decision in (("always", AUTONOMOUS), ("autonomous", AUTONOMOUS), ("notify", NOTIFY), ("ask", ASK), ("never", NEVER)):
        values = root.get(group)
        if isinstance(values, list) and action in {_clean_action(item) for item in values}:
            return decision
    return None


def _soul_override(action: str, agent: str) -> str | None:
    """Read explicit SOUL autonomy declarations, if present.

    Supported compact forms:
      agency.autonomy.<action>: ask
      agency.autonomy.<agent>.<action>: notify
      autonomy <action>: never
    """

    path = Path(get_hermes_home()) / "SOUL.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    candidates = [
        rf"(?im)^\s*agency\.autonomy\.{re.escape(agent)}\.{re.escape(action)}\s*:\s*([a-z_-]+)\s*$",
        rf"(?im)^\s*agency\.autonomy\.{re.escape(action)}\s*:\s*([a-z_-]+)\s*$",
        rf"(?im)^\s*autonomy\s+{re.escape(action)}\s*:\s*([a-z_-]+)\s*$",
    ]
    for pattern in candidates:
        match = re.search(pattern, text)
        if match:
            decision = _decision(match.group(1))
            if decision:
                return decision
    return None


def _default_decision(action: str) -> str:
    for decision, actions in DEFAULT_POLICY.items():
        if action in actions:
            return decision
    # Unknown actions are conservative but not prohibited: ask Kyle.
    return ASK


def check_autonomy(action: str, agent: str | None = None) -> dict[str, Any]:
    """Categorize an autonomous action as autonomous, notify, ask, or never."""

    clean_action = _clean_action(action)
    clean_agent = str(agent or current_profile_name()).strip().lower() or "default"
    config = load_config()
    source = "default"
    decision = _soul_override(clean_action, clean_agent)
    if decision:
        source = "SOUL.md"
    else:
        decision = _config_override(config, clean_action, clean_agent)
        if decision:
            source = "config"
        else:
            decision = _default_decision(clean_action)
    return {
        "action": clean_action,
        "agent": clean_agent,
        "decision": decision,
        "source": source,
        "autonomous": decision == AUTONOMOUS,
        "notify": decision == NOTIFY,
        "requires_approval": decision == ASK,
        "prohibited": decision == NEVER,
    }


def policy_summary() -> dict[str, Any]:
    return {
        "defaults": {key: sorted(values) for key, values in DEFAULT_POLICY.items()},
        "valid_decisions": sorted(VALID_DECISIONS),
    }
