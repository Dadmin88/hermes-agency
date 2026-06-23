"""Persistent roster of all agency profiles.

Maintains ~/.hermes/pool/roster.json so any agent can check who exists,
who's online, what they do, and how to reach them.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from typing import Any

PROFILES = Path.home() / ".hermes" / "profiles"
ROSTER_PATH = Path.home() / ".hermes" / "pool" / "roster.json"


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


def _read_profile_meta(profile_dir: Path) -> dict[str, Any]:
    """Read minimal metadata from a profile directory."""
    name = profile_dir.name
    soul = profile_dir / "SOUL.md"

    description = ""
    if soul.exists():
        try:
            for line in soul.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    description = line[:200]
                    break
        except Exception:
            pass

    # Read skills list
    skills = []
    skills_dir = profile_dir / "skills"
    if skills_dir.exists():
        for sf in sorted(skills_dir.glob("**/SKILL.md")):
            try:
                for line in sf.read_text().splitlines():
                    if line.strip().startswith("name:"):
                        skill_name = line.split(":", 1)[1].strip().strip("\"'")
                        if skill_name:
                            skills.append(skill_name)
                        break
            except Exception:
                pass

    return {
        "name": name,
        "description": description,
        "skills": skills[:20],  # cap for roster
        "skill_count": len(skills),
    }


def _is_daemon_running(name: str) -> bool:
    """Check if a profile's daemon process is alive."""
    sock = PROFILES / name / ".agency" / "daemon.sock"
    return sock.exists()


def _read_peer_id(name: str) -> str | None:
    """Read peer_id from daemon log if available."""
    log = PROFILES / name / ".agency" / "logs" / "daemon.log"
    if not log.exists():
        return None
    try:
        import re

        text = log.read_text()
        m = re.search(r'"peer_id":"(12D3KooW[^"]+)"', text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def build_roster() -> dict[str, Any]:
    """Build a fresh roster from the filesystem."""
    plugin_summary = ensure_profile_plugins()
    profiles = []
    if not PROFILES.is_dir():
        return {
            "updated_at": time.time(),
            "total": 0,
            "online": 0,
            "profiles": [],
            "plugin_setup": _plugin_setup_module().compact_setup_summary(plugin_summary),
        }

    for d in sorted(PROFILES.iterdir()):
        if not d.is_dir() or not d.name.startswith("agency-"):
            continue
        meta = _read_profile_meta(d)
        online = _is_daemon_running(d.name)
        peer_id = _read_peer_id(d.name) if online else None
        profiles.append(
            {
                **meta,
                "online": online,
                "peer_id": peer_id,
            }
        )

    roster = {
        "updated_at": time.time(),
        "total": len(profiles),
        "online": sum(1 for p in profiles if p["online"]),
        "profiles": profiles,
        "plugin_setup": _plugin_setup_module().compact_setup_summary(plugin_summary),
    }
    return roster


def save_roster(roster: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build and save the roster to disk."""
    if roster is None:
        roster = build_roster()
    ROSTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROSTER_PATH.write_text(json.dumps(roster, indent=2))
    return roster


def load_roster() -> dict[str, Any]:
    """Load roster from disk, or build fresh if missing/stale."""
    if ROSTER_PATH.exists():
        try:
            data = json.loads(ROSTER_PATH.read_text())
            # Refresh if older than 5 minutes
            if time.time() - data.get("updated_at", 0) < 300:
                # Symlink setup is idempotent and should happen even when roster
                # data is fresh, so newly created profiles do not wait for cache
                # expiry before becoming Agency-capable.
                plugin_summary = ensure_profile_plugins()
                data["plugin_setup"] = _plugin_setup_module().compact_setup_summary(plugin_summary)
                return data
        except Exception:
            pass
    return save_roster()


def find_agent(query: str) -> dict[str, Any] | None:
    """Find an agent by name, skill, or role keyword."""
    roster = load_roster()
    q = query.lower().strip()

    # Exact name match
    for p in roster["profiles"]:
        if p["name"] == q or p["name"] == f"agency-{q}":
            return p

    # Skill match
    for p in roster["profiles"]:
        for skill in p.get("skills", []):
            if q in skill.lower():
                return p

    # Description match
    for p in roster["profiles"]:
        if q in p.get("description", "").lower():
            return p

    return None


if __name__ == "__main__":
    current = save_roster()
    setup = current.get("plugin_setup", {})
    print(f"Roster saved: {current['online']}/{current['total']} agency profiles online")
    print(
        "Plugin setup: "
        f"{setup.get('profiles_updated', 0)} updated, "
        f"{setup.get('profiles_already', 0)} already, "
        f"{setup.get('profiles_errors', 0)} profile errors, "
        f"main={setup.get('main_status', 'skipped')}"
    )
