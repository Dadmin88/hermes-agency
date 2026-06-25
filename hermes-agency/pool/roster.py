"""Persistent roster of all agency profiles.

The static registry_definition.json is the source of truth for which
``agency-*`` agents exist and what they are good at.  Runtime discovery only
adds the volatile transport overlay: peer_id, online, and last_seen.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any

REGISTRY_DEFINITION_PATH = Path(__file__).with_name("registry_definition.json")
ROSTER_STATE_FILENAME = "roster_state.json"
OFFLINE_QUEUE_FILENAME = "offline_task_queue.json"
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_PROVIDER = "openai-codex"
# Test/diagnostic override hooks. Normal runtime uses HERMES_HOME-aware helpers
# below so profile-scoped gateway sessions still see the shared root roster.
PROFILES: Path | None = None
LEGACY_ROSTER_PATH: Path | None = None


def _root_hermes_home() -> Path:
    """Return the installation-level Hermes home for shared profile data."""

    hermes_home = os.getenv("HERMES_HOME", "").strip()
    active_home = Path(hermes_home).expanduser() if hermes_home else Path.home() / ".hermes"
    if active_home.parent.name == "profiles":
        return active_home.parent.parent
    return active_home


def _profiles_dir() -> Path:
    """Return the shared profiles directory, independent of the active profile."""

    if PROFILES is not None:
        return PROFILES
    return _root_hermes_home() / "profiles"


def _legacy_roster_path() -> Path:
    if LEGACY_ROSTER_PATH is not None:
        return LEGACY_ROSTER_PATH
    return _root_hermes_home() / "pool" / "roster.json"


def _plugin_setup_module():
    """Load pool.plugin_setup in package and direct-script execution modes."""

    try:
        from . import plugin_setup

        return plugin_setup
    except ImportError:
        module_path = Path(__file__).with_name("plugin_setup.py")
        spec = importlib.util.spec_from_file_location(
            "hermes_agency_pool_plugin_setup", module_path
        )
        if spec is None or spec.loader is None:
            raise
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def ensure_profile_plugins() -> dict[str, Any]:
    """Ensure every Hermes profile can load the Hermes Agency plugin."""

    plugin_setup = _plugin_setup_module()
    return plugin_setup.setup_all_profile_plugins(include_main=True)


def _default_shared_agency_home() -> Path:
    """Return the installation-level agency home shared by all pool profiles."""

    return _root_hermes_home() / ".agency"


def _agency_home() -> Path:
    """Return the shared Hermes Agency pool-state directory.

    Pool roster and offline queue state are installation-level data: every
    ``agency-*`` profile needs to see the same roster when rendering team
    context.  Profile-local daemon state still lives under each profile's
    ``.agency`` directory via ``config.get_config().home``; this helper is only
    for pool state files.  Older profile-local roster snapshots can be stale, so
    ignore the implicit ``<profile>/.agency`` default and use the root
    ``~/.hermes/.agency`` path instead.  Explicit non-default ``agency.home``
    overrides are still respected.
    """

    shared_home = _default_shared_agency_home()
    try:
        from ..config import get_config

        cfg = get_config()
        cfg_home = Path(cfg.home).expanduser() if cfg.home else None
        hermes_home = os.getenv("HERMES_HOME", "").strip()
        active_home = Path(hermes_home).expanduser() if hermes_home else Path.home() / ".hermes"
        implicit_profile_home = (
            active_home / ".agency" if active_home.parent.name == "profiles" else None
        )
        if cfg_home and cfg_home != implicit_profile_home:
            return cfg_home
    except Exception:
        pass
    return shared_home


def roster_state_path() -> Path:
    """Return the persistent roster-state path under agency.home."""

    return _agency_home() / ROSTER_STATE_FILENAME


def offline_queue_path() -> Path:
    """Return the persistent offline outbound queue path under agency.home."""

    return _agency_home() / OFFLINE_QUEUE_FILENAME


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _normalise_skill_id(value: Any) -> str:
    return " ".join(str(value or "").replace("_", "-").split()).strip().lower()


def _normalise_skills(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    skills: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            skill = _normalise_skill_id(item.get("id") or item.get("name") or item.get("skill_id"))
        else:
            skill = _normalise_skill_id(item)
        if skill and skill not in seen:
            seen.add(skill)
            skills.append(skill)
    return skills


def _derive_capabilities(skills: list[str]) -> list[dict[str, str]]:
    """Derive capability records from static registry skills."""

    return [{"id": skill, "description": f"Can handle {skill} tasks"} for skill in skills]


def _read_yaml_file(path: Path) -> dict[str, Any]:
    """Best-effort YAML reader for profile config overlays.

    Roster generation runs in CLI, gateway, and direct-script contexts. Prefer
    PyYAML when available, but keep a tiny one-level fallback so model/provider
    metadata still works in stripped-down environments.
    """

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}

    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        data: dict[str, Any] = {}
        current_parent: str | None = None
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            key, _, value = stripped.partition(":")
            key = key.strip()
            parsed = value.strip().strip("\"'")
            if indent == 0 and not parsed:
                data[key] = {}
                current_parent = key
            elif indent > 0 and current_parent and isinstance(data.get(current_parent), dict):
                data[current_parent][key] = parsed
            elif indent == 0:
                data[key] = parsed
                current_parent = None
        return data


def _read_profile_model(profile_dir: Path) -> dict[str, str]:
    """Read public model/provider display fields from a profile config.yaml."""

    config = _read_yaml_file(profile_dir / "config.yaml")
    model_cfg = config.get("model") if isinstance(config, dict) else {}
    if not isinstance(model_cfg, dict):
        return {}

    model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
    provider = str(model_cfg.get("provider") or "").strip()
    meta: dict[str, str] = {}
    if model:
        meta["model"] = model
    if provider:
        meta["provider"] = provider
    return meta


def _read_card_model(card: dict[str, Any]) -> dict[str, str]:
    """Extract model/provider metadata from a serialized AgentCard when present."""

    metadata = card.get("metadata") if isinstance(card, dict) else {}
    hermes_meta = metadata.get("hermes") if isinstance(metadata, dict) else {}
    model_meta = hermes_meta.get("model") if isinstance(hermes_meta, dict) else {}
    if not isinstance(model_meta, dict):
        return {}
    model = str(model_meta.get("default") or model_meta.get("model") or "").strip()
    provider = str(model_meta.get("provider") or "").strip()
    result: dict[str, str] = {}
    if model:
        result["model"] = model
    if provider:
        result["provider"] = provider
    return result


def _registry_agents() -> list[dict[str, Any]]:
    data = _load_json(REGISTRY_DEFINITION_PATH)
    agents = data.get("agents") or []
    if not isinstance(agents, list):
        return []

    normalised: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in agents:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name.startswith("agency-") or name in seen:
            continue
        seen.add(name)
        skills = _normalise_skills(item.get("skills") or [])
        normalised.append(
            {
                "name": name,
                "description": str(item.get("description") or "").strip(),
                "skills": skills,
                "skill_count": len(skills),
                "capabilities": _derive_capabilities(skills),
                "category": str(item.get("category") or "").strip() or None,
                "model": str(item.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
                "provider": str(item.get("provider") or DEFAULT_PROVIDER).strip()
                or DEFAULT_PROVIDER,
                "peer_id": None,
                "online": False,
                "last_seen": None,
                "last_wake_attempt_at": None,
                "wake_attempt_count": 0,
                "last_wake_error": None,
            }
        )
    return normalised


def _read_profile_meta(profile_dir: Path) -> dict[str, Any]:
    """Read minimal metadata from a profile directory as a fallback overlay."""

    name = profile_dir.name
    soul = profile_dir / "SOUL.md"

    description = ""
    if soul.exists():
        try:
            for line in soul.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    description = line[:200]
                    break
        except Exception:
            pass

    skills: list[str] = []
    skills_dir = profile_dir / "skills"
    if skills_dir.exists():
        for sf in sorted(skills_dir.glob("**/SKILL.md")):
            try:
                for line in sf.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.strip().startswith("name:"):
                        skill_name = _normalise_skill_id(line.split(":", 1)[1].strip().strip("\"'"))
                        if skill_name:
                            skills.append(skill_name)
                        break
            except Exception:
                pass

    meta = {
        "name": name,
        "description": description,
        "skills": skills[:20],
        "skill_count": len(skills),
        "capabilities": _derive_capabilities(skills[:20]),
    }
    meta.update(_read_profile_model(profile_dir))
    return meta


def _is_daemon_running(name: str) -> bool:
    """Best-effort check that a profile's daemon process/socket is alive."""

    profiles = _profiles_dir()
    for dirname in (".agency", ".agentanycast"):
        sock = profiles / name / dirname / "daemon.sock"
        if sock.exists():
            return True
    return False


