"""Pool tools for Hermes Agency — simple protocol any agent can use.

Tools:
  pool_roster   — See all agents, who's online, what they do
  pool_wake     — Start an agent's daemon
  pool_sleep    — Stop an agent's daemon
  pool_send     — Send work to an agent (auto-wakes if offline)
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .roster import build_roster, ensure_profile_plugins, find_agent, load_roster, save_roster

PROFILES = Path.home() / ".hermes" / "profiles"
RELAY = "/ip4/100.123.57.115/tcp/4001/p2p/12D3KooWGE3zmqw2FJTyuNGAzSNCUxSNSeMvCtocULczXfX9Y8nK"
HERMES_BIN = Path.home() / ".hermes" / ".agentanycast" / "bin" / "agentanycastd"
STARTUP_WAIT = 12


def pool_roster(query: str = "", show_offline: bool = True) -> str:
    """Show the agency roster. Optionally filter by query."""
    roster = load_roster()
    profiles = roster["profiles"]

    if query:
        q = query.lower()
        profiles = [
            p
            for p in profiles
            if q in p["name"].lower()
            or any(q in s.lower() for s in p.get("skills", []))
            or q in p.get("description", "").lower()
        ]

    if not show_offline:
        profiles = [p for p in profiles if p["online"]]

    lines = [f"Agency roster: {roster['online']}/{roster['total']} online"]
    for p in profiles:
        status = "🟢" if p["online"] else "⚫"
        skills_str = ", ".join(p.get("skills", [])[:5])
        if p.get("skill_count", 0) > 5:
            skills_str += f" +{p['skill_count'] - 5}"
        lines.append(f"  {status} {p['name']} — {skills_str}")

    return "\n".join(lines)


def pool_wake(name: str) -> str:
    """Wake an agency profile — start its daemon and register it."""
    if not name.startswith("agency-"):
        name = f"agency-{name}"

    profile_dir = PROFILES / name
    if not profile_dir.exists():
        return f"Error: profile {name} not found"

    setup = ensure_profile_plugins()
    if setup.get("profiles_errors"):
        return (
            "Error: Hermes Agency plugin setup failed for "
            f"{setup['profiles_errors']} profile(s); run `hermes agency setup-plugins`."
        )

    # Check if already running
    sock = profile_dir / ".agency" / "daemon.sock"
    if sock.exists():
        # Refresh roster
        save_roster(build_roster())
        return f"{name} is already online"

    # Ensure binary
    bin_path = profile_dir / ".agency" / "bin" / "agentanycastd"
    if not bin_path.exists() and HERMES_BIN.exists():
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(HERMES_BIN, bin_path)
        bin_path.chmod(0o755)

    if not bin_path.exists():
        return f"Error: no daemon binary for {name}"

    # Clean stale locks
    for f in (profile_dir / ".agency").rglob("*.lock"):
        f.unlink(missing_ok=True)
    if sock.exists():
        sock.unlink()

    key = profile_dir / ".agency" / "key"
    log = profile_dir / ".agency" / "logs" / "daemon.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("")

    proc = subprocess.Popen(
        [
            str(bin_path),
            f"--key={key}",
            f"--grpc-listen=unix://{sock}",
            "--log-level=info",
            f"--bootstrap-peers={RELAY}",
        ],
        stdout=open(log, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    # Wait for startup + registration
    time.sleep(STARTUP_WAIT)

    # Resolve peer_id
    import re

    peer_id = None
    for _ in range(3):
        try:
            text = log.read_text()
            m = re.search(r'"peer_id":"(12D3KooW[^"]+)"', text)
            if m:
                peer_id = m.group(1)
                break
        except Exception:
            pass
        time.sleep(2)

    # Update roster
    save_roster(build_roster())

    if peer_id:
        return f"{name} online — peer_id: {peer_id[:24]}..."
    else:
        return f"{name} daemon started (pid={proc.pid}) — peer_id not yet resolved"


def pool_sleep(name: str) -> str:
    """Sleep an agency profile — stop its daemon."""
    if not name.startswith("agency-"):
        name = f"agency-{name}"

    profile_dir = PROFILES / name
    if not profile_dir.exists():
        return f"Error: profile {name} not found"

    # Kill daemon
    subprocess.run(
        ["pkill", "-9", "-f", f"profiles/{name}/.agency/bin/agentanycastd"],
        capture_output=True,
        timeout=3,
    )
    time.sleep(0.5)

    # Clean locks
    for f in (profile_dir / ".agency").rglob("*.lock"):
        f.unlink(missing_ok=True)
    sock = profile_dir / ".agency" / "daemon.sock"
    sock.unlink(missing_ok=True)

    # Update roster
    save_roster(build_roster())

    return f"{name} offline"


def pool_send(name: str, message: str) -> str:
    """Send work to an agent. Auto-wakes if offline."""
    if not name.startswith("agency-"):
        name = f"agency-{name}"

    agent = find_agent(name)
    if not agent:
        return f"Error: agent '{name}' not found in roster"

    # Auto-wake if offline
    if not agent["online"]:
        wake_result = pool_wake(name)
        if "Error" in wake_result:
            return wake_result
        # Re-read roster to get updated peer_id
        agent = find_agent(name)

    if not agent.get("peer_id"):
        return f"Error: {name} started but no peer_id resolved yet"

    # Return the peer_id so the caller can use a2a_send
    return f"Ready to send to {name} (peer_id: {agent['peer_id'][:24]}...). Use a2a_send with this peer_id."
