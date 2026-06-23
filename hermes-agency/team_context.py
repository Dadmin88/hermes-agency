"""Team discovery and team-context rendering for Hermes Agency collaboration.

This module keeps all team state in memory. It never writes SOUL.md or config;
configuration only controls whether/when refresh and prompt injection happen.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AgencyConfig, get_config
from .registration import live_registrations


def _load_pool_roster() -> dict[str, Any]:
    """Best-effort load of the persistent agency-* roster."""

    try:
        from .pool.roster import build_roster, save_roster

        return save_roster(build_roster(include_plugin_setup=False))
    except Exception:
        return {"profiles": [], "total": 0, "online": 0}


def _update_pool_roster_from_discovery(peers: dict[str, PeerCapability]) -> None:
    """Persist live discovery overlay without making discovery depend on roster I/O."""

    try:
        from .pool.roster import update_roster_from_discovery

        update_roster_from_discovery({peer_id: peer.as_dict() for peer_id, peer in peers.items()})
    except Exception:
        return


@dataclass
class PeerCapability:
    """Normalized capability record for one discovered A2A peer."""

    peer_id: str
    name: str = ""
    description: str = ""
    skills: list[dict[str, str]] = field(default_factory=list)
    card_name: str = ""
    card_description: str = ""
    card_skills: list[dict[str, str]] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "name": self.name,
            "description": self.description,
            "skills": list(self.skills),
            "card_name": self.card_name,
            "card_description": self.card_description,
            "card_skills": list(self.card_skills),
            "addresses": list(self.addresses),
            "last_seen": self.last_seen,
        }


@dataclass
class TeamState:
    """In-memory team discovery cache."""

    peers: dict[str, PeerCapability] = field(default_factory=dict)
    last_refresh: float | None = None
    last_error: str | None = None
    refresh_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "peers": {peer_id: peer.as_dict() for peer_id, peer in sorted(self.peers.items())},
            "last_refresh": self.last_refresh,
            "last_error": self.last_error,
            "refresh_count": self.refresh_count,
        }


_state = TeamState()


def get_team_state() -> TeamState:
    """Return the process-local team cache."""

    return _state


def _skill_id(skill: Any) -> str:
    if isinstance(skill, dict):
        return str(skill.get("skill_id") or skill.get("id") or skill.get("name") or "").strip()
    return str(
        getattr(skill, "skill_id", "") or getattr(skill, "id", "") or getattr(skill, "name", "")
    ).strip()


def _skill_description(skill: Any) -> str:
    if isinstance(skill, dict):
        return str(skill.get("description") or "").strip()
    return str(getattr(skill, "description", "") or "").strip()


def _normalise_skills(skills: Any) -> list[dict[str, str]]:
    normalised: list[dict[str, str]] = []
    if not isinstance(skills, list):
        return normalised
    seen: set[str] = set()
    for item in skills:
        skill_id = _skill_id(item)
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        normalised.append({"id": skill_id, "description": _skill_description(item)})
    return normalised


def _peer_id(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("peer_id") or item.get("id") or item.get("did") or "").strip()
    return str(
        getattr(item, "peer_id", "") or getattr(item, "id", "") or getattr(item, "did", "")
    ).strip()


def _card_from_peer(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        card = item.get("card") or item.get("agent_card") or {}
        return card if isinstance(card, dict) else {}
    card = getattr(item, "card", None) or getattr(item, "agent_card", None)
    if isinstance(card, dict):
        return card
    return {}


def _normalise_peer(item: Any) -> PeerCapability | None:
    peer_id = _peer_id(item)
    if not peer_id:
        return None

    card = _card_from_peer(item)
    if isinstance(item, dict):
        name = str(item.get("agent_name") or item.get("name") or card.get("name") or "").strip()
        description = str(
            item.get("agent_description")
            or item.get("description")
            or card.get("description")
            or ""
        ).strip()
        raw_skills = item.get("skills") or card.get("skills") or []
        addresses = item.get("addresses") or []
    else:
        name = str(
            getattr(item, "agent_name", "") or getattr(item, "name", "") or card.get("name") or ""
        ).strip()
        description = str(
            getattr(item, "agent_description", "")
            or getattr(item, "description", "")
            or card.get("description")
            or ""
        ).strip()
        raw_skills = getattr(item, "skills", None) or card.get("skills") or []
        addresses = getattr(item, "addresses", []) or []

    return PeerCapability(
        peer_id=peer_id,
        name=name,
        description=description,
        skills=_normalise_skills(raw_skills),
        addresses=[str(addr) for addr in addresses] if isinstance(addresses, list) else [],
    )


def _normalise_card(peer_id: str, card: Any) -> PeerCapability | None:
    """Build a capability record from an AgentCard returned by node.get_card()."""

    peer_id = str(peer_id or "").strip()
    if not peer_id:
        return None
    if isinstance(card, dict):
        name = str(card.get("name") or "").strip()
        description = str(card.get("description") or "").strip()
        raw_skills = card.get("skills") or []
    else:
        name = str(getattr(card, "name", "") or "").strip()
        description = str(getattr(card, "description", "") or "").strip()
        raw_skills = getattr(card, "skills", None) or []
    skills = _normalise_skills(raw_skills)
    return PeerCapability(
        peer_id=peer_id,
        name=name,
        description=description,
        skills=skills,
        card_name=name,
        card_description=description,
        card_skills=skills,
    )


def _normalise_registration(item: dict[str, Any]) -> PeerCapability | None:
    """Build a capability record from Phase 4 self-registration state."""

    peer_id = str(item.get("peer_id") or "").strip()
    if not peer_id:
        return None
    return PeerCapability(
        peer_id=peer_id,
        name=str(item.get("name") or "").strip(),
        description=str(item.get("description") or "").strip(),
        skills=_normalise_skills(item.get("skills") or []),
    )


def _merge_peer(base: PeerCapability | None, incoming: PeerCapability) -> PeerCapability:
    if base is None:
        return incoming
    base.last_seen = time.time()
    if incoming.name:
        base.name = incoming.name
    if incoming.description:
        base.description = incoming.description
    if incoming.skills:
        by_id = {skill["id"]: skill for skill in base.skills}
        for skill in incoming.skills:
            by_id[skill["id"]] = skill
        base.skills = sorted(by_id.values(), key=lambda item: item["id"])
    if incoming.card_name:
        base.card_name = incoming.card_name
    if incoming.card_description:
        base.card_description = incoming.card_description
    if incoming.card_skills:
        by_id = {skill["id"]: skill for skill in base.card_skills}
        for skill in incoming.card_skills:
            by_id[skill["id"]] = skill
        base.card_skills = sorted(by_id.values(), key=lambda item: item["id"])
    if incoming.addresses:
        seen = set(base.addresses)
        for addr in incoming.addresses:
            if addr not in seen:
                seen.add(addr)
                base.addresses.append(addr)
    return base


async def _fetch_peer_card(node: Any, peer_id: str) -> PeerCapability | None:
    """Best-effort AgentCard fetch for a connected peer."""

    get_card = getattr(node, "get_card", None)
    if not callable(get_card):
        return None
    card = await asyncio.wait_for(_maybe_await(get_card(peer_id)), timeout=3.0)
    return _normalise_card(peer_id, card)


def _display_name(peer: PeerCapability, registration: dict[str, Any] | None = None) -> str:
    return (
        peer.card_name
        or peer.name
        or (str(registration.get("name") or "").strip() if registration else "")
        or f"{peer.peer_id[:20]}... (skills unknown)"
    )


def _agency_names(
    peer: PeerCapability, registration: dict[str, Any] | None = None
) -> tuple[str, ...]:
    """Return all peer profile-name candidates used for agency namespace filtering."""

    names = [peer.card_name, peer.name]
    if registration:
        names.append(str(registration.get("name") or "").strip())
    return tuple(name.strip() for name in names if name and name.strip())


def is_agency_peer(peer: PeerCapability, registration: dict[str, Any] | None = None) -> bool:
    """Return True when a discovered peer belongs to the agency-* profile namespace."""

    return any(name.startswith("agency-") for name in _agency_names(peer, registration))


def team_context_filter(config: AgencyConfig | None = None) -> str:
    """Return the configured team-context filter mode."""

    cfg = config or get_config()
    value = str(getattr(cfg.team, "context_filter", "agency-only") or "agency-only").strip().lower()
    return value if value in {"agency-only", "all"} else "agency-only"


def filter_team_peers(
    peers: dict[str, PeerCapability],
    config: AgencyConfig | None = None,
    registrations: list[dict[str, Any]] | None = None,
) -> dict[str, PeerCapability]:
    """Return peers visible to team/orchestrator context under the configured filter."""

    if team_context_filter(config) == "all":
        return dict(peers)
    registered_by_peer = {str(item.get("peer_id")): item for item in registrations or []}
    return {
        peer_id: peer
        for peer_id, peer in peers.items()
        if is_agency_peer(peer, registered_by_peer.get(peer_id))
    }


def visible_team_state(config: AgencyConfig | None = None) -> dict[str, Any]:
    """Return the team cache as seen by prompts/status/info after filtering."""

    cfg = config or get_config()
    registrations = live_registrations(tenant=cfg.team.tenant)
    visible = filter_team_peers(_state.peers, cfg, registrations)
    return {
        "peers": {peer_id: peer.as_dict() for peer_id, peer in sorted(visible.items())},
        "last_refresh": _state.last_refresh,
        "last_error": _state.last_error,
        "refresh_count": _state.refresh_count,
        "context_filter": team_context_filter(cfg),
        "filtered_peer_count": len(visible),
    }


def visible_team_peer_count(config: AgencyConfig | None = None) -> int:
    """Return the number of teammates visible after team-context filtering."""

    cfg = config or get_config()
    if team_context_filter(cfg) == "agency-only":
        roster = _load_pool_roster()
        return len(
            [
                agent
                for agent in roster.get("profiles", [])
                if str(agent.get("name") or "").startswith("agency-")
            ]
        )
    return len(visible_team_state(cfg).get("peers") or {})


def _display_description(peer: PeerCapability, registration: dict[str, Any] | None = None) -> str:
    return (
        peer.card_description
        or peer.description
        or (str(registration.get("description") or "").strip() if registration else "")
    )


def _display_skills(
    peer: PeerCapability, registration: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    reg_skills = _normalise_skills(registration.get("skills") or []) if registration else []
    return peer.card_skills or peer.skills or reg_skills


def _enforce_context_budget(text: str, max_chars: int) -> str:
    """Hard-cap injected prompt context so team discovery cannot bloat turns."""

    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return "…"[:max_chars]
    return text[: max_chars - 1].rstrip() + "…"


def _format_skill(skill: dict[str, str]) -> str:
    return f"{skill['id']}" + (f" ({skill['description']})" if skill.get("description") else "")


def _team_context_limits(cfg: AgencyConfig) -> tuple[int, int, int]:
    return (
        max(1, int(getattr(cfg.team, "max_context_peers", 100) or 100)),
        max(1, int(getattr(cfg.team, "max_context_skills", 8) or 8)),
        max(240, int(getattr(cfg.team, "context_max_chars", 20000) or 20000)),
    )


def _discovery_skills(local_card: Any | None) -> list[str]:
    skills = []
    for skill in getattr(local_card, "skills", []) or []:
        skill_id = _skill_id(skill)
        if skill_id:
            skills.append(skill_id)
    # Always try the generic Hermes skill too; build_card() uses it when a
    # profile has no explicit skills, and it is cheap when the registry exists.
    skills.append("hermes-chat")
    seen: set[str] = set()
    unique: list[str] = []
    for skill in skills:
        if skill not in seen:
            seen.add(skill)
            unique.append(skill)
    # Cap discovery probes so startup cannot fan out across a huge skill list.
    return unique[:8]


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def refresh_capability_map(
    node: Any | None,
    *,
    local_peer_id: str | None = None,
    local_card: Any | None = None,
) -> dict[str, PeerCapability]:
    """Refresh the capability map from the live Hermes Agency node.

    Discovery is best-effort: ``list_peers()`` works for LAN/mDNS presence and
    ``discover()`` enriches cards/skills when anycast routing is configured. If
    either path fails, the other still updates the cache; if both fail, the
    previous cache is left intact and ``last_error`` records the problem.
    """

    if node is None:
        _state.peers = {}
        _state.last_refresh = time.time()
        _state.last_error = None
        _state.refresh_count += 1
        return {}

    discovered: dict[str, PeerCapability] = {}
    errors: list[str] = []

    # Extract relay peer ID to skip it — relay doesn't have real capabilities
    relay_peer_id = ""
    try:
        cfg = get_config()
        relay = cfg.relay or ""
        parts = relay.split("/p2p/")
        if len(parts) == 2:
            relay_peer_id = parts[-1].strip()
    except Exception:
        pass

    try:
        listed = await _maybe_await(node.list_peers())
        for item in listed or []:
            peer = _normalise_peer(item)
            if peer is None or peer.peer_id == local_peer_id:
                continue
            if relay_peer_id and peer.peer_id == relay_peer_id:
                continue  # skip relay node
            # Preserve any previously fetched card data while refreshing the
            # peer list. list_peers() only returns peer_id + addresses on the
            # current daemon, so the AgentCard cache is the source of names and
            # skills between successful get_card() calls.
            cached = _state.peers.get(peer.peer_id)
            if cached is not None:
                peer = _merge_peer(cached, peer)
            discovered[peer.peer_id] = _merge_peer(discovered.get(peer.peer_id), peer)
            try:
                card_peer = await _fetch_peer_card(node, peer.peer_id)
            except Exception as exc:
                errors.append(f"get_card({peer.peer_id[:12]}…): {type(exc).__name__}: {exc}")
            else:
                if card_peer is not None:
                    discovered[peer.peer_id] = _merge_peer(discovered.get(peer.peer_id), card_peer)
    except Exception as exc:
        errors.append(f"list_peers: {type(exc).__name__}: {exc}")

    # Phase 4 self-registration records are a secondary source of agent names
    # and skills. Use them to enrich listed peers when get_card() is unavailable
    # and to keep recently registered peers visible until discovery catches up.
    try:
        for item in live_registrations(tenant=get_config().team.tenant):
            peer = _normalise_registration(item)
            if peer is None or peer.peer_id == local_peer_id:
                continue
            if relay_peer_id and peer.peer_id == relay_peer_id:
                continue
            discovered[peer.peer_id] = _merge_peer(discovered.get(peer.peer_id), peer)
    except Exception as exc:
        errors.append(f"registrations: {type(exc).__name__}: {exc}")

    for skill in _discovery_skills(local_card):
        discover = getattr(node, "discover", None)
        if not callable(discover):
            break
        try:
            agents = await _maybe_await(discover(skill=skill, limit=25))
        except TypeError:
            try:
                agents = await _maybe_await(discover(skill, limit=25))
            except Exception as exc:  # pragma: no cover - SDK-version defensive
                errors.append(f"discover({skill}): {type(exc).__name__}: {exc}")
                continue
        except Exception as exc:
            errors.append(f"discover({skill}): {type(exc).__name__}: {exc}")
            continue
        for item in agents or []:
            peer = _normalise_peer(item)
            if peer is None or peer.peer_id == local_peer_id:
                continue
            discovered[peer.peer_id] = _merge_peer(discovered.get(peer.peer_id), peer)

    if discovered or not errors:
        # Replacing the map handles both joins and leaves. If no peers are
        # present this becomes an empty map without raising.
        _state.peers = dict(sorted(discovered.items()))
    _state.last_refresh = time.time()
    _state.last_error = "; ".join(errors) if errors and not discovered else None
    _state.refresh_count += 1
    _update_pool_roster_from_discovery(_state.peers)
    return _state.peers


def refresh_capability_map_sync(
    node: Any | None,
    *,
    local_peer_id: str | None = None,
    local_card: Any | None = None,
) -> dict[str, PeerCapability]:
    """Synchronous wrapper for tests/CLI helpers."""

    return asyncio.run(
        refresh_capability_map(node, local_peer_id=local_peer_id, local_card=local_card)
    )


def _is_pool_agent(name: str) -> bool:
    """Return True if the peer name indicates a pool-managed agent (agency-*)."""
    return name.startswith("agency-")


def _local_profile_skills(profile_name: str) -> list[dict[str, str]]:
    """Read skills from a local Hermes profile's skills directory.

    Returns an empty list when the profile doesn't exist locally or has no
    skills.  This is used to enrich discovered peers whose AgentCard or
    registration data is sparse (e.g. the daemon had no card set at startup).
    """

    try:
        from hermes_constants import get_hermes_home

        active_home = Path(get_hermes_home()).expanduser()
        if active_home.parent.name == "profiles":
            profiles_dir = active_home.parent
        else:
            profiles_dir = active_home / "profiles"
        skills_dir = profiles_dir / profile_name / "skills"
        if not skills_dir.exists():
            return []

        # Lazy import of the card-builder helpers to avoid circular deps.
        from .card_builder import read_profile_skills

        return read_profile_skills(profiles_dir / profile_name)
    except Exception:
        return []


def _enriched_skills(
    peer: PeerCapability,
    registration: dict[str, Any] | None = None,
    *,
    sparse_threshold: int = 5,
) -> list[dict[str, str]]:
    """Return display skills, enriching from local disk when sparse.

    When a peer has fewer than *sparse_threshold* skills (common when the
    daemon was started without a card), try reading from the local profile
    directory.  Only works on machines where the profile exists locally.
    """

    skills = _display_skills(peer, registration)
    if len(skills) >= sparse_threshold:
        return skills

    # Derive the profile name from the display label (card_name or peer name).
    profile_name = peer.card_name or peer.name
    if not profile_name:
        return skills

    local = _local_profile_skills(profile_name)
    return local if len(local) > len(skills) else skills


def _render_peer(
    peer: PeerCapability,
    registration: dict[str, Any] | None,
    max_skills: int,
) -> list[str]:
    """Render a single peer entry for the team context."""

    lines: list[str] = []
    label = _display_name(peer, registration)
    skills = _enriched_skills(peer, registration)
    if skills:
        skill_text = ", ".join(_format_skill(skill) for skill in skills[:max_skills])
        omitted_skills = len(skills) - max_skills
        if omitted_skills > 0:
            skill_text = f"{skill_text}, … (+{omitted_skills} more)"
        lines.append(f"- {label} — skills: {skill_text}")
    else:
        lines.append(f"- {label}")
        lines.append(
            "  Top skills: unknown from peer discovery; direct peer delegation is still available."
        )
    description = _display_description(peer, registration)
    if description:
        lines.append(f"  Description: {description}")
    lines.append(f"  peer_id: {peer.peer_id}")
    return lines


def _format_last_seen(timestamp: Any) -> str:
    try:
        seconds = max(0, time.time() - float(timestamp))
    except (TypeError, ValueError):
        return "never"
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    if hours < 48:
        return f"{hours}h ago"
    return f"{int(hours // 24)}d ago"


def _render_roster_agent(agent: dict[str, Any], max_skills: int) -> list[str]:
    """Render a persistent roster entry with online/offline status."""

    skills = [str(skill) for skill in agent.get("skills") or [] if str(skill).strip()]
    status = "ONLINE" if agent.get("online") else "OFFLINE"
    skill_text = ", ".join(skills[:max_skills]) or "unknown"
    omitted_skills = len(skills) - max_skills
    if omitted_skills > 0:
        skill_text = f"{skill_text}, … (+{omitted_skills} more)"
    line = f"- {agent.get('name')} — skills: {skill_text} [{status}]"
    if agent.get("online") and agent.get("peer_id"):
        line += f" peer_id: {agent['peer_id']}"
    elif agent.get("last_seen"):
        line += f" last_seen: {_format_last_seen(agent.get('last_seen'))}"
    else:
        line += " last_seen: never"

    lines = [line]
    description = str(agent.get("description") or "").strip()
    if description:
        lines.append(f"  Description: {description}")
    if agent.get("model") or agent.get("provider"):
        lines.append(
            f"  model/provider: {agent.get('model') or 'unknown'} / {agent.get('provider') or 'unknown'}"
        )
    if agent.get("last_wake_attempt_at"):
        wake = _format_last_seen(agent.get("last_wake_attempt_at"))
        wake_count = int(agent.get("wake_attempt_count") or 0)
        wake_text = f"  wake attempts: {wake_count}; last_attempt: {wake}"
        if agent.get("last_wake_error"):
            wake_text += f"; last_error: {agent.get('last_wake_error')}"
        lines.append(wake_text)
    return lines


def build_team_context(config: AgencyConfig | None = None) -> str:
    """Build the prompt block that tells an agent about available teammates.

    Returns an empty string when injection is disabled. By default, only peers
    whose card/profile name starts with ``agency-`` are visible so orchestrators
    do not see personal Hermes profiles as delegation targets. Set
    ``agency.team.context_filter: all`` only for debugging the raw directory.
    """

    cfg = config or get_config()
    if not cfg.team.inject_context:
        return ""

    registrations = live_registrations(tenant=cfg.team.tenant)
    registered_by_peer = {str(item.get("peer_id")): item for item in registrations}
    all_by_peer: dict[str, PeerCapability] = dict(_state.peers)
    for item in registrations:
        peer = _normalise_registration(item)
        if peer is not None:
            all_by_peer[peer.peer_id] = _merge_peer(all_by_peer.get(peer.peer_id), peer)

    visible_by_peer = filter_team_peers(all_by_peer, cfg, registrations)
    visible_peers = list(visible_by_peer.values())
    filter_mode = team_context_filter(cfg)

    max_peers, max_skills, max_chars = _team_context_limits(cfg)
    lines = [
        "Hermes Agency team context:",
        f"Tenant: {cfg.team.tenant}",
        f"Team context filter: {filter_mode}",
    ]

    def sort_key(item: PeerCapability) -> str:
        return _display_name(item, registered_by_peer.get(item.peer_id)).lower()

    def _render_section(
        section_peers: list[PeerCapability],
        header: str,
        budget: int,
    ) -> list[str]:
        section_lines: list[str] = []
        if not section_peers:
            return section_lines
        section_lines.append(header)
        shown = section_peers[:budget]
        for peer in shown:
            registration = registered_by_peer.get(peer.peer_id)
            section_lines.extend(_render_peer(peer, registration, max_skills))
        omitted = len(section_peers) - len(shown)
        if omitted > 0:
            section_lines.append(
                f"  ({omitted} more omitted — use agency_discover for the full list.)"
            )
        return section_lines

    if filter_mode == "agency-only":
        roster = _load_pool_roster()
        roster_agents = sorted(
            [
                agent
                for agent in roster.get("profiles", [])
                if str(agent.get("name", "")).startswith("agency-")
            ],
            key=lambda item: str(item.get("name") or "").lower(),
        )
        lines.append(
            f"Registered agency roster: {roster.get('online', 0)}/{roster.get('total', len(roster_agents))} online"
        )
        lines.append(
            "Use skill fit first when delegating. Offline agents are still valid targets: "
            "agency_pool_send/orchestrator routing will attempt wake and persistently queue if wake fails."
        )
        if not roster_agents:
            # The static registry should normally prevent this branch; keep a
            # diagnostic instead of the old misleading "no teammates" message.
            lines.append(
                "Roster registry unavailable; no agency-* agents loaded from registry_definition.json."
            )
        else:
            shown = roster_agents[:max_peers]
            for agent in shown:
                lines.extend(_render_roster_agent(agent, max_skills))
            omitted = len(roster_agents) - len(shown)
            if omitted > 0:
                lines.append(
                    f"{omitted} more registered agency teammate agent(s) omitted by context budget. "
                    "Use agency_roster for the full persistent roster."
                )
    else:
        pool_peers: list[PeerCapability] = []
        personal_peers: list[PeerCapability] = []
        for peer in visible_peers:
            registration = registered_by_peer.get(peer.peer_id)
            if is_agency_peer(peer, registration):
                pool_peers.append(peer)
            else:
                personal_peers.append(peer)
        pool_peers.sort(key=sort_key)
        personal_peers.sort(key=sort_key)

        if pool_peers and personal_peers:
            pool_budget = min(len(pool_peers), max(1, max_peers // 2))
            personal_budget = min(len(personal_peers), max_peers - pool_budget)
        elif pool_peers:
            pool_budget = min(len(pool_peers), max_peers)
            personal_budget = 0
        else:
            pool_budget = 0
            personal_budget = min(len(personal_peers), max_peers)

        lines.append("The following teammate agents are currently discoverable on the A2A network.")
        lines.extend(_render_section(pool_peers, "Pool agents (agency-*):", pool_budget))
        lines.extend(_render_section(personal_peers, "Personal agents:", personal_budget))

        total_shown = min(len(pool_peers), pool_budget) + min(len(personal_peers), personal_budget)
        total_peers = len(pool_peers) + len(personal_peers)
        total_omitted = total_peers - total_shown
        if total_omitted > 0:
            lines.append(
                f"{total_omitted} more teammate agent(s) omitted from this compact prompt context. "
                "Use agency_discover for the full live directory."
            )

    lines.append(
        "To delegate directly, call agency_send with the target peer_id and a clear task message. "
        "The Hermes Agency plugin will wrap the message in a structured context packet automatically."
    )
    return _enforce_context_budget("\n".join(lines), max_chars)
