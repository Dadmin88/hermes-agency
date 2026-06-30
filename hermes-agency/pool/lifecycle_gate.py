from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ALLOWED_ACTIVE_STATUSES = {"received", "queued", "processing"}
_DEFAULT_ALLOWED_REASONS = ("manual", "task", "handshake")
_DEFAULT_PERMANENT_AGENTS = ("agency-orchestrator",)


@dataclass(frozen=True)
class WakeRequest:
    agent_name: str
    reason: str = "manual"
    requested_by: str | None = None
    peer_id: str | None = None
    task_id: str | None = None
    requested_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class AgentSlot:
    name: str
    online: bool
    persistent: bool = False
    last_activity_at: float | None = None
    incoming_queue_size: int = 0
    incoming_processing_count: int = 0
    rss_mb: float = 0.0

    @property
    def busy(self) -> bool:
        return self.incoming_processing_count > 0 or self.incoming_queue_size > 0

    def idle_for_seconds(self, now: float | None = None) -> float | None:
        if self.last_activity_at is None:
            return None
        current = time.time() if now is None else now
        return max(0.0, current - self.last_activity_at)


@dataclass(frozen=True)
class ResourceSnapshot:
    available_mem_mb: float | None
    total_rss_mb: float
    runner_count: int = 0
    all_agent_pids: tuple[int, ...] = ()
    runner_pids: tuple[int, ...] = ()


@dataclass(frozen=True)
class WakeDecision:
    allowed: bool
    status: str
    reason: str
    request: WakeRequest
    target_online: bool = False
    sleep_candidate: AgentSlot | None = None
    resource_snapshot: ResourceSnapshot | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.allowed,
            "allowed": self.allowed,
            "status": self.status,
            "reason": self.reason,
            "agent_name": self.request.agent_name,
            "wake_reason": self.request.reason,
            "target_online": self.target_online,
            "sleep_candidate": self.sleep_candidate.name if self.sleep_candidate else None,
            "resource_snapshot": None
            if self.resource_snapshot is None
            else {
                "available_mem_mb": self.resource_snapshot.available_mem_mb,
                "total_rss_mb": self.resource_snapshot.total_rss_mb,
                "runner_count": self.resource_snapshot.runner_count,
                "all_agent_pids": list(self.resource_snapshot.all_agent_pids),
                "runner_pids": list(self.resource_snapshot.runner_pids),
            },
        }


@dataclass(frozen=True)
class PoolPolicy:
    max_online_agents: int = 3
    max_total_rss_mb: int = 2048
    min_free_mem_mb: int = 2048
    idle_sleep_after_seconds: int = 300
    busy_recent_activity_seconds: int = 120
    allow_discovery_wake: bool = False
    allow_handshake_wake: bool = True
    allow_sleep_for_wake: bool = True
    allowed_wake_reasons: tuple[str, ...] = _DEFAULT_ALLOWED_REASONS
    permanent_agents: tuple[str, ...] = _DEFAULT_PERMANENT_AGENTS


