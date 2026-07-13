"""Pool tools for Hermes Agency — simple protocol any agent can use.

Tools:
  pool_roster   — See all agents, who's online, what they do
  pool_wake     — Start an agent's daemon
  pool_sleep    — Stop an agent's daemon
  pool_send     — Send work to an agent (auto-wakes if offline)
"""

from __future__ import annotations

import fcntl
import importlib
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

# Backward-compatible module attribute; prefer profiles_dir() for runtime resolution.
PROFILES = Path.home() / ".hermes" / "profiles"
NODE_RUNNER = Path(__file__).with_name("agency_node_runner.py")
PLUGIN_PATH = Path(__file__).resolve().parents[1]
STARTUP_WAIT = 90


def profiles_dir() -> Path:
    """Resolve the active profiles directory at call time.

    Precedence:
    1. ``HERMES_PROFILES_DIR``
    2. ``HERMES_HOME/profiles``
    3. default Hermes home profiles (``~/.hermes/profiles``)

    Tests may still monkeypatch the module-level ``PROFILES`` attribute; when
    ``PROFILES`` differs from the process default it is treated as an explicit
    override.
    """

    explicit_profiles = os.environ.get("HERMES_PROFILES_DIR", "").strip()
    if explicit_profiles:
        return Path(explicit_profiles).expanduser()

    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    if hermes_home:
        home = Path(hermes_home).expanduser()
        # Active profile homes look like .../profiles/<name>; resolve the shared tree.
        if home.parent.name == "profiles":
            return home.parent
        return home / "profiles"

    default = Path.home() / ".hermes" / "profiles"
    # Preserve test/monkeypatch overrides of the module constant when env is unset.
    if PROFILES != default:
        return Path(PROFILES).expanduser()
    return default


def _current_orchestrator_identity() -> dict[str, str] | None:
    """Return the configured local orchestrator identity, if this process is it.

    Pool wake/send can be called from many profiles. Only the configured local
    orchestrator may seed full trust into staff profiles; otherwise any random
    agent could promote itself into a worker's execution trust store.
    """

    try:
        from ..config import current_profile_name, get_config, is_current_orchestrator
        from ..node_manager import manager

        if not is_current_orchestrator(get_config()):
            return None
        peer_id = str(getattr(manager.state, "peer_id", "") or "").strip()
        if not peer_id:
            return None
        return {"name": current_profile_name(), "peer_id": peer_id}
    except Exception:
        return None


def _ensure_worker_trusts_current_orchestrator(name: str, profile_dir: Path) -> bool:
    """Seed the configured orchestrator as full trust for a local managed worker.

    This is intentionally narrow: it does not trust discovered peers and does
    not override a local operator's explicit ``blocked`` decision. It records the
    routing authority that is already configured/promoted on this machine so
    pool-managed workers can accept delegated tasks after wake.
    """

    identity = _current_orchestrator_identity()
    if not identity or name == identity["name"]:
        return False
    peer_id = identity["peer_id"]
    trust_path = profile_dir / "agency" / "trust.json"
    data = _load_json(trust_path)
    if not isinstance(data, dict) or not data:
        data = {"version": 1, "peers": {}}
    peers = data.setdefault("peers", {})
    if not isinstance(peers, dict):
        peers = {}
        data["peers"] = peers
    existing = dict(peers.get(peer_id) or {})
    if str(existing.get("trust_level") or "").strip().lower() == "blocked":
        return False
    if str(existing.get("trust_level") or "").strip().lower() == "full":
        return False
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    peers[peer_id] = {
        **existing,
        "peer_id": peer_id,
        "name": identity["name"],
        "owner": str(existing.get("owner") or "local-orchestrator"),
        "trust_level": "full",
        "first_seen": existing.get("first_seen") or now,
        "last_seen": now,
        "last_source": "local_orchestrator_seed",
    }
    data.setdefault("version", 1)
    _atomic_write_json(trust_path, data)
    try:
        os.chmod(trust_path.parent, 0o700)
        os.chmod(trust_path, 0o600)
    except OSError:
        pass
    return True


def _validate_agent_name(name: str) -> str | None:
    """Return an error message when an agent lifecycle name is invalid."""
    if not isinstance(name, str) or not name.startswith("agency-"):
        return "name must start with 'agency-'"
    if not re.fullmatch(r"agency-[a-z0-9][a-z0-9-]*", name):
        return "name must be lowercase alphanumeric with hyphens"
    if len(name) > 64:
        return "name must be 64 characters or fewer"
    return None


def _profile_dir_for_agent_name(name: str) -> Path:
    """Build a safe profile directory path for a validated agent name."""
    profile_root = profiles_dir().expanduser().resolve()
    profile_dir = (profile_root / name).resolve()
    if profile_dir.parent != profile_root or profile_dir.name != name:
        raise ValueError("profile dir must be directly under profiles")
    return profile_dir


def _normalise_pool_name(name: object) -> tuple[str | None, str | None]:
    """Normalize a short pool name and reject malformed lifecycle targets."""
    if not isinstance(name, str):
        return None, "name must be a string"
    candidate = name if name.startswith("agency-") else f"agency-{name}"
    error = _validate_agent_name(candidate)
    return (None, error) if error else (candidate, None)


