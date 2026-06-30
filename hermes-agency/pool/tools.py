"""Pool tools for Hermes Agency — simple protocol any agent can use.

Tools:
  pool_roster   — See all agents, who's online, what they do
  pool_wake     — Start an agent's daemon
  pool_sleep    — Stop an agent's daemon
  pool_send     — Send work to an agent (auto-wakes if offline)
"""

from __future__ import annotations

import fcntl
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .roster import (
    _atomic_write_json,
    _load_json,
    build_roster,
    ensure_profile_plugins,
    find_agent,
    load_roster,
    queue_offline_task,
    record_wake_attempt,
    roster_state_path,
    save_roster,
    update_agent_status,
)

PROFILES = Path.home() / ".hermes" / "profiles"
NODE_RUNNER = Path(__file__).with_name("agency_node_runner.py")
PLUGIN_PATH = Path(__file__).resolve().parents[1]
STARTUP_WAIT = 90


def _pid_alive(pid: int) -> bool:
    try:
        state = (Path("/proc") / str(pid) / "status").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        state = ""
    for line in state.splitlines():
        fields = line.split()
        if fields[:1] == ["State:"] and len(fields) > 1 and fields[1] == "Z":
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _runner_pid_file(profile_dir: Path) -> Path:
    return profile_dir / ".agency" / "runner.pid"


def _read_runner_pid(profile_dir: Path) -> int | None:
    try:
        raw = _runner_pid_file(profile_dir).read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except Exception:
        return None


def _read_proc_nul_file(path: Path) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    return [item.decode(errors="ignore") for item in raw.split(b"\0") if item]


def _proc_environ(pid: int, proc_root: Path = Path("/proc")) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in _read_proc_nul_file(proc_root / str(pid) / "environ"):
        key, sep, value = item.partition("=")
        if sep:
            env[key] = value
    return env


def _proc_cmdline(pid: int, proc_root: Path = Path("/proc")) -> list[str]:
    return _read_proc_nul_file(proc_root / str(pid) / "cmdline")


def _same_path(left: str | Path | None, right: Path) -> bool:
    if not left:
        return False
    try:
        return Path(left).expanduser().resolve() == right.expanduser().resolve()
    except OSError:
        return Path(left).expanduser() == right.expanduser()


def _pid_matches_profile_runner(
    pid: int,
    name: str,
    profile_dir: Path,
    *,
    proc_root: Path = Path("/proc"),
) -> bool:
    if pid == os.getpid():
        return False
    argv = _proc_cmdline(pid, proc_root=proc_root)
    if not any(Path(arg).name == "agency_node_runner.py" for arg in argv):
        return False

    env = _proc_environ(pid, proc_root=proc_root)
    if env.get("HERMES_PROFILE") == name:
        return True
    if _same_path(env.get("HERMES_HOME"), profile_dir):
        return True

    # Fallback for processes whose environ cannot be read: pool-managed runner
    # command lines include the profile-scoped plugin symlink path.
    profile_fragment = f"profiles/{name}/plugins/hermes-agency/pool/agency_node_runner.py"
    return any(profile_fragment in arg for arg in argv)


def _profile_runner_pids(
    name: str, profile_dir: Path, *, proc_root: Path = Path("/proc")
) -> list[int]:
    pids: list[int] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return pids
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if _pid_matches_profile_runner(pid, name, profile_dir, proc_root=proc_root):
            pids.append(pid)
    return sorted(set(pids))


def _terminate_pids(pids: list[int], *, grace_seconds: float = 1.5) -> None:
    for pid in sorted(set(pids)):
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.time() + grace_seconds
    while time.time() < deadline and any(_pid_alive(pid) for pid in pids):
        time.sleep(0.05)
    for pid in sorted(set(pids)):
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def stop_profile_runner_processes(name: str, profile_dir: Path | None = None) -> list[int]:
    """Stop all long-lived pool runners for a profile, including stale pidfiles.

    Gateway restarts run the active orchestrator node in-process. If an older
    pool-managed ``agency_node_runner.py`` survives with a stale pidfile, it can
    keep receiving A2A tasks with code that no longer matches the files on disk.
    Scan ``/proc`` by profile env/cmdline so cleanup does not depend on the
    pidfile being current.
    """

    if not name.startswith("agency-"):
        name = f"agency-{name}"
    resolved_profile_dir = profile_dir or (PROFILES / name)
    pids: list[int] = []
    runner_pid = _read_runner_pid(resolved_profile_dir)
    if runner_pid is not None:
        pids.append(runner_pid)
    pids.extend(_profile_runner_pids(name, resolved_profile_dir))
    pids = sorted({pid for pid in pids if pid != os.getpid()})
    if pids:
        _terminate_pids(pids)
    _runner_pid_file(resolved_profile_dir).unlink(missing_ok=True)
    return pids