def _read_peer_id(name: str) -> str | None:
    """Read this profile's own peer_id from daemon logs if available."""

    import re

    profiles = _profiles_dir()
    patterns = [
        profiles / name / ".agency" / "logs" / "daemon.log",
        profiles / name / ".agentanycast" / "logs" / "daemon.log",
    ]
    for log in patterns:
        if not log.exists():
            continue
        try:
            text = log.read_text(encoding="utf-8", errors="ignore")[-50000:]
            for pattern in (
                r'"peer_id"\s*:\s*"(12D3KooW[^"]+)"',
                r"^PEER_ID=(12D3KooW\S+)",
            ):
                m = re.search(pattern, text, re.MULTILINE)
                if m:
                    return m.group(1)
        except Exception:
            pass
    return None


def _persisted_state_by_name() -> dict[str, dict[str, Any]]:
    data = _load_json(roster_state_path())
    legacy_roster_path = _legacy_roster_path()
    if not data and legacy_roster_path.exists():
        data = _load_json(legacy_roster_path)
    profiles = data.get("profiles") or []
    if not isinstance(profiles, list):
        return {}
    return {
        str(item.get("name") or "").strip(): item
        for item in profiles
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }


def _normalise_live_peer(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        peer_id = str(item.get("peer_id") or item.get("id") or item.get("did") or "").strip()
        card = item.get("card") or item.get("agent_card") or {}
        if not isinstance(card, dict):
            card = {}
        name = str(
            item.get("card_name")
            or item.get("agent_name")
            or item.get("name")
            or card.get("name")
            or ""
        ).strip()
        description = str(
            item.get("card_description")
            or item.get("agent_description")
            or item.get("description")
            or card.get("description")
            or ""
        ).strip()
        skills = _normalise_skills(
            item.get("card_skills") or item.get("skills") or card.get("skills") or []
        )
        model_meta = _read_card_model(card)
    else:
        peer_id = str(getattr(item, "peer_id", "") or getattr(item, "id", "") or "").strip()
        name = str(getattr(item, "card_name", "") or getattr(item, "name", "") or "").strip()
        description = str(
            getattr(item, "card_description", "") or getattr(item, "description", "") or ""
        ).strip()
        skills = _normalise_skills(
            getattr(item, "card_skills", None) or getattr(item, "skills", None) or []
        )
        model_meta = {}
    if not peer_id and not name:
        return None
    peer = {"peer_id": peer_id or None, "name": name, "description": description, "skills": skills}
    peer.update(model_meta)
    return peer


def _merge_agent(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key in (
        "description",
        "category",
        "model",
        "provider",
        "peer_id",
        "last_seen",
        "last_wake_attempt_at",
        "wake_attempt_count",
        "last_wake_error",
    ):
        value = overlay.get(key)
        if value not in (None, ""):
            merged[key] = value
    if overlay.get("skills") and not merged.get("skills"):
        skills = _normalise_skills(overlay["skills"])
        if skills:
            merged["skills"] = skills
            merged["skill_count"] = len(skills)
            merged["capabilities"] = _derive_capabilities(skills)
    return merged


def build_roster(
    live_peers: list[Any] | dict[str, Any] | None = None,
    *,
    include_plugin_setup: bool = True,
) -> dict[str, Any]:
    """Build a roster from registry_definition.json plus runtime overlays.

    ``registry_definition.json`` is always the base source of truth.  Persisted
    state contributes historical fields such as last_seen and wake attempts.
    Live discovery or daemon/socket checks mark entries online for the current
    runtime view.
    """

    plugin_summary: dict[str, Any] = {}
    if include_plugin_setup:
        try:
            plugin_summary = ensure_profile_plugins()
        except Exception as exc:
            plugin_summary = {"error": f"{type(exc).__name__}: {exc}"}

    persisted = _persisted_state_by_name()
    agents_by_name: dict[str, dict[str, Any]] = {}
    for agent in _registry_agents():
        saved = persisted.get(agent["name"], {})
        merged = _merge_agent(agent, saved)
        # Current online status is volatile.  Keep historical peer_id/last_seen
        # from state, but recompute online from live sources below.
        merged["online"] = False
        agents_by_name[agent["name"]] = merged

    profiles_dir = _profiles_dir()
    if profiles_dir.is_dir():
        for profile_dir in sorted(profiles_dir.iterdir()):
            if not profile_dir.is_dir() or not profile_dir.name.startswith("agency-"):
                continue
            meta = _read_profile_meta(profile_dir)
            if profile_dir.name not in agents_by_name:
                skills = _normalise_skills(meta.get("skills") or [])
                agents_by_name[profile_dir.name] = {
                    "name": profile_dir.name,
                    "description": meta.get("description") or "",
                    "skills": skills,
                    "skill_count": len(skills),
                    "capabilities": _derive_capabilities(skills),
                    "category": None,
                    "model": meta.get("model") or DEFAULT_MODEL,
                    "provider": meta.get("provider") or DEFAULT_PROVIDER,
                    "peer_id": None,
                    "online": False,
                    "last_seen": None,
                    "last_wake_attempt_at": None,
                    "wake_attempt_count": 0,
                    "last_wake_error": None,
                }
            else:
                agents_by_name[profile_dir.name] = _merge_agent(
                    agents_by_name[profile_dir.name], meta
                )
            if _is_daemon_running(profile_dir.name):
                agents_by_name[profile_dir.name]["online"] = True
                agents_by_name[profile_dir.name]["last_seen"] = time.time()
                peer_id = _read_peer_id(profile_dir.name)
                if peer_id:
                    agents_by_name[profile_dir.name]["peer_id"] = peer_id

    raw_live_items: list[Any]
    if isinstance(live_peers, dict):
        raw_live_items = list(live_peers.values())
    elif isinstance(live_peers, list):
        raw_live_items = live_peers
    else:
        raw_live_items = []

    for raw_peer in raw_live_items:
        peer = _normalise_live_peer(raw_peer)
        if peer is None:
            continue
        name = peer.get("name") or ""
        if not name.startswith("agency-"):
            continue
        if name not in agents_by_name:
            skills = _normalise_skills(peer.get("skills") or [])
            agents_by_name[name] = {
                "name": name,
                "description": peer.get("description") or "",
                "skills": skills,
                "skill_count": len(skills),
                "capabilities": _derive_capabilities(skills),
                "category": None,
                "model": peer.get("model") or DEFAULT_MODEL,
                "provider": peer.get("provider") or DEFAULT_PROVIDER,
                "peer_id": None,
                "online": False,
                "last_seen": None,
                "last_wake_attempt_at": None,
                "wake_attempt_count": 0,
                "last_wake_error": None,
            }
        else:
            # Runtime discovery is only a volatile transport overlay for known
            # pool agents.  Local registry/profile metadata is authoritative for
            # descriptions, skills, and model/provider display: live AgentCards
            # can be stale (or started under a previous provider) and should not
            # rewrite prompt context for every future roster render.
            peer = {
                key: value
                for key, value in peer.items()
                if key
                in {
                    "peer_id",
                    "last_seen",
                    "last_wake_attempt_at",
                    "wake_attempt_count",
                    "last_wake_error",
                }
            }
            agents_by_name[name] = _merge_agent(agents_by_name[name], peer)
        agents_by_name[name]["online"] = True
        agents_by_name[name]["last_seen"] = time.time()
        if peer.get("peer_id"):
            agents_by_name[name]["peer_id"] = peer["peer_id"]

    profiles = []
    for name in sorted(agents_by_name):
        agent = agents_by_name[name]
        if not agent.get("online"):
            agent["peer_id"] = None
        profiles.append(agent)
    roster = {
        "version": 2,
        "updated_at": time.time(),
        "source": str(REGISTRY_DEFINITION_PATH),
        "state_path": str(roster_state_path()),
        "total": len(profiles),
        "online": sum(1 for p in profiles if p.get("online")),
        "profiles": profiles,
    }
    if plugin_summary:
        try:
            roster["plugin_setup"] = _plugin_setup_module().compact_setup_summary(plugin_summary)
        except Exception:
            roster["plugin_setup"] = plugin_summary
    return roster


def save_roster(roster: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build and save the roster state to ``<agency_home>/roster_state.json``."""

    if roster is None:
        roster = build_roster()
    _atomic_write_json(roster_state_path(), roster)
    return roster


def load_roster() -> dict[str, Any]:
    """Load persistent roster state merged with the static registry.

    This never returns an empty "no teammates" roster when
    ``registry_definition.json`` is present; offline agents remain listed with
    ``online=false`` and their last known peer_id/last_seen metadata.
    """

    return save_roster(build_roster())


def update_roster_from_discovery(peers: list[Any] | dict[str, Any] | None) -> dict[str, Any]:
    """Overlay live discovery data and persist the updated roster."""

    return save_roster(build_roster(live_peers=peers, include_plugin_setup=False))


def update_agent_status(
    name: str,
    *,
    online: bool,
    peer_id: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Persist a profile start/stop status update in roster_state.json."""

    if not name.startswith("agency-"):
        name = f"agency-{name}"
    roster = build_roster(include_plugin_setup=False)
    now = time.time()
    for agent in roster.get("profiles", []):
        if agent.get("name") != name:
            continue
        agent["online"] = bool(online)
        if online:
            agent["last_seen"] = now
            if peer_id:
                agent["peer_id"] = peer_id
            agent["last_wake_error"] = None
        else:
            agent["peer_id"] = None
        if error:
            agent["last_wake_error"] = error
        break
    else:
        roster.setdefault("profiles", []).append(
            {
                "name": name,
                "description": "",
                "skills": [],
                "skill_count": 0,
                "capabilities": [],
                "category": None,
                "model": DEFAULT_MODEL,
                "provider": DEFAULT_PROVIDER,
                "peer_id": peer_id,
                "online": bool(online),
                "last_seen": now if online else None,
                "last_wake_attempt_at": None,
                "wake_attempt_count": 0,
                "last_wake_error": error,
            }
        )
    roster["updated_at"] = now
    roster["total"] = len(roster.get("profiles") or [])
    roster["online"] = sum(1 for p in roster.get("profiles", []) if p.get("online"))
    return save_roster(roster)


def record_wake_attempt(
    name: str,
    *,
    success: bool,
    peer_id: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Record an offline-agent wake attempt to avoid blind retry spam."""

    if not name.startswith("agency-"):
        name = f"agency-{name}"
    roster = build_roster(include_plugin_setup=False)
    now = time.time()
    for agent in roster.get("profiles", []):
        if agent.get("name") == name:
            agent["last_wake_attempt_at"] = now
            agent["wake_attempt_count"] = int(agent.get("wake_attempt_count") or 0) + 1
            agent["last_wake_error"] = None if success else (error or "wake failed")
            agent["online"] = bool(success)
            if success:
                agent["last_seen"] = now
                if peer_id:
                    agent["peer_id"] = peer_id
            break
    roster["updated_at"] = now
    roster["online"] = sum(1 for p in roster.get("profiles", []) if p.get("online"))
    return save_roster(roster)


def queue_offline_task(
    name: str,
    message: str,
    *,
    metadata: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Persist an outbound task for an agent that cannot be woken now."""

    if not name.startswith("agency-"):
        name = f"agency-{name}"
    path = offline_queue_path()
    data = _load_json(path) or {"version": 1, "tasks": []}
    tasks = data.setdefault("tasks", [])
    if not isinstance(tasks, list):
        tasks = []
        data["tasks"] = tasks
    queued_at = time.time()
    task = {
        "id": f"offline-{int(queued_at * 1000)}-{len(tasks) + 1}",
        "target_agent": name,
        "message": message,
        "metadata": metadata or {},
        "reason": reason or "agent offline",
        "status": "queued",
        "attempts": 0,
        "queued_at": queued_at,
        "updated_at": queued_at,
    }
    tasks.append(task)
    data["updated_at"] = queued_at
    _atomic_write_json(path, data)
    return {"ok": True, "queue_path": str(path), "task": task, "queued_count": len(tasks)}


def load_offline_queue() -> dict[str, Any]:
    """Return the persistent outbound offline queue."""

    data = _load_json(offline_queue_path())
    return data if data else {"version": 1, "tasks": []}


def find_agent(query: str) -> dict[str, Any] | None:
    """Find an agent by name, skill, or role keyword."""

    roster = load_roster()
    q = query.lower().strip()

    for p in roster["profiles"]:
        if p["name"] == q or p["name"] == f"agency-{q}":
            return p

    for p in roster["profiles"]:
        for skill in p.get("skills", []):
            if q in skill.lower():
                return p

    for p in roster["profiles"]:
        if q in p.get("description", "").lower():
            return p

    return None


if __name__ == "__main__":
    current = save_roster()
    setup = current.get("plugin_setup", {})
    print(
        f"Roster saved: {current['online']}/{current['total']} agency profiles online "
        f"({current.get('state_path')})"
    )
    print(
        "Plugin setup: "
        f"{setup.get('profiles_updated', 0)} updated, "
        f"{setup.get('profiles_already', 0)} already, "
        f"{setup.get('profiles_errors', 0)} profile errors, "
        f"main={setup.get('main_status', 'skipped')}"
    )