def _int_value(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _bool_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _string_tuple(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return default
    seen: set[str] = set()
    normalised: list[str] = []
    for item in items:
        clean = str(item or "").strip().lower()
        if clean and clean not in seen:
            seen.add(clean)
            normalised.append(clean)
    return tuple(normalised) or default


def _pool_mapping(config: Any) -> dict[str, Any]:
    if isinstance(config, dict):
        agency = config.get("agency")
        if isinstance(agency, dict):
            pool = agency.get("pool")
            return pool if isinstance(pool, dict) else {}
        pool = config.get("pool")
        return pool if isinstance(pool, dict) else {}
    pool = getattr(config, "pool", None)
    if pool is None:
        return {}
    return {
        "max_online_agents": getattr(pool, "max_online_agents", None),
        "max_active_agents": getattr(pool, "max_active_agents", None),
        "max_total_rss_mb": getattr(pool, "max_total_rss_mb", None),
        "min_free_mem_mb": getattr(pool, "min_free_mem_mb", None),
        "idle_sleep_after_seconds": getattr(pool, "idle_sleep_after_seconds", None),
        "busy_recent_activity_seconds": getattr(pool, "busy_recent_activity_seconds", None),
        "allow_discovery_wake": getattr(pool, "allow_discovery_wake", None),
        "allow_handshake_wake": getattr(pool, "allow_handshake_wake", None),
        "allow_sleep_for_wake": getattr(pool, "allow_sleep_for_wake", None),
        "allowed_wake_reasons": getattr(pool, "allowed_wake_reasons", None),
        "permanent_agents": getattr(pool, "permanent_agents", None),
    }


def pool_policy(config: Any) -> PoolPolicy:
    pool = _pool_mapping(config)
    max_online_raw = pool.get("max_online_agents")
    if max_online_raw is None:
        max_online_raw = pool.get("max_active_agents")
    return PoolPolicy(
        max_online_agents=_int_value(max_online_raw, 3),
        max_total_rss_mb=_int_value(pool.get("max_total_rss_mb"), 2048),
        min_free_mem_mb=_int_value(pool.get("min_free_mem_mb"), 2048),
        idle_sleep_after_seconds=_int_value(pool.get("idle_sleep_after_seconds"), 300),
        busy_recent_activity_seconds=_int_value(pool.get("busy_recent_activity_seconds"), 120),
        allow_discovery_wake=_bool_value(pool.get("allow_discovery_wake"), False),
        allow_handshake_wake=_bool_value(pool.get("allow_handshake_wake"), True),
        allow_sleep_for_wake=_bool_value(pool.get("allow_sleep_for_wake"), True),
        allowed_wake_reasons=_string_tuple(
            pool.get("allowed_wake_reasons"), _DEFAULT_ALLOWED_REASONS
        ),
        permanent_agents=_string_tuple(pool.get("permanent_agents"), _DEFAULT_PERMANENT_AGENTS),
    )


def _profiles_dir() -> Path:
    return Path(
        os.environ.get("HERMES_PROFILES_DIR", Path.home() / ".hermes" / "profiles")
    ).expanduser()


def _read_proc_nul_file(path: Path) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    return [item.decode(errors="ignore") for item in raw.split(b"\0") if item]


def _proc_cmdline(pid: int, proc_root: Path = Path("/proc")) -> list[str]:
    return _read_proc_nul_file(proc_root / str(pid) / "cmdline")


def _proc_environ(pid: int, proc_root: Path = Path("/proc")) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in _read_proc_nul_file(proc_root / str(pid) / "environ"):
        key, sep, value = item.partition("=")
        if sep:
            env[key] = value
    return env


def _proc_rss_kb(pid: int, proc_root: Path = Path("/proc")) -> int:
    try:
        lines = (
            (proc_root / str(pid) / "status")
            .read_text(encoding="utf-8", errors="ignore")
            .splitlines()
        )
    except OSError:
        return 0
    for line in lines:
        if line.startswith("VmRSS:"):
            parts = line.split()
            try:
                return int(parts[1]) if len(parts) > 1 else 0
            except ValueError:
                return 0
    return 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_profile_process(
    name: str, profile_dir: Path, pid: int, proc_root: Path = Path("/proc")
) -> bool:
    if pid == os.getpid():
        return False
    argv = _proc_cmdline(pid, proc_root=proc_root)
    if not argv:
        return False
    joined = "\0".join(argv)
    env = _proc_environ(pid, proc_root=proc_root)
    if env.get("HERMES_PROFILE") == name:
        return True
    home_match = env.get("HERMES_HOME")
    if home_match:
        try:
            if Path(home_match).expanduser().resolve() == profile_dir.expanduser().resolve():
                return True
        except OSError:
            if Path(home_match).expanduser() == profile_dir.expanduser():
                return True
    runner_fragment = f"profiles/{name}/plugins/hermes-agency/pool/agency_node_runner.py"
    daemon_fragment = f"profiles/{name}/.agency/"
    return runner_fragment in joined or ("agentanycastd" in joined and daemon_fragment in joined)


def profile_process_pids(
    name: str, profile_dir: Path, proc_root: Path = Path("/proc")
) -> list[int]:
    pids: list[int] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return pids
    for entry in entries:
        if entry.name.isdigit() and _is_profile_process(
            name, profile_dir, int(entry.name), proc_root=proc_root
        ):
            pids.append(int(entry.name))
    return sorted(set(pids))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def profile_incoming_metrics(profile_dir: Path) -> tuple[int, int, float | None]:
    payload = _read_json(profile_dir / ".agency" / "incoming_queue.json")
    raw_records = payload.get("records") if isinstance(payload, dict) else []
    if not isinstance(raw_records, list):
        return 0, 0, None
    queue_size = 0
    processing = 0
    last_activity_at: float | None = None
    for item in raw_records:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status not in _ALLOWED_ACTIVE_STATUSES:
            continue
        if status == "processing":
            processing += 1
        else:
            queue_size += 1
        updated_at = item.get("updated_at")
        try:
            updated = float(updated_at)
        except (TypeError, ValueError):
            updated = None
        if updated is not None and (last_activity_at is None or updated > last_activity_at):
            last_activity_at = updated
    return queue_size, processing, last_activity_at


def resource_snapshot(proc_root: Path = Path("/proc")) -> ResourceSnapshot:
    all_agent_pids: list[int] = []
    runner_pids: list[int] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        argv = _proc_cmdline(pid, proc_root=proc_root)
        if not argv:
            continue
        joined = "\0".join(argv)
        env = _proc_environ(pid, proc_root=proc_root)
        profile_name = str(env.get("HERMES_PROFILE") or "").strip()
        is_runner = any(Path(arg).name == "agency_node_runner.py" for arg in argv)
        is_daemon = "agentanycastd" in joined and "/profiles/agency-" in joined
        if is_runner or is_daemon or profile_name.startswith("agency-"):
            all_agent_pids.append(pid)
            if is_runner:
                runner_pids.append(pid)
    available_mem_mb: float | None = None
    try:
        meminfo = (proc_root / "meminfo").read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in meminfo:
            if line.startswith("MemAvailable:"):
                parts = line.split()
                available_mem_mb = round(int(parts[1]) / 1024, 1)
                break
    except Exception:
        available_mem_mb = None
    total_rss_kb = sum(_proc_rss_kb(pid, proc_root=proc_root) for pid in set(all_agent_pids))
    return ResourceSnapshot(
        available_mem_mb=available_mem_mb,
        total_rss_mb=round(total_rss_kb / 1024, 1),
        runner_count=len(set(runner_pids)),
        all_agent_pids=tuple(sorted(set(all_agent_pids))),
        runner_pids=tuple(sorted(set(runner_pids))),
    )


def build_agent_slots(
    config: Any,
    *,
    active_map: dict[str, dict[str, Any]] | None = None,
    proc_root: Path = Path("/proc"),
    profiles_dir: Path | None = None,
) -> list[AgentSlot]:
    policy = pool_policy(config)
    profiles_root = profiles_dir or _profiles_dir()
    slots: list[AgentSlot] = []
    seen: set[str] = set()

    if active_map is not None:
        for name, data in active_map.items():
            seen.add(name)
            last_active = data.get("last_active")
            last_ts = last_active.timestamp() if hasattr(last_active, "timestamp") else None
            rss_mb = 0.0
            proc = data.get("proc")
            if proc is not None and getattr(proc, "pid", None):
                rss_mb = round(_proc_rss_kb(int(proc.pid), proc_root=proc_root) / 1024, 1)
            slots.append(
                AgentSlot(
                    name=name,
                    online=proc is None or getattr(proc, "poll", lambda: None)() is None,
                    persistent=bool(data.get("persistent")) or name in policy.permanent_agents,
                    last_activity_at=last_ts,
                    rss_mb=rss_mb,
                )
            )
        return slots

    try:
        from .roster import load_roster

        roster = load_roster()
    except Exception:
        roster = {"profiles": []}

    for item in roster.get("profiles") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        profile_dir = profiles_root / name
        queue_size, processing_count, queue_activity_at = profile_incoming_metrics(profile_dir)
        pids = profile_process_pids(name, profile_dir, proc_root=proc_root)
        rss_mb = round(sum(_proc_rss_kb(pid, proc_root=proc_root) for pid in pids) / 1024, 1)
        last_seen_raw = item.get("last_wake_attempt_at") or item.get("last_seen")
        try:
            last_seen_at = float(last_seen_raw) if last_seen_raw is not None else None
        except (TypeError, ValueError):
            last_seen_at = None
        last_activity_at = queue_activity_at if queue_activity_at is not None else last_seen_at
        slots.append(
            AgentSlot(
                name=name,
                online=bool(item.get("online")) or bool(pids),
                persistent=name in policy.permanent_agents,
                last_activity_at=last_activity_at,
                incoming_queue_size=queue_size,
                incoming_processing_count=processing_count,
                rss_mb=rss_mb,
            )
        )
    return slots


def select_sleep_candidate(
    slots: list[AgentSlot],
    config: Any,
    *,
    exclude_names: set[str] | None = None,
    now: float | None = None,
) -> AgentSlot | None:
    policy = pool_policy(config)
    current = time.time() if now is None else now
    excluded = exclude_names or set()
    candidates: list[tuple[float, AgentSlot]] = []
    for slot in slots:
        if not slot.online or slot.name in excluded or slot.persistent:
            continue
        if slot.busy:
            continue
        idle_for = slot.idle_for_seconds(current)
        if idle_for is None:
            continue
        if idle_for < policy.busy_recent_activity_seconds:
            continue
        if idle_for < policy.idle_sleep_after_seconds:
            continue
        candidates.append((idle_for, slot))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1].name))
    return candidates[0][1]