def _profile_env(name: str, profile_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HERMES_PROFILE": name,
            "HERMES_HOME": str(profile_dir),
            "HERMES_AGENCY_PLUGIN_PATH": str(PLUGIN_PATH),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def _stop_profile_daemon_processes(name: str) -> None:
    subprocess.run(
        ["pkill", "-9", "-f", f"profiles/{name}/.agency/.*agentanycastd"],
        capture_output=True,
        timeout=3,
        check=False,
    )


def _proc_rss_kb(pid: int, proc_root: Path = Path("/proc")) -> int:
    try:
        for line in (
            (proc_root / str(pid) / "status")
            .read_text(encoding="utf-8", errors="ignore")
            .splitlines()
        ):
            if line.startswith("VmRSS:"):
                parts = line.split()
                return int(parts[1]) if len(parts) > 1 else 0
    except (OSError, ValueError):
        return 0
    return 0


def _agency_pool_process_pids(proc_root: Path = Path("/proc")) -> list[int]:
    pids: list[int] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return pids
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        argv = _proc_cmdline(pid, proc_root=proc_root)
        joined = "\0".join(argv)
        if "agency_node_runner.py" in joined or (
            "agentanycastd" in joined and "/profiles/agency-" in joined
        ):
            pids.append(pid)
    return sorted(set(pids))


def _pool_resource_snapshot() -> dict[str, Any]:
    pids = _agency_pool_process_pids()
    runner_pids = [
        pid for pid in pids if any("agency_node_runner.py" in arg for arg in _proc_cmdline(pid))
    ]
    total_rss_kb = sum(_proc_rss_kb(pid) for pid in pids)
    return {
        "pids": pids,
        "runner_pids": runner_pids,
        "runner_count": len(runner_pids),
        "total_rss_kb": total_rss_kb,
        "total_rss_mb": round(total_rss_kb / 1024, 1),
    }


def _pool_limits() -> tuple[int, int]:
    try:
        from ..config import get_config

        cfg = get_config()
        return cfg.pool.max_online_agents, cfg.pool.max_total_rss_mb
    except Exception:
        return 3, 2048


def _pool_wake_block_reason(name: str) -> str | None:
    max_online, max_rss_mb = _pool_limits()
    snapshot = _pool_resource_snapshot()
    if max_online == 0:
        return f"pool wake blocked for {name}: pool wakes are disabled by config"
    if max_online and snapshot["runner_count"] >= max_online:
        return (
            f"pool wake blocked for {name}: {snapshot['runner_count']} pool runner(s) "
            f"already online; limit={max_online}"
        )
    if max_rss_mb and snapshot["total_rss_mb"] >= max_rss_mb:
        return (
            f"pool wake blocked for {name}: pool RSS {snapshot['total_rss_mb']} MiB "
            f">= limit={max_rss_mb} MiB"
        )
    return None


def _wake_lock_path() -> Path:
    root = Path.home() / ".hermes" / ".agency"
    root.mkdir(parents=True, exist_ok=True)
    return root / "wake.lock"


class _WakeLock:
    def __enter__(self):
        self._fh = _wake_lock_path().open("w")
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        self._fh.close()
        return False


def _extract_own_peer_id(text: str) -> str | None:
    match = re.search(r'(?:"peer_id"\s*:\s*"|^PEER_ID=)(12D3KooW[0-9A-Za-z]+)', text, re.M)
    return match.group(1) if match else None


def _resolve_runner_peer_id(agency_dir: Path, runner_log: Path) -> str | None:
    """Resolve a just-started runner's own peer ID from all live startup logs.

    The Python runner may keep runner.log empty while the child daemon writes
    PEER_ID / agentanycastd-started lines to daemon.log. Treat both as startup
    sources so a healthy runner is not marked failed and queued as offline.
    """

    candidates = [runner_log, agency_dir / "logs" / "daemon.log"]
    for candidate in candidates:
        try:
            peer_id = _extract_own_peer_id(
                candidate.read_text(encoding="utf-8", errors="ignore")[-20000:]
            )
        except Exception:
            peer_id = None
        if peer_id:
            return peer_id
    return None


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
        status = "ONLINE" if p["online"] else "OFFLINE"
        skills_str = ", ".join(p.get("skills", [])[:5])
        if p.get("skill_count", 0) > 5:
            skills_str += f" +{p['skill_count'] - 5}"
        line = f"  {p['name']} — skills: {skills_str} [{status}]"
        if p.get("online") and p.get("peer_id"):
            line += f" peer_id: {p['peer_id']}"
        elif p.get("last_seen"):
            line += f" last_seen: {p['last_seen']}"
        lines.append(line)

    return "\n".join(lines)


def pool_wake(name: str) -> str:
    """Wake an agency profile with the long-lived node runner."""
    if not name.startswith("agency-"):
        name = f"agency-{name}"

    profile_dir = PROFILES / name
    if not profile_dir.exists():
        record_wake_attempt(name, success=False, error=f"profile {name} not found")
        return f"Error: profile {name} not found"

    setup = ensure_profile_plugins()
    if setup.get("profiles_errors"):
        return (
            "Error: Hermes Agency plugin setup failed for "
            f"{setup['profiles_errors']} profile(s); run `hermes agency setup-plugins`."
        )

    agency_dir = profile_dir / ".agency"
    agency_dir.mkdir(parents=True, exist_ok=True)
    with _WakeLock():
        runner_pid = _read_runner_pid(profile_dir)
        sock = agency_dir / "daemon.sock"
        if runner_pid and _pid_alive(runner_pid) and sock.exists():
            peer_id = _resolve_runner_peer_id(agency_dir, agency_dir / "logs" / "runner.log")
            if not peer_id:
                agent = find_agent(name)
                peer_id = agent.get("peer_id") if agent else None
            update_agent_status(name, online=True, peer_id=peer_id)
            save_roster(build_roster())
            suffix = f" — peer_id: {peer_id[:24]}..." if peer_id else ""
            return f"{name} is already online{suffix}"

        blocked = _pool_wake_block_reason(name)
        if blocked:
            record_wake_attempt(name, success=False, error=blocked)
            return f"Error: {blocked}"

        # Migrate older direct-daemon wakes to the long-lived runner. A bare daemon
        # can retain a card, but it has no Python task handler once the CLI exits.
        stop_profile_runner_processes(name, profile_dir)
        _stop_profile_daemon_processes(name)
        sock.unlink(missing_ok=True)
        for f in agency_dir.rglob("*.lock"):
            f.unlink(missing_ok=True)

        log = agency_dir / "logs" / "runner.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")

        with open(log, "a", encoding="utf-8") as log_fh:
            proc = subprocess.Popen(
                [sys.executable, str(NODE_RUNNER)],
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                cwd=str(profile_dir),
                env=_profile_env(name, profile_dir),
                text=True,
            )
        _runner_pid_file(profile_dir).write_text(str(proc.pid), encoding="utf-8")

    deadline = time.time() + STARTUP_WAIT
    peer_id = None
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            peer_id = _resolve_runner_peer_id(agency_dir, log)
        except Exception:
            peer_id = None
        if peer_id and sock.exists():
            break
        time.sleep(0.5)

    save_roster(build_roster())

    if peer_id and proc.poll() is None:
        record_wake_attempt(name, success=True, peer_id=peer_id)
        update_agent_status(name, online=True, peer_id=peer_id)
        return f"{name} online — peer_id: {peer_id[:24]}..."

    output = ""
    try:
        output = log.read_text(encoding="utf-8", errors="ignore")[-1000:]
    except Exception:
        pass
    daemon_output = ""
    try:
        daemon_output = (agency_dir / "logs" / "daemon.log").read_text(
            encoding="utf-8", errors="ignore"
        )[-1000:]
    except Exception:
        pass
    details = output or daemon_output or "no output"
    error = f"runner failed to start for {name}; pid={proc.pid}; output={details}"
    record_wake_attempt(name, success=False, error=error)
    return f"Error: {error}"