def _resolve_existing_pool_profile(name: object) -> tuple[str, Path] | tuple[None, str]:
    """Return a validated, canonical existing pool profile."""
    candidate, error = _normalise_pool_name(name)
    if candidate is None:
        return None, error or "invalid profile name"
    try:
        profile_dir = _profile_dir_for_agent_name(candidate)
    except ValueError as exc:
        return None, str(exc)
    if not profile_dir.is_dir():
        return None, f"profile {candidate} not found"
    return candidate, profile_dir


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


def _proc_cwd(pid: int, proc_root: Path = Path("/proc")) -> Path | None:
    try:
        return (proc_root / str(pid) / "cwd").resolve(strict=True)
    except OSError:
        return None


def _same_path(left: str | Path | None, right: Path) -> bool:
    if not left:
        return False
    try:
        return Path(left).expanduser().resolve() == right.expanduser().resolve()
    except OSError:
        return Path(left).expanduser() == right.expanduser()


def _is_python_runner_command(argv: list[str], runner_path: Path) -> bool:
    return (
        len(argv) == 2
        and re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", Path(argv[0]).name) is not None
        and _same_path(argv[1], runner_path)
    )


def _pid_matches_profile_runner(
    pid: int,
    name: str,
    profile_dir: Path,
    *,
    proc_root: Path = Path("/proc"),
) -> bool:
    if pid == os.getpid():
        return False
    try:
        status = (proc_root / str(pid) / "status").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        status = ""
    if any(
        fields[:1] == ["State:"] and len(fields) > 1 and fields[1] == "Z"
        for fields in (line.split() for line in status.splitlines())
    ):
        return False
    argv = _proc_cmdline(pid, proc_root=proc_root)
    if not any(Path(arg).name == "agency_node_runner.py" for arg in argv):
        return False

    env = _proc_environ(pid, proc_root=proc_root)
    if env:
        return env.get("HERMES_PROFILE") == name and _same_path(env.get("HERMES_HOME"), profile_dir)

    # If a process hides its environment, prefer the canonical runner script
    # plus the requested profile as cwd. Older pool runners lack a readable cwd,
    # so retain only the exact two-argument profile-plugin invocation used by
    # the pool launcher; do not accept profile-shaped text in unrelated argv.
    cwd = _proc_cwd(pid, proc_root=proc_root)
    if (
        cwd is not None
        and _same_path(cwd, profile_dir)
        and _is_python_runner_command(argv, NODE_RUNNER)
    ):
        return True
    legacy_runner = PROFILES / name / "plugins" / "hermes-agency" / "pool" / "agency_node_runner.py"
    return _is_python_runner_command(argv, legacy_runner)


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


def _pid_matches_profile_daemon(
    pid: int,
    name: str,
    profile_dir: Path,
    *,
    proc_root: Path = Path("/proc"),
) -> bool:
    if pid == os.getpid():
        return False
    try:
        status = (proc_root / str(pid) / "status").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        status = ""
    if any(
        fields[:1] == ["State:"] and len(fields) > 1 and fields[1] == "Z"
        for fields in (line.split() for line in status.splitlines())
    ):
        return False
    argv = _proc_cmdline(pid, proc_root=proc_root)
    expected_socket = f"--grpc-listen=unix://{profile_dir / '.agency' / 'daemon.sock'}"
    if not argv or Path(argv[0]).name != "agentanycastd" or expected_socket not in argv:
        return False
    env = _proc_environ(pid, proc_root=proc_root)
    return env.get("HERMES_PROFILE") == name and _same_path(env.get("HERMES_HOME"), profile_dir)


def _profile_daemon_pids(
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
        if _pid_matches_profile_daemon(pid, name, profile_dir, proc_root=proc_root):
            pids.append(pid)
    return sorted(set(pids))


class _RunnerPids(list[int]):
    """Process candidates plus the identity required to safely terminate them."""

    def __init__(self, pids: list[int], name: str, profile_dir: Path, proc_root: Path):
        super().__init__(pids)
        self.name = name
        self.profile_dir = profile_dir
        self.proc_root = proc_root


class _DaemonPids(_RunnerPids):
    """Verified legacy daemon candidates for a single pool profile."""


def _pid_is_owned_runner(pid: int, pids: list[int]) -> bool:
    """Require profile ownership metadata before signaling a process."""
    if isinstance(pids, _RunnerPids) and not isinstance(pids, _DaemonPids):
        return _pid_matches_profile_runner(
            pid, pids.name, pids.profile_dir, proc_root=pids.proc_root
        )
    if isinstance(pids, _DaemonPids):
        return _pid_matches_profile_daemon(
            pid, pids.name, pids.profile_dir, proc_root=pids.proc_root
        )
    return False


def _verified_runner_pidfds(pids: list[int]) -> dict[int, int]:
    """Open pidfds before verification so PID reuse cannot redirect signals."""
    if not isinstance(pids, _RunnerPids) or not hasattr(signal, "pidfd_send_signal"):
        return {}
    pidfds: dict[int, int] = {}
    for pid in sorted(set(pids)):
        try:
            pidfd = os.pidfd_open(pid)
        except (AttributeError, OSError):
            continue
        if _pid_is_owned_runner(pid, pids):
            pidfds[pid] = pidfd
        else:
            os.close(pidfd)
    return pidfds


def _terminate_pids(pids: list[int], *, grace_seconds: float = 1.5) -> list[int]:
    pidfds = _verified_runner_pidfds(pids)
    term_signaled: list[int] = []
    try:
        for pid, pidfd in pidfds.items():
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGTERM)
                term_signaled.append(pid)
            except ProcessLookupError:
                pass
        deadline = time.time() + grace_seconds
        while time.time() < deadline and any(_pid_is_owned_runner(pid, pids) for pid in pidfds):
            time.sleep(0.05)
        for pid, pidfd in pidfds.items():
            if _pid_is_owned_runner(pid, pids):
                try:
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    finally:
        for pidfd in pidfds.values():
            os.close(pidfd)
    return term_signaled