def _wake_denial_status(reason: str) -> str:
    return "queued" if reason in {"task", "handshake"} else "denied"


def evaluate_wake_request(
    request: WakeRequest,
    config: Any,
    *,
    slots: list[AgentSlot] | None = None,
    snapshot: ResourceSnapshot | None = None,
    now: float | None = None,
) -> WakeDecision:
    policy = pool_policy(config)
    current = time.time() if now is None else now
    snapshot = snapshot or resource_snapshot()
    slots = list(slots or [])
    target_slot = next((slot for slot in slots if slot.name == request.agent_name), None)
    reason = str(request.reason or "manual").strip().lower()

    allowed_reasons = set(policy.allowed_wake_reasons)
    if reason == "discovery" and not policy.allow_discovery_wake:
        allowed_reasons.discard("discovery")
    if reason == "handshake" and not policy.allow_handshake_wake:
        allowed_reasons.discard("handshake")
    if reason not in allowed_reasons:
        return WakeDecision(
            allowed=False,
            status=_wake_denial_status(reason),
            reason=f"wake reason '{reason}' is not allowed by policy",
            request=request,
            target_online=bool(target_slot and target_slot.online),
            resource_snapshot=snapshot,
        )

    if target_slot and target_slot.online:
        return WakeDecision(
            allowed=True,
            status="approved",
            reason=f"{request.agent_name} is already online",
            request=request,
            target_online=True,
            resource_snapshot=snapshot,
        )

    current_non_permanent = sum(1 for slot in slots if slot.online and not slot.persistent)
    target_persistent = request.agent_name in policy.permanent_agents
    effective_online = current_non_permanent if target_persistent else current_non_permanent + 1
    blockers: list[str] = []
    requires_swap = False

    if not target_persistent and policy.max_online_agents == 0:
        blockers.append("pool wakes are disabled by config")
    elif (
        not target_persistent
        and policy.max_online_agents
        and effective_online > policy.max_online_agents
    ):
        blockers.append(
            f"online agent limit reached ({current_non_permanent}/{policy.max_online_agents})"
        )
        requires_swap = True

    if policy.max_total_rss_mb and snapshot.total_rss_mb >= policy.max_total_rss_mb:
        blockers.append(
            f"pool RSS {snapshot.total_rss_mb} MiB >= limit={policy.max_total_rss_mb} MiB"
        )
        requires_swap = True

    if (
        policy.min_free_mem_mb
        and snapshot.available_mem_mb is not None
        and snapshot.available_mem_mb < policy.min_free_mem_mb
    ):
        blockers.append(
            f"free memory {snapshot.available_mem_mb} MiB < floor={policy.min_free_mem_mb} MiB"
        )
        requires_swap = True

    if not blockers:
        return WakeDecision(
            allowed=True,
            status="approved",
            reason=f"wake approved for {request.agent_name}",
            request=request,
            resource_snapshot=snapshot,
        )

    candidate = None
    if policy.allow_sleep_for_wake and requires_swap:
        candidate = select_sleep_candidate(
            slots,
            config,
            exclude_names={request.agent_name},
            now=current,
        )
        if candidate is not None:
            return WakeDecision(
                allowed=True,
                status="approved",
                reason=(
                    f"wake approved for {request.agent_name} after sleeping idle agent {candidate.name}; "
                    + "; ".join(blockers)
                ),
                request=request,
                sleep_candidate=candidate,
                resource_snapshot=snapshot,
            )

    return WakeDecision(
        allowed=False,
        status=_wake_denial_status(reason),
        reason=f"wake blocked for {request.agent_name}: {'; '.join(blockers)}",
        request=request,
        sleep_candidate=candidate,
        resource_snapshot=snapshot,
    )