def pool_sleep(name: str) -> str:
    """Sleep an agency profile — stop its daemon."""
    if not name.startswith("agency-"):
        name = f"agency-{name}"

    profile_dir = PROFILES / name
    if not profile_dir.exists():
        return f"Error: profile {name} not found"

    # Stop long-lived runners, including stale processes no longer tracked by
    # runner.pid, then kill any profile-owned daemon.
    stop_profile_runner_processes(name, profile_dir)
    _stop_profile_daemon_processes(name)
    subprocess.run(
        ["pkill", "-9", "-f", f"profiles/{name}/.agency/bin/agentanycastd"],
        capture_output=True,
        timeout=3,
        check=False,
    )
    time.sleep(0.5)

    # Clean locks
    for f in (profile_dir / ".agency").rglob("*.lock"):
        f.unlink(missing_ok=True)
    sock = profile_dir / ".agency" / "daemon.sock"
    sock.unlink(missing_ok=True)

    # Update roster
    update_agent_status(name, online=False)
    save_roster(build_roster())

    return f"{name} offline"


def _recent_failed_wake(agent: dict[str, Any], cooldown_seconds: int = 60) -> bool:
    """Return True when a recent failed wake should be respected."""

    if not agent.get("last_wake_error") or not agent.get("last_wake_attempt_at"):
        return False
    try:
        return time.time() - float(agent["last_wake_attempt_at"]) < cooldown_seconds
    except (TypeError, ValueError):
        return False