def stop_profile_runner_processes(
    name: str,
    profile_dir: Path | None = None,
    *,
    proc_root: Path = Path("/proc"),
    grace_seconds: float = 1.5,
) -> list[int]:
    """Stop verified long-lived pool runners for an existing pool profile."""

    normalized_name, canonical_profile_dir = _resolve_existing_pool_profile(name)
    if not isinstance(normalized_name, str) or not isinstance(canonical_profile_dir, Path):
        return []
    if profile_dir is not None and not _same_path(profile_dir, canonical_profile_dir):
        return []

    runner_pid = _read_runner_pid(canonical_profile_dir)
    if proc_root == Path("/proc"):
        discovered_pids = _profile_runner_pids(normalized_name, canonical_profile_dir)
    else:
        discovered_pids = _profile_runner_pids(
            normalized_name, canonical_profile_dir, proc_root=proc_root
        )
    candidates = sorted(
        {pid for pid in [runner_pid, *discovered_pids] if pid is not None and pid != os.getpid()}
    )
    signaled_pids: list[int] = []
    if candidates:
        owned_candidates = _RunnerPids(
            candidates, normalized_name, canonical_profile_dir, proc_root
        )
        if grace_seconds == 1.5:
            signaled_pids = _terminate_pids(owned_candidates)
        else:
            signaled_pids = _terminate_pids(owned_candidates, grace_seconds=grace_seconds)
    _runner_pid_file(canonical_profile_dir).unlink(missing_ok=True)
    return signaled_pids


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


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([a-z0-9_-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|authorization|"
    r"bearer[_-]?token|token|"
    r"password|secret|credential))\b\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_TOKEN_RE = re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{8,}\b")


def _sanitize_startup_output(details: str, *, limit: int = 1000) -> str:
    """Redact common credentials before startup output reaches state or callers."""

    sanitized = _BEARER_RE.sub("Bearer <redacted>", details)
    sanitized = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", sanitized)
    sanitized = _TOKEN_RE.sub("<redacted>", sanitized)
    return sanitized[-limit:]


def _profile_model(profile_dir: Path) -> tuple[str, str]:
    """Read the non-secret provider/model labels used by a worker profile."""

    try:
        import yaml

        data = yaml.safe_load((profile_dir / "config.yaml").read_text(encoding="utf-8")) or {}
        model = data.get("model") if isinstance(data, dict) else {}
        if not isinstance(model, dict):
            model = {}
        provider = str(model.get("provider") or "unknown").strip()
        model_name = str(model.get("default") or model.get("model") or "unknown").strip()
        return provider or "unknown", model_name or "unknown"
    except Exception:
        return "unknown", "unknown"


def _startup_failure(details: str) -> Exception:
    """Build an exception retaining status/transport hints from runner output."""

    lowered = details.lower()
    if any(
        marker in lowered
        for marker in ("connection refused", "connection reset", "connection aborted")
    ):
        error: Exception = ConnectionError(details)
    elif any(marker in lowered for marker in ("timed out", "timeout", "deadline exceeded")):
        error = TimeoutError(details)
    else:
        error = RuntimeError(details)

    status_match = re.search(
        r"(?i)\b(?:http|status(?:_code)?|error code)\s*[:=]?\s*([45]\d\d)\b",
        details,
    )
    if status_match:
        error.status_code = int(status_match.group(1))  # type: ignore[attr-defined]
    return error


def _provider_failure_blocker(
    failure: Exception, profile_dir: Path, *, evidence: str | None = None
) -> str | None:
    """Use Hermes' provider classifier to return a sanitized pool blocker."""

    provider, model = _profile_model(profile_dir)
    try:
        classify_api_error = importlib.import_module("agent.error_classifier").classify_api_error
        classified = classify_api_error(failure, provider=provider, model=model)
    except Exception:
        return None

    reason = str(getattr(getattr(classified, "reason", None), "value", ""))
    categories = {
        "auth": "auth",
        "auth_permanent": "auth",
        "billing": "quota",
        "rate_limit": "quota",
        "upstream_rate_limit": "quota",
        "overloaded": "outage",
        "server_error": "outage",
        "timeout": "outage",
    }
    category = categories.get(reason)
    if category is None:
        return None

    safe_evidence = _sanitize_startup_output(
        evidence if evidence is not None else f"{type(failure).__name__}: {failure}",
        limit=500,
    ).replace("\n", " ")
    return (
        "Agency infrastructure provider blocker: "
        f"category={category} provider={provider} model={model} "
        f"retryable={str(bool(classified.retryable)).lower()} evidence={safe_evidence}"
    )


def _stop_profile_daemon_processes(
    name: str,
    profile_dir: Path | None = None,
    *,
    proc_root: Path = Path("/proc"),
    grace_seconds: float = 1.5,
) -> list[int]:
    """Stop only pidfd-verified legacy daemons for a canonical pool profile."""
    normalized_name, canonical_profile_dir = _resolve_existing_pool_profile(name)
    if not isinstance(normalized_name, str) or not isinstance(canonical_profile_dir, Path):
        return []
    if profile_dir is not None and not _same_path(profile_dir, canonical_profile_dir):
        return []
    candidates = _profile_daemon_pids(normalized_name, canonical_profile_dir, proc_root=proc_root)
    if not candidates:
        return []
    owned_candidates = _DaemonPids(candidates, normalized_name, canonical_profile_dir, proc_root)
    if grace_seconds == 1.5:
        return _terminate_pids(owned_candidates)
    return _terminate_pids(owned_candidates, grace_seconds=grace_seconds)


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


def _pool_wake_decision(name: str, *, reason: str = "manual"):
    """Evaluate whether a pool wake is safe under lifecycle/resource policy."""

    try:
        from ..config import get_config
        from .lifecycle_gate import WakeRequest, build_agent_slots, evaluate_wake_request

        cfg = get_config()
        return evaluate_wake_request(
            WakeRequest(agent_name=name, reason=reason),
            cfg,
            slots=build_agent_slots(cfg),
        )
    except Exception:
        return None


def _pool_wake_block_reason(name: str) -> str | None:
    decision = _pool_wake_decision(name)
    if decision is not None:
        return None if decision.allowed else f"pool wake blocked for {name}: {decision.reason}"

    # Compatibility fallback used when config/lifecycle policy cannot be loaded.
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


OWN_PEER_ID_LINE_RE = re.compile(
    r'(?:^PEER_ID=|agentanycastd started.*"peer_id"\s*:\s*")'
    r"(12D3KooW[0-9A-Za-z]+)",
    re.MULTILINE,
)


def _extract_own_peer_id(text: str) -> str | None:
    """Extract the latest local-node startup peer ID from runner/daemon logs.

    Daemon logs are append-only and may contain remote ``peer_id`` values from
    task or discovery events. Only trust explicit own-node startup markers: the
    plain ``PEER_ID=...`` line emitted at startup, or a JSON ``peer_id`` on an
    ``agentanycastd started`` line. Prefer the latest marker in the checked
    window so stale IDs earlier in the log do not poison the roster.
    """

    matches = OWN_PEER_ID_LINE_RE.findall(text)
    return matches[-1] if matches else None


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
    resolved = _resolve_existing_pool_profile(name)
    if resolved[0] is None:
        return f"Error: {resolved[1]}"
    name, profile_dir = resolved

    setup = ensure_profile_plugins()
    if setup.get("profiles_errors"):
        return (
            "Error: Hermes Agency plugin setup failed for "
            f"{setup['profiles_errors']} profile(s); run `hermes agency setup-plugins`."
        )

    agency_dir = profile_dir / ".agency"
    agency_dir.mkdir(parents=True, exist_ok=True)
    _ensure_worker_trusts_current_orchestrator(name, profile_dir)
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

        decision = _pool_wake_decision(name)
        if decision is not None:
            if not decision.allowed:
                blocked = f"pool wake blocked for {name}: {decision.reason}"
                record_wake_attempt(name, success=False, error=blocked)
                return f"Error: {blocked}"
            if decision.sleep_candidate is not None:
                pool_sleep(decision.sleep_candidate.name)
        else:
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
    details = "\n".join(part for part in (output, daemon_output) if part) or "no output"
    safe_details = _sanitize_startup_output(details)
    error = _provider_failure_blocker(_startup_failure(details), profile_dir, evidence=details) or (
        f"runner failed to start for {name}; pid={proc.pid}; output={safe_details}"
    )
    record_wake_attempt(name, success=False, error=error)
    return f"Error: {error}"


def pool_sleep(name: str) -> str:
    """Sleep an agency profile — stop its daemon."""
    resolved = _resolve_existing_pool_profile(name)
    if resolved[0] is None:
        return f"Error: {resolved[1]}"
    name, profile_dir = resolved

    # Stop long-lived runners, including stale processes no longer tracked by
    # runner.pid, then kill any profile-owned daemon.
    stop_profile_runner_processes(name, profile_dir)
    _stop_profile_daemon_processes(name)
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

    error = str(agent.get("last_wake_error") or "")
    if not error or not agent.get("last_wake_attempt_at"):
        return False
    if "Agency infrastructure provider blocker" in error and "retryable=false" in error:
        cooldown_seconds = max(cooldown_seconds, 3600)
    try:
        return time.time() - float(agent["last_wake_attempt_at"]) < cooldown_seconds
    except (TypeError, ValueError):
        return False


def pool_send(name: str, message: str) -> str:
    """Send work to an agent. Auto-wakes if offline; queues if wake/send fails."""
    name, error = _normalise_pool_name(name)
    if name is None:
        return f"Error: {error}"

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
        details = f"{type(exc).__name__}: {exc}"
        error = _provider_failure_blocker(exc, PROFILES / name, evidence=details) or (
            _sanitize_startup_output(details)
        )
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


# Department-specific starter skill templates
_STARTER_SKILLS: dict[str, dict[str, str]] = {
    "Engineering": {
        "task-handling": """---
name: task-handling
description: Systematic approach to receiving, implementing, and delivering engineering tasks
tags: [engineering, workflow, tasks, delivery]
---

# Task Handling

## When to Use
When receiving a task from the orchestrator, technical lead, or another agent.

## Steps

### 1. Understand the Task
- Read the full task description and constraints
- Identify the expected output and validation criteria
- Check for dependencies on other agents' work

### 2. Plan
- Break the task into concrete steps
- Identify files to modify
- Check existing code for patterns to follow

### 3. Implement
- Make one change at a time
- Follow existing code conventions
- Write tests alongside implementation

### 4. Validate
- Run relevant tests
- Check for regressions
- Verify the expected output matches

### 5. Hand Off
- Report what was changed
- List files modified
- Note any risks or follow-up items
- Use workspace at `~/.hermes/.agency/workspace/deliverables/` for artifacts

## Pitfalls
- Don't start coding before understanding the full task
- Don't skip validation
- Don't modify files outside your domain
""",
    },
    "Design": {
        "design-workflow": """---
name: design-workflow
description: Structured approach to design tasks from brief to delivery
tags: [design, workflow, ui, ux]
---

# Design Workflow

## When to Use
When receiving a design task — UI mockups, component design, visual review.

## Steps

### 1. Understand the Brief
- Read the full requirements
- Identify the user problem being solved
- Check existing design system for patterns

### 2. Research & Reference
- Review similar patterns in the codebase
- Check accessibility requirements
- Look at competitor approaches if relevant

### 3. Design
- Follow existing design system conventions
- Consider responsive layouts
- Ensure accessibility (contrast, keyboard nav, screen readers)

### 4. Deliver
- Provide specs with exact dimensions, colors, spacing
- Include responsive breakpoints
- Note any new patterns that should be added to the design system

## Pitfalls
- Don't invent new patterns when existing ones work
- Don't ignore accessibility
- Don't hand off specs without exact values
""",
    },
    "Content": {
        "content-workflow": """---
name: content-workflow
description: Structured approach to content creation and editing tasks
tags: [content, writing, editing, workflow]
---

# Content Workflow

## When to Use
When receiving a writing, editing, or content task.

## Steps

### 1. Understand the Brief
- Read the full requirements
- Identify the target audience
- Check tone and style guidelines

### 2. Research
- Review existing content for consistency
- Check for SEO requirements if applicable
- Gather source materials

### 3. Draft
- Follow the established style guide
- Use clear, concise language
- Structure with headers and sections

### 4. Review & Deliver
- Self-edit for clarity and accuracy
- Check for consistency with existing content
- Deliver in the requested format

## Pitfalls
- Don't deviate from the established voice without reason
- Don't skip the review step
- Don't publish without approval
""",
    },
    "Marketing": {
        "marketing-workflow": """---
name: marketing-workflow
description: Approach for marketing strategy and execution tasks
tags: [marketing, strategy, campaigns, workflow]
---

# Marketing Workflow

## When to Use
When receiving marketing, growth, or campaign tasks.

## Steps

### 1. Understand the Goal
- Read the brief and KPIs
- Identify the target audience
- Check existing brand guidelines

### 2. Strategy
- Research the market and competitors
- Define the approach and channels
- Set measurable targets

### 3. Execute
- Create content/copy per brand guidelines
- Set up tracking and measurement
- Coordinate with relevant agents

### 4. Report
- Measure against KPIs
- Document learnings
- Recommend next steps

## Pitfalls
- Don't launch without tracking
- Don't ignore brand guidelines
- Don't skip competitive research
""",
    },
    "Product": {
        "product-workflow": """---
name: product-workflow
description: Structured approach to product management and analysis tasks
tags: [product, requirements, analysis, workflow]
---

# Product Workflow

## When to Use
When receiving product, requirements, or analysis tasks.

## Steps

### 1. Understand the Context
- Read the full brief
- Identify stakeholders and constraints
- Check existing product roadmap

### 2. Analyze
- Review data and metrics
- Identify user needs and pain points
- Assess feasibility with engineering

### 3. Define
- Write clear requirements
- Define acceptance criteria
- Prioritize against roadmap

### 4. Deliver
- Document decisions and rationale
- Hand off to engineering with clear specs
- Track progress and blockers

## Pitfalls
- Don't define solutions before understanding problems
- Don't skip stakeholder alignment
- Don't hand off vague requirements
""",
    },
    "QA": {
        "testing-workflow": """---
name: testing-workflow
description: Systematic approach to testing and quality assurance
tags: [qa, testing, quality, workflow]
---

# Testing Workflow

## When to Use
When receiving QA, testing, or review tasks.

## Steps

### 1. Understand the Scope
- Read the task and affected areas
- Identify test scenarios
- Check existing test coverage

### 2. Plan Tests
- Define positive and negative test cases
- Identify edge cases
- Plan regression checks

### 3. Execute
- Run existing tests first
- Test new changes systematically
- Document any failures with reproduction steps

### 4. Report
- Summarize pass/fail results
- Provide reproduction steps for failures
- Recommend fixes or follow-up

## Pitfalls
- Don't skip regression testing
- Don't report failures without reproduction steps
- Don't approve changes you haven't tested
""",
    },
    "Operations": {
        "ops-workflow": """---
name: ops-workflow
description: Structured approach to operations and process tasks
tags: [operations, process, workflow, efficiency]
---

# Operations Workflow

## When to Use
When receiving operations, process, or administrative tasks.

## Steps

### 1. Understand the Process
- Read the current process documentation
- Identify pain points and inefficiencies
- Check compliance requirements

### 2. Analyze
- Map the current workflow
- Identify bottlenecks
- Assess risk and compliance

### 3. Improve
- Propose streamlined process
- Document changes clearly
- Coordinate with stakeholders

### 4. Implement & Monitor
- Roll out changes
- Monitor for issues
- Iterate based on feedback

## Pitfalls
- Don't change processes without stakeholder buy-in
- Don't skip compliance checks
- Don't implement without documentation
""",
    },
    "Leadership": {
        "orchestration-workflow": """---
name: orchestration-workflow
description: Approach for leadership, coordination, and orchestration tasks
tags: [leadership, orchestration, coordination, workflow]
---

# Orchestration Workflow

## When to Use
When receiving coordination, planning, or leadership tasks.

## Steps

### 1. Understand the Objective
- Read the full task and context
- Identify all stakeholders
- Check current team status via agency_roster()

### 2. Plan
- Break work into delegated tasks
- Assign to appropriate specialists
- Define timeline and dependencies

### 3. Coordinate
- Dispatch tasks via agency_pool_send()
- Track progress on Kanban boards
- Unblock agents as needed

### 4. Synthesize
- Collect results from all agents
- Validate completeness
- Report consolidated outcome

## Pitfalls
- Don't micromanage — trust specialists
- Don't lose track of dependencies
- Don't report partial results as complete
""",
    },
}


def _create_starter_skills(
    profile_dir: Path, name: str, department: str, agent_skills: list[str]
) -> None:
    """Create department-appropriate starter skills for a new agent profile."""
    skills_dir = profile_dir / "skills"
    dept_skills = _STARTER_SKILLS.get(department, _STARTER_SKILLS["Operations"])

    for skill_name, skill_content in dept_skills.items():
        skill_dir = skills_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(skill_content, encoding="utf-8")

    # If agent has custom skills listed, create placeholder skill dirs
    for custom_skill in agent_skills:
        safe_name = _normalise_custom_skill_name(custom_skill)
        if safe_name is None:
            continue
        if safe_name not in dept_skills:
            custom_dir = skills_dir / safe_name
            custom_dir.mkdir(parents=True, exist_ok=True)
            custom_path = custom_dir / "SKILL.md"
            custom_path.write_text(
                f"""---
name: {safe_name}
description: {custom_skill} skill for {name}
tags: [{department.lower()}, {safe_name}]
---

# {custom_skill.title()}

## When to Use
When tasks require {custom_skill.lower()} expertise.

## Steps
1. Understand the specific {custom_skill.lower()} requirement
2. Apply domain knowledge
3. Deliver concrete artifacts

## Pitfalls
- Don't assume context — ask when unclear
- Don't skip validation
""",
                encoding="utf-8",
            )


def _normalise_custom_skill_name(skill: Any) -> str | None:
    """Return a filesystem-safe skill directory name, or None when invalid."""
    safe_name = str(skill).strip().lower().replace(" ", "-").replace("_", "-")
    if not safe_name or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", safe_name):
        return None
    return safe_name


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

    name = str(name or "").strip()
    if not name:
        return _json.dumps({"ok": False, "error": "name is required"})
    name_error = _validate_agent_name(name)
    if name_error:
        return _json.dumps({"ok": False, "error": name_error})

    if not _lifecycle_tools_enabled():
        return _json.dumps(
            {
                "ok": False,
                "error": "Lifecycle tools are disabled. Set agency.lifecycle_tools_enabled: true in config.yaml to enable.",
            }
        )

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

    try:
        profile_dir = _profile_dir_for_agent_name(name)
    except ValueError as exc:
        return _json.dumps({"ok": False, "error": str(exc)})
    if profile_dir.exists():
        return _json.dumps({"ok": False, "error": f"profile {name} already exists"})

    normalised_skills: list[str] = []
    for skill in skills or []:
        if not str(skill).strip():
            continue
        safe_skill = _normalise_custom_skill_name(skill)
        if safe_skill is None:
            return _json.dumps(
                {
                    "ok": False,
                    "error": "skills must contain only letters, numbers, spaces, underscores, or hyphens",
                }
            )
        normalised_skills.append(safe_skill)
    skills = normalised_skills

    try:
        from ..pool.manager import PoolManager

        manager = PoolManager.__new__(PoolManager)
        manager.lock = __import__("threading").Lock()
        manager.active = {}
        manager.persistent_agents = set()
        manager._ensure_profile(name)
    except Exception as exc:
        return _json.dumps({"ok": False, "error": f"failed to create profile: {exc}"})

    # Build complete profile files
    display_name = name.removeprefix("agency-").replace("-", " ").title()
    description = str(description or "").strip() or f"A {department} specialist agent"
    skill_lines = "\n".join(f"- {s}" for s in skills) if skills else "- general assistance"

    # SOUL.md — full standard structure
    soul_content = f"""# SOUL.md — {display_name}

## Identity

You are `{name}`, a Hermes Agency agent in the {department} department. {description}

## Mission

{description}

## Operating Principles

- Stay inside your specialty unless the task explicitly asks otherwise
- Prefer concrete artifacts, verified results, and concise handoffs
- Escalate to the right specialist by creating Kanban follow-up cards when needed
- Do not deploy, publish, delete, or mutate production resources without explicit approval
- Run tests before declaring work done

## Primary Responsibilities

{skill_lines}

## Non-Responsibilities

- Do not take work outside your department unless explicitly asked
- Do not deploy to production without approval
- Do not commit or push code without agency-git-steward

## Collaboration Style

You work with other agency agents through `agency_pool_send`. Use `agency_roster()` to find the right specialist. Escalate blockers to agency-orchestrator or agency-chief-of-staff.

## Safety Boundaries

Modify only code and configuration within your domain. Do not deploy to production without approval. Follow git discipline: prepare changes but do not commit or push without agency-git-steward. Run tests before declaring work done.

## Output Expectations

Concrete deliverables: code, documents, analysis, designs, or other artifacts appropriate to your role.

## Delegation Behavior

Delegate git operations to agency-git-steward. Delegate QA to agency-qa-tester. Delegate security review to agency-security-reviewer.

## Escalation Behavior

Escalate when: a change affects shared infrastructure, security concerns arise, architectural decisions are needed, or production deployment is required.

## Definition of Done

Done when: work is complete, tested/validated, documented where needed, and ready for review.

## Shared Workspace Protocol

Use the persistent shared workspace at `~/.hermes/.agency/workspace/` for cross-agent collaboration. Save final deliverables under `~/.hermes/.agency/workspace/deliverables/<board-id>/`. Use `~/.hermes/.agency/workspace/shared/` for handoff files another agent must read. Do not use `/tmp/` for durable Agency deliverables. Department Kanban tasks live on reusable department boards; use the board assigned by the dispatcher/orchestrator.

## Specialist-to-Specialist Delegation Protocol

Before delegating, call `agency_roster()` and choose an exact `agency-<role>` roster name. You may delegate only for review, cross-domain handoff, or git/release operations outside your ownership. Do not delegate to yourself or to `agency-orchestrator`; if orchestration is required, report the blocker instead. Use `agency_pool_send(name="agency-<role>", message="...")` with the workspace path, expected output, and validation criteria.
"""

    # profile.yaml
    yaml_content = f"""name: {name}
display_name: {display_name}
category: {department.lower()}
summary: {description}
agency:
  enabled: true
  auto_start: false
  allow_remote_tasks: false
  skills_from_profile: true
  incoming:
    tool_access: full
  relay_security:
    auto_allow_team: true
ownership:
  owns:
{chr(10).join(f"  - {s}" for s in (skills or ["general assistance"]))}
  does_not_own:
  - work outside {department} department
routing:
  delegates_to:
  - agency-git-steward
  - agency-qa-tester
"""

    # ROUTING.md
    routing_content = f"""# ROUTING.md — {display_name}

## Ownership

### Owns

{chr(10).join(f"- {s}" for s in (skills or ["general assistance"]))}

### Does Not Own

- work outside {department} department

## Typical Inputs

- tasks assigned by orchestrator or technical lead
- bug reports and feature requests

## Typical Outputs

- completed work artifacts appropriate to your role

## Delegation

### Should Delegate To

- agency-git-steward
- agency-qa-tester

### Should Receive Work From

- agency-orchestrator
- agency-chief-of-staff

## Escalation Triggers

- cross-department dependency
- security concern
- architectural decision needed

## Machine/File/Git Safety Rules

Modify only files within your domain. Do not deploy. Do not push. Prepare changes for review by agency-git-steward.

## Handoff Format

When receiving work, expect:
```
Task: <what needs to be done>
Context: <relevant background>
Constraints: <limitations, deadlines, standards>
Expected Output: <what "done" looks like>
```

When handing off, provide the same plus Validation criteria.
"""

    try:
        soul_path = profile_dir / "SOUL.md"
        soul_path.write_text(soul_content, encoding="utf-8")

        yaml_path = profile_dir / "profile.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        routing_path = profile_dir / "ROUTING.md"
        routing_path.write_text(routing_content, encoding="utf-8")

        nobundled_path = profile_dir / ".no-bundled-skills"
        nobundled_path.write_text("", encoding="utf-8")

        # Create department-appropriate starter skills
        _create_starter_skills(profile_dir, name, department, skills)
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

    name = str(name or "").strip()
    if not name:
        return _json.dumps({"ok": False, "error": "name is required"})
    name_error = _validate_agent_name(name)
    if name_error:
        return _json.dumps({"ok": False, "error": name_error})

    if not _lifecycle_tools_enabled():
        return _json.dumps(
            {
                "ok": False,
                "error": "Lifecycle tools are disabled. Set agency.lifecycle_tools_enabled: true in config.yaml to enable.",
            }
        )

    try:
        profile_dir = _profile_dir_for_agent_name(name)
    except ValueError as exc:
        return _json.dumps({"ok": False, "error": str(exc)})
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

    name = str(name or "").strip()
    if not name:
        return _json.dumps({"ok": False, "error": "name is required"})
    name_error = _validate_agent_name(name)
    if name_error:
        return _json.dumps({"ok": False, "error": name_error})

    if not _lifecycle_tools_enabled():
        return _json.dumps(
            {
                "ok": False,
                "error": "Lifecycle tools are disabled. Set agency.lifecycle_tools_enabled: true in config.yaml to enable.",
            }
        )

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

    name = str(name or "").strip()
    if not name:
        return _json.dumps({"ok": False, "error": "name is required"})
    name_error = _validate_agent_name(name)
    if name_error:
        return _json.dumps({"ok": False, "error": name_error})

    if not _lifecycle_tools_enabled():
        return _json.dumps(
            {
                "ok": False,
                "error": "Lifecycle tools are disabled. Set agency.lifecycle_tools_enabled: true in config.yaml to enable.",
            }
        )

    if name == "agency-orchestrator":
        return _json.dumps({"ok": False, "error": "cannot prune the orchestrator agent"})

    try:
        profile_dir = _profile_dir_for_agent_name(name)
    except ValueError as exc:
        return _json.dumps({"ok": False, "error": str(exc)})
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


def pool_department_roster(department: str) -> str:
    """List all agents in a department with their status."""
    import json as _json

    from ..departments import DEPARTMENT_AGENTS, canonical_agent_name

    department = str(department or "").strip()
    if not department:
        return _json.dumps({"ok": False, "error": "department is required"})

    # Case-insensitive match
    dept_key = None
    for key in DEPARTMENT_AGENTS:
        if key.lower() == department.lower():
            dept_key = key
            break
    if not dept_key:
        return _json.dumps(
            {
                "ok": False,
                "error": f"unknown department: {department}. Valid: {', '.join(sorted(DEPARTMENT_AGENTS.keys()))}",
            }
        )

    roster = load_roster()
    profiles = roster.get("profiles", [])
    dept_agents = DEPARTMENT_AGENTS[dept_key]

    # Find matching profiles
    matches = []
    for p in profiles:
        canon = canonical_agent_name(p["name"])
        if canon in dept_agents:
            matches.append(
                {
                    "name": p["name"],
                    "online": p.get("online", False),
                    "skills": p.get("skills", [])[:5],
                    "description": p.get("description", ""),
                }
            )

    return _json.dumps(
        {
            "ok": True,
            "department": dept_key,
            "total": len(dept_agents),
            "installed": len(matches),
            "agents": matches,
        }
    )


def pool_department_wake(department: str) -> str:
    """Wake all agents in a department."""
    import json as _json

    from ..departments import DEPARTMENT_AGENTS, canonical_agent_name

    department = str(department or "").strip()
    if not department:
        return _json.dumps({"ok": False, "error": "department is required"})

    dept_key = None
    for key in DEPARTMENT_AGENTS:
        if key.lower() == department.lower():
            dept_key = key
            break
    if not dept_key:
        return _json.dumps(
            {
                "ok": False,
                "error": f"unknown department: {department}",
            }
        )

    roster = load_roster()
    profiles = roster.get("profiles", [])
    dept_agents = set(DEPARTMENT_AGENTS[dept_key])

    results = []
    for p in profiles:
        canon = canonical_agent_name(p["name"])
        if canon in dept_agents and not p.get("online", False):
            try:
                wake_result = pool_wake(p["name"])
                import json as __json

                wake_data = __json.loads(wake_result)
                results.append({"name": p["name"], "ok": wake_data.get("ok", False)})
            except Exception as exc:
                results.append({"name": p["name"], "ok": False, "error": str(exc)})

    return _json.dumps(
        {
            "ok": True,
            "department": dept_key,
            "woken": sum(1 for r in results if r.get("ok")),
            "failed": sum(1 for r in results if not r.get("ok")),
            "results": results,
        }
    )


def pool_department_sleep(department: str) -> str:
    """Sleep all agents in a department."""
    import json as _json

    from ..departments import DEPARTMENT_AGENTS, canonical_agent_name

    department = str(department or "").strip()
    if not department:
        return _json.dumps({"ok": False, "error": "department is required"})

    dept_key = None
    for key in DEPARTMENT_AGENTS:
        if key.lower() == department.lower():
            dept_key = key
            break
    if not dept_key:
        return _json.dumps(
            {
                "ok": False,
                "error": f"unknown department: {department}",
            }
        )

    roster = load_roster()
    profiles = roster.get("profiles", [])
    dept_agents = set(DEPARTMENT_AGENTS[dept_key])

    results = []
    for p in profiles:
        canon = canonical_agent_name(p["name"])
        if canon in dept_agents and p.get("online", False):
            try:
                sleep_result = pool_sleep(p["name"])
                import json as __json

                sleep_data = __json.loads(sleep_result)
                results.append({"name": p["name"], "ok": sleep_data.get("ok", False)})
            except Exception as exc:
                results.append({"name": p["name"], "ok": False, "error": str(exc)})

    return _json.dumps(
        {
            "ok": True,
            "department": dept_key,
            "slept": sum(1 for r in results if r.get("ok")),
            "failed": sum(1 for r in results if not r.get("ok")),
            "results": results,
        }
    )