def pool_send(name: str, message: str) -> str:
    """Send work to an agent. Auto-wakes if offline; queues if wake/send fails."""
    if not name.startswith("agency-"):
        name = f"agency-{name}"

    agent = find_agent(name)
    if not agent:
        return f"Error: agent '{name}' not found in roster"

    if not agent["online"] or not agent.get("peer_id"):
        if _recent_failed_wake(agent):
            queued = queue_offline_task(
                name,
                message,
                reason=f"recent wake failure: {agent.get('last_wake_error')}",
            )
            return (
                f"Queued task for {name}; recent wake failure is still cooling down. "
                f"queue_id={queued['task']['id']} queue_path={queued['queue_path']}"
            )
        wake_result = pool_wake(name)
        if "Error" in wake_result:
            queued = queue_offline_task(name, message, reason=wake_result)
            return (
                f"Queued task for {name}; wake failed: {wake_result}. "
                f"queue_id={queued['task']['id']} queue_path={queued['queue_path']}"
            )
        agent = find_agent(name) or agent

    if not agent.get("peer_id"):
        queued = queue_offline_task(name, message, reason="no peer_id resolved after wake")
        return (
            f"Queued task for {name}; daemon started but no peer_id resolved yet. "
            f"queue_id={queued['task']['id']} queue_path={queued['queue_path']}"
        )

    try:
        from ..node_manager import manager

        result = manager.send_task_sync(
            message=message, peer_id=str(agent["peer_id"]), wait_seconds=0
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        queued = queue_offline_task(name, message, reason=error)
        return (
            f"Queued task for {name}; send failed after wake: {error}. "
            f"queue_id={queued['task']['id']} queue_path={queued['queue_path']}"
        )

    return (
        f"Sent task to {name} (peer_id: {str(agent['peer_id'])[:24]}...). "
        f"task_id={result.get('task_id')} status={result.get('status')}"
    )


def _lifecycle_tools_enabled() -> bool:
    """Check if destructive lifecycle tools are enabled in config."""
    try:
        import yaml

        config_path = Path.home() / ".hermes" / "config.yaml"
        if config_path.exists():
            data = yaml.safe_load(config_path.read_text()) or {}
            agency = data.get("agency", {})
            if agency.get("lifecycle_tools_enabled") is True:
                return True
        # Also check profile-level config
        profile_config = Path.home() / ".hermes" / "agency" / "config.yaml"
        if profile_config.exists():
            data = yaml.safe_load(profile_config.read_text()) or {}
            if data.get("lifecycle_tools_enabled") is True:
                return True
    except Exception:
        pass
    return False


def pool_create_agent(
    name: str,
    department: str = "Operations",
    skills: list[str] | None = None,
    description: str = "",
) -> str:
    """Create a new agency agent profile at runtime.

    Requires agency.lifecycle_tools_enabled: true in config.
    """
    import json as _json
    import re

    if not _lifecycle_tools_enabled():
        return _json.dumps(
            {
                "ok": False,
                "error": "Lifecycle tools are disabled. Set agency.lifecycle_tools_enabled: true in config.yaml to enable.",
            }
        )

    name = str(name or "").strip()
    if not name:
        return _json.dumps({"ok": False, "error": "name is required"})
    if not name.startswith("agency-"):
        return _json.dumps({"ok": False, "error": "name must start with 'agency-'"})
    if not re.match(r"^[a-z0-9-]+$", name):
        return _json.dumps(
            {"ok": False, "error": "name must be lowercase alphanumeric with hyphens"}
        )
    if len(name) > 64:
        return _json.dumps({"ok": False, "error": "name must be 64 characters or fewer"})

    from ..departments import DEPARTMENT_BOARD_SLUGS

    valid_departments = set(DEPARTMENT_BOARD_SLUGS.keys())
    department = str(department or "").strip()
    if department not in valid_departments:
        return _json.dumps(
            {
                "ok": False,
                "error": f"department must be one of: {', '.join(sorted(valid_departments))}",
            }
        )

    profile_dir = PROFILES / name
    if profile_dir.exists():
        return _json.dumps({"ok": False, "error": f"profile {name} already exists"})

    skills = [str(s).strip().lower().replace("_", "-") for s in (skills or []) if str(s).strip()]

    try:
        from ..pool.manager import PoolManager

        manager = PoolManager.__new__(PoolManager)
        manager.lock = __import__("threading").Lock()
        manager.active = {}
        manager.persistent_agents = set()
        manager._ensure_profile(name)
    except Exception as exc:
        return _json.dumps({"ok": False, "error": f"failed to create profile: {exc}"})

    # Override SOUL.md with custom content
    soul_path = profile_dir / "SOUL.md"
    skill_lines = "\n".join(f"- {s}" for s in skills) if skills else "- general assistance"
    description = str(description or "").strip() or f"A {department} agent"
    soul_content = (
        f"# SOUL.md — {department} Agent\n\n"
        f"## Identity\n\n"
        f"You are `{name}`, a Hermes Agency agent in the {department} department.\n\n"
        f"## Skills\n\n"
        f"{skill_lines}\n\n"
        f"## Role Description\n\n"
        f"{description}\n\n"
        f"## Operating Principles\n\n"
        f"- Stay inside your specialty unless the task explicitly asks otherwise.\n"
        f"- Prefer concrete artifacts, verified results, and concise handoffs.\n"
        f"- Escalate to the right specialist by creating Kanban follow-up cards when needed.\n"
        f"- Do not deploy, publish, delete, or mutate production resources without explicit approval.\n"
    )
    try:
        soul_path.write_text(soul_content, encoding="utf-8")
    except Exception:
        pass

    # Record in roster state
    from .roster import set_agent_created_by

    set_agent_created_by(name, "lifecycle")

    return _json.dumps(
        {
            "ok": True,
            "name": name,
            "department": department,
            "skills": skills,
            "profile_dir": str(profile_dir),
        }
    )


def pool_disable_agent(name: str) -> str:
    """Mark an agent as disabled — won't be woken or receive tasks.

    Requires agency.lifecycle_tools_enabled: true in config.
    """
    import json as _json

    if not _lifecycle_tools_enabled():
        return _json.dumps(
            {
                "ok": False,
                "error": "Lifecycle tools are disabled. Set agency.lifecycle_tools_enabled: true in config.yaml to enable.",
            }
        )

    name = str(name or "").strip()
    if not name:
        return _json.dumps({"ok": False, "error": "name is required"})

    profile_dir = PROFILES / name
    from .roster import (
        _persisted_state_by_name,
        _registry_agents,
        is_agent_disabled,
        set_agent_disabled,
    )

    persisted = _persisted_state_by_name()
    in_registry = any(a.get("name") == name for a in _registry_agents())
    if not profile_dir.exists() and not in_registry and name not in persisted:
        return _json.dumps({"ok": False, "error": f"agent {name} not found"})

    if is_agent_disabled(name):
        return _json.dumps({"ok": True, "name": name, "action": "already_disabled"})

    # Sleep if online
    try:
        pool_sleep(name)
    except Exception:
        pass

    set_agent_disabled(name, True, "manual")
    return _json.dumps({"ok": True, "name": name, "action": "disabled"})


def pool_enable_agent(name: str) -> str:
    """Re-enable a disabled agent.

    Requires agency.lifecycle_tools_enabled: true in config.
    """
    import json as _json

    if not _lifecycle_tools_enabled():
        return _json.dumps(
            {
                "ok": False,
                "error": "Lifecycle tools are disabled. Set agency.lifecycle_tools_enabled: true in config.yaml to enable.",
            }
        )

    name = str(name or "").strip()
    if not name:
        return _json.dumps({"ok": False, "error": "name is required"})

    from .roster import is_agent_disabled, set_agent_disabled

    if not is_agent_disabled(name):
        return _json.dumps({"ok": False, "error": f"agent {name} is not disabled"})

    set_agent_disabled(name, False)
    return _json.dumps({"ok": True, "name": name, "action": "enabled"})


def pool_prune_agent(name: str, force: bool = False) -> str:
    """Remove an agent entirely — delete profile dir and roster state.

    Requires agency.lifecycle_tools_enabled: true in config.
    Default staff agents require force=True.
    """
    import json as _json
    import shutil

    if not _lifecycle_tools_enabled():
        return _json.dumps(
            {
                "ok": False,
                "error": "Lifecycle tools are disabled. Set agency.lifecycle_tools_enabled: true in config.yaml to enable.",
            }
        )

    name = str(name or "").strip()
    if not name:
        return _json.dumps({"ok": False, "error": "name is required"})

    if name == "agency-orchestrator":
        return _json.dumps({"ok": False, "error": "cannot prune the orchestrator agent"})

    profile_dir = PROFILES / name
    from .roster import _persisted_state_by_name, _registry_agents

    persisted = _persisted_state_by_name()
    in_registry = any(a.get("name") == name for a in _registry_agents())
    if not profile_dir.exists() and not in_registry and name not in persisted:
        return _json.dumps({"ok": False, "error": f"agent {name} not found"})

    if in_registry and not force:
        return _json.dumps(
            {
                "ok": False,
                "error": f"{name} is a default staff agent. Pass force=True to prune (it can be reinstalled via pool_reset_agents).",
                "reinstallable": True,
            }
        )

    # Sleep if online
    try:
        pool_sleep(name)
    except Exception:
        pass

    # Delete profile dir
    if profile_dir.exists():
        try:
            shutil.rmtree(profile_dir)
        except Exception as exc:
            return _json.dumps({"ok": False, "error": f"failed to delete profile dir: {exc}"})

    # Remove from roster state
    data = _load_json(roster_state_path())
    profiles = data.get("profiles")
    if isinstance(profiles, list):
        data["profiles"] = [
            p for p in profiles if not (isinstance(p, dict) and p.get("name") == name)
        ]
        _atomic_write_json(roster_state_path(), data)

    return _json.dumps(
        {
            "ok": True,
            "name": name,
            "action": "pruned",
            "reinstallable": in_registry,
        }
    )


def pool_reset_agents() -> str:
    """Reinstall all default_staff profiles. Safety net for over-pruning.

    Requires agency.lifecycle_tools_enabled: true in config.
    """
    import json as _json

    if not _lifecycle_tools_enabled():
        return _json.dumps(
            {
                "ok": False,
                "error": "Lifecycle tools are disabled. Set agency.lifecycle_tools_enabled: true in config.yaml to enable.",
            }
        )

    try:
        from ..default_staff import install_default_staff

        result = install_default_staff(force=True)
        return _json.dumps({"ok": True, **result})
    except Exception as exc:
        return _json.dumps({"ok": False, "error": str(exc)})
