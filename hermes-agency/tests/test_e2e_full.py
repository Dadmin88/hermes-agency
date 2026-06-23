#!/usr/bin/env python3
"""Full Phase 7 end-to-end validation for the Hermes Hermes Agency plugin.

This is intentionally a standalone validation script, not a pytest module.
It starts real Hermes Agency SDK nodes/daemons, sends real P2P tasks, verifies
team context, Kanban tracking, announcement records, completion artifacts, and
cleans up the nodes it owns.

Run from the repository root with:
    python3 hermes-agency/tests/test_e2e_full.py

Safety note:
    By default this script uses isolated temporary daemon homes for both local
    LAN nodes so it does not collide with gateway/Desktop-owned profile nodes.
    It still uses the real profile homes for card/config/Kanban behavior.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import signal
import sys
import tempfile
import time
import types
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OVERALL_TIMEOUT_SECONDS = float(os.getenv("AGENTANYCAST_E2E_TIMEOUT", "180"))
PEER_DISCOVERY_TIMEOUT_SECONDS = float(os.getenv("AGENTANYCAST_E2E_PEER_TIMEOUT", "20"))
TASK_TIMEOUT_SECONDS = float(os.getenv("AGENTANYCAST_E2E_TASK_TIMEOUT", "20"))
POLL_INTERVAL_SECONDS = 0.25
RELAY_MULTIADDR = os.getenv(
    "AGENTANYCAST_E2E_RELAY",
    "/ip4/100.123.57.115/tcp/4001/p2p/12D3KooWGE3zmqw2FJTyuNGAzSNCUxSNSeMvCtocULczXfX9Y8nK",
)
REGISTRY_ADDR = os.getenv("AGENTANYCAST_REGISTRY_ADDRS", "100.123.57.115:50052")

SCRIPT_PATH = Path(__file__).resolve()
PLUGIN_DIR = SCRIPT_PATH.parents[1]
REPO_ROOT = PLUGIN_DIR.parent
SDK_SRC_DIR = REPO_ROOT / "src"
HERMES_APP_DIR = Path.home() / ".hermes" / "hermes-agent"
GPT_PROFILE_HOME = Path.home() / ".hermes" / "profiles" / "gpt"
KATANA_PROFILE_HOME = Path.home() / ".hermes" / "profiles" / "katana"

# Let local checkout imports win over installed SDK/plugin copies, but keep the
# Hermes application importable so Kanban integration uses the real DB bridge.
sys.path.insert(0, str(SDK_SRC_DIR))
sys.path.insert(0, str(PLUGIN_DIR))
sys.path.insert(0, str(HERMES_APP_DIR))
os.environ.setdefault("AGENTANYCAST_REGISTRY_ADDRS", REGISTRY_ADDR)
os.environ.setdefault("HERMES_HOME", str(GPT_PROFILE_HOME))


class OverallTimeout(RuntimeError):
    pass


def _overall_timeout_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
    raise OverallTimeout(f"overall timeout exceeded ({OVERALL_TIMEOUT_SECONDS:.0f}s)")


signal.signal(signal.SIGALRM, _overall_timeout_handler)
signal.alarm(int(OVERALL_TIMEOUT_SECONDS))


def ts() -> str:
    return time.strftime("%H:%M:%S") + f".{int((time.time() % 1) * 1000):03d}"


def log(message: str) -> None:
    print(f"[{ts()}] {message}", flush=True)


@dataclass
class TestResult:
    # This file is a standalone script, not a pytest module. Without this flag,
    # pytest tries to collect the dataclass because its name starts with Test.
    __test__ = False

    name: str
    ok: bool
    detail: str = ""


RESULTS: list[TestResult] = []
FAILURES: list[str] = []
ARTIFACTS: dict[str, Any] = {}


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append(TestResult(name, ok, detail))
    status = "PASS" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    log(f"{status}: {name}{suffix}")
    if not ok:
        FAILURES.append(f"{name}: {detail}" if detail else name)
    return ok


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def install_hermes_stubs_if_needed() -> None:
    """Install tiny Hermes stubs only if the real Hermes app is unavailable."""

    try:
        import hermes_cli.config  # noqa: F401
        import hermes_constants  # noqa: F401

        return
    except Exception:
        pass

    constants = types.ModuleType("hermes_constants")
    setattr(
        constants,
        "get_hermes_home",
        lambda: Path(os.environ.get("HERMES_HOME", str(GPT_PROFILE_HOME))),
    )
    sys.modules.setdefault("hermes_constants", constants)

    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli.__path__ = []
    sys.modules.setdefault("hermes_cli", hermes_cli)

    config = types.ModuleType("hermes_cli.config")
    setattr(config, "load_config", lambda: {})
    setattr(config, "cfg_get", lambda cfg, *path, default=None: default)
    sys.modules.setdefault("hermes_cli.config", config)


def load_plugin_modules() -> Any:
    """Load node_manager.py with a synthetic package name.

    The checkout directory is named hermes-agency, which is not importable as a
    normal Python package. This imports plugin modules directly while preserving
    relative imports and avoiding execution of plugin __init__.py.
    """

    install_hermes_stubs_if_needed()
    package_name = "agency_hermes_plugin_e2e_full"
    package = types.ModuleType(package_name)
    package.__path__ = [str(PLUGIN_DIR)]
    sys.modules[package_name] = package
    return importlib.import_module(f"{package_name}.node_manager")


nm = load_plugin_modules()
config_mod = importlib.import_module("agency_hermes_plugin_e2e_full.config")
NodeManager = nm.NodeManager
AgencyConfig = config_mod.AgencyConfig
TeamConfig = config_mod.TeamConfig

from agentanycast import AgentCard, Skill  # noqa: E402

announcements_mod = importlib.import_module("agency_hermes_plugin_e2e_full.announcements")
kanban_mod = importlib.import_module("agency_hermes_plugin_e2e_full.kanban_bridge")
team_mod = importlib.import_module("agency_hermes_plugin_e2e_full.team_context")


def make_card(profile_name: str) -> AgentCard:
    display = "Katana" if profile_name == "katana" else "hermes-gpt"
    return AgentCard(
        name=display,
        description=f"Phase 7 Hermes Agency e2e validation node for {display}",
        version="1.0.0",
        skills=[
            Skill(id="hermes-chat", description="Receive a natural-language task"),
            Skill(id="agency-e2e", description="Phase 7 validation skill"),
            Skill(id=f"profile-{profile_name}", description=f"Profile marker for {profile_name}"),
        ],
    )


@dataclass
class ProfileRuntime:
    name: str
    profile_home: Path
    daemon_home: Path
    manager: Any

    @property
    def cfg(self) -> Any:
        return AgencyConfig(
            enabled=True,
            relay=RELAY_MULTIADDR,
            auto_start=False,
            skills_from_profile=False,
            allow_remote_tasks=True,
            trusted_peers=(),
            incoming_queue_limit=100,
            card_name="Katana" if self.name == "katana" else "hermes-gpt",
            home=self.daemon_home,
            team=TeamConfig(
                auto_discover=True,
                auto_register=True,
                inject_context=True,
                kanban_integration=True,
                self_serve=True,
                announce_progress=False,
                tenant="default",
                context_refresh_minutes=1,
            ),
        )


@contextmanager
def plugin_context(runtime: ProfileRuntime):
    old_home = os.environ.get("HERMES_HOME")
    old_profile = os.environ.get("HERMES_PROFILE")
    old_get_config = nm.get_config
    old_build_card = nm.build_card
    old_kanban_get_config = kanban_mod.get_config
    old_kanban_current_profile_name = kanban_mod.current_profile_name
    os.environ["HERMES_HOME"] = str(runtime.profile_home)
    os.environ["HERMES_PROFILE"] = runtime.name
    nm.get_config = lambda: runtime.cfg
    nm.build_card = lambda: make_card(runtime.name)
    kanban_mod.get_config = lambda: runtime.cfg
    kanban_mod.current_profile_name = lambda: runtime.name
    try:
        yield
    finally:
        nm.get_config = old_get_config
        nm.build_card = old_build_card
        kanban_mod.get_config = old_kanban_get_config
        kanban_mod.current_profile_name = old_kanban_current_profile_name
        if old_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = old_home
        if old_profile is None:
            os.environ.pop("HERMES_PROFILE", None)
        else:
            os.environ["HERMES_PROFILE"] = old_profile


def call(runtime: ProfileRuntime, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    with plugin_context(runtime):
        return fn(*args, **kwargs)


def new_runtime(name: str, profile_home: Path, daemon_home: Path) -> ProfileRuntime:
    return ProfileRuntime(
        name=name, profile_home=profile_home, daemon_home=daemon_home, manager=NodeManager()
    )


def start_runtime(runtime: ProfileRuntime) -> Any:
    runtime.daemon_home.mkdir(parents=True, exist_ok=True)
    state = call(runtime, runtime.manager.start_sync, timeout=60)
    if state.error:
        raise RuntimeError(state.error)
    require(state.started is True, f"{runtime.name} did not start")
    require(bool(state.peer_id), f"{runtime.name} peer_id missing")
    return state


def stop_runtime(runtime: ProfileRuntime) -> Any:
    return call(runtime, runtime.manager.stop_sync, timeout=30)


def list_peers(runtime: ProfileRuntime) -> list[dict[str, Any]]:
    return call(runtime, runtime.manager.list_peers_sync, timeout=10)


def refresh_team(runtime: ProfileRuntime) -> None:
    # No public sync wrapper exists for team refresh; use the manager's normal
    # submit path so the coroutine runs on the owned event loop with profile
    # config/card patched for this runtime.
    return call(
        runtime,
        runtime.manager._submit,
        runtime.manager._refresh_team_context_impl(force=True),
        timeout=20,
    )  # noqa: SLF001


def team_context(runtime: ProfileRuntime) -> str:
    return str(runtime.manager.info().get("team_context") or "")


def send_task_checked(
    runtime: ProfileRuntime,
    *,
    message: str,
    peer_id: str | None = None,
    skill: str | None = None,
    wait_seconds: float = 0,
    timeout: float = 30,
) -> dict[str, Any]:
    if not message.strip():
        raise ValueError("message is required")
    if sum(bool(item) for item in (peer_id, skill)) != 1:
        raise ValueError("exactly one of peer_id or skill is required")
    return call(
        runtime,
        runtime.manager.send_task_sync,
        message,
        peer_id=peer_id,
        skill=skill,
        wait_seconds=wait_seconds,
        timeout=timeout,
        conversation_context={
            "summary": "Phase 7 e2e validation",
            "sender": runtime.name,
            "channel": "test_e2e_full",
        },
    )


def task_status(runtime: ProfileRuntime, task_id: str) -> dict[str, Any] | None:
    return call(runtime, runtime.manager.task_status_sync, task_id, timeout=10)


def inbox(runtime: ProfileRuntime, limit: int = 20) -> list[dict[str, Any]]:
    return call(runtime, runtime.manager.incoming_tasks_sync, limit=limit, timeout=10)


def peer_seen(peers: list[dict[str, Any]], peer_id: str) -> bool:
    return any(p.get("peer_id") == peer_id for p in peers)


def wait_for_peers(
    a: ProfileRuntime, b: ProfileRuntime, timeout: float = PEER_DISCOVERY_TIMEOUT_SECONDS
) -> None:
    deadline = time.monotonic() + timeout
    last_a: list[dict[str, Any]] = []
    last_b: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        last_a = list_peers(a)
        last_b = list_peers(b)
        a_sees_b = peer_seen(last_a, b.manager.state.peer_id)
        b_sees_a = peer_seen(last_b, a.manager.state.peer_id)
        if a_sees_b and b_sees_a:
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(
        f"peers did not discover each other in {timeout}s; A peers={last_a}; B peers={last_b}"
    )


def wait_completed(
    runtime: ProfileRuntime, task_id: str, timeout: float = TASK_TIMEOUT_SECONDS
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = task_status(runtime, task_id)
        if last and last.get("status") == "completed" and last.get("artifact_text"):
            return last
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(f"task {task_id} did not complete in {timeout}s; last={last}")


def get_kanban_task(runtime: ProfileRuntime, a2a_task_id: str) -> dict[str, Any]:
    return call(runtime, kanban_mod.get_task, a2a_task_id)


def cleanup(*runtimes: ProfileRuntime) -> None:
    for runtime in runtimes:
        try:
            stop_runtime(runtime)
        except Exception as exc:
            log(f"cleanup warning for {runtime.name}: {type(exc).__name__}: {exc}")


def validate_plugin_load() -> None:
    name = "7.5 plugin modules load without errors"
    try:
        require(NodeManager is not None, "NodeManager not loaded")
        require(callable(getattr(kanban_mod, "track_delegation", None)), "Kanban bridge not loaded")
        require(
            callable(getattr(announcements_mod, "recent_announcements", None)),
            "announcements not loaded",
        )
        require(callable(getattr(team_mod, "build_team_context", None)), "team context not loaded")
        record(name, True)
    except Exception as exc:
        record(name, False, f"{type(exc).__name__}: {exc}")
        raise


def validate_lan() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="agency-phase7-lan-"))
    gpt = new_runtime("gpt", GPT_PROFILE_HOME, tmp / "gpt" / ".agency")
    katana = new_runtime("katana", KATANA_PROFILE_HOME, tmp / "katana" / ".agency")
    try:
        start_runtime(gpt)
        start_runtime(katana)
        record(
            "7.1 start both LAN nodes",
            True,
            f"gpt={gpt.manager.state.peer_id}; katana={katana.manager.state.peer_id}",
        )

        wait_for_peers(katana, gpt)
        record("7.1 a2a_list_peers sees both LAN nodes", True)

        refresh_team(gpt)
        refresh_team(katana)
        gpt_ctx = team_context(gpt)
        katana_ctx = team_context(katana)
        ARTIFACTS["gpt_team_context"] = gpt_ctx
        ARTIFACTS["katana_team_context"] = katana_ctx
        require(
            "Katana" in gpt_ctx and "skills:" in gpt_ctx,
            f"GPT team context missing Katana/skills: {gpt_ctx}",
        )
        require(
            "hermes-gpt" in katana_ctx and "skills:" in katana_ctx,
            f"Katana team context missing gpt/skills: {katana_ctx}",
        )
        record("7.1 team context shows names and skills", True)

        t0 = time.monotonic()
        sent_kg = send_task_checked(
            katana, message="What is your name?", peer_id=gpt.manager.state.peer_id, wait_seconds=10
        )
        done_kg = wait_completed(katana, sent_kg["task_id"])
        kg_latency = time.monotonic() - t0
        require(done_kg.get("status") == "completed", f"Katana->GPT status={done_kg.get('status')}")
        require(bool(done_kg.get("artifact_text")), "Katana->GPT artifact_text empty")
        record(
            "7.1 Katana -> GPT task completed with artifact",
            True,
            f"task={sent_kg['task_id']} latency={kg_latency:.3f}s",
        )

        t1 = time.monotonic()
        sent_gk = send_task_checked(
            gpt, message="What is your name?", peer_id=katana.manager.state.peer_id, wait_seconds=10
        )
        done_gk = wait_completed(gpt, sent_gk["task_id"])
        gk_latency = time.monotonic() - t1
        require(done_gk.get("status") == "completed", f"GPT->Katana status={done_gk.get('status')}")
        require(bool(done_gk.get("artifact_text")), "GPT->Katana artifact_text empty")
        record(
            "7.1 GPT -> Katana task completed with artifact",
            True,
            f"task={sent_gk['task_id']} latency={gk_latency:.3f}s",
        )

        katana_inbox = inbox(katana, limit=10)
        gpt_inbox = inbox(gpt, limit=10)
        require(
            any(
                item.get("task_id") == sent_gk["task_id"] and item.get("status") == "completed"
                for item in katana_inbox
            ),
            "Katana inbox missing completed GPT->Katana task",
        )
        require(
            any(
                item.get("task_id") == sent_kg["task_id"] and item.get("status") == "completed"
                for item in gpt_inbox
            ),
            "GPT inbox missing completed Katana->GPT task",
        )
        record("7.1 incoming queues recorded completed tasks", True)

        kb_kg = get_kanban_task(katana, sent_kg["task_id"])
        kb_gk = get_kanban_task(gpt, sent_gk["task_id"])
        require(kb_kg.get("available") and kb_kg.get("ok"), f"Katana Kanban lookup failed: {kb_kg}")
        require(kb_gk.get("available") and kb_gk.get("ok"), f"GPT Kanban lookup failed: {kb_gk}")
        require(
            kb_kg.get("task", {}).get("plugin_status") in {"done", "in_progress"},
            f"Katana Kanban unexpected status: {kb_kg}",
        )
        require(
            kb_gk.get("task", {}).get("plugin_status") in {"done", "in_progress"},
            f"GPT Kanban unexpected status: {kb_gk}",
        )
        record(
            "7.1 Kanban tasks created for delegations",
            True,
            f"katana_kb={kb_kg.get('task_id')}; gpt_kb={kb_gk.get('task_id')}",
        )

        anns = announcements_mod.recent_announcements(50)
        kinds = {item.get("kind") for item in anns}
        ARTIFACTS["announcements"] = anns
        require("delegate" in kinds, f"delegate announcement missing: {anns}")
        require("start" in kinds, f"start announcement missing: {anns}")
        require("complete" in kinds, f"complete announcement missing: {anns}")
        record("7.1 announcements recorded delegate/start/complete", True)

        info_gpt = gpt.manager.info()
        info_katana = katana.manager.info()
        require(
            info_gpt.get("started") and info_gpt.get("serve_task_running"),
            f"bad GPT info: {info_gpt}",
        )
        require(
            info_katana.get("started") and info_katana.get("serve_task_running"),
            f"bad Katana info: {info_katana}",
        )
        record("7.5 a2a_info-equivalent node state is correct", True)

        try:
            agents = call(gpt, gpt.manager.discover_sync, skill="hermes-chat", limit=25, timeout=15)
            require(isinstance(agents, list), f"discover returned non-list: {agents!r}")
            require(
                any(
                    (item.get("peer_id") == katana.manager.state.peer_id)
                    for item in agents
                    if isinstance(item, dict)
                ),
                f"discover did not include Katana: {agents}",
            )
            record("7.5 a2a_discover works via registry", True, f"results={len(agents)}")
        except Exception as exc:
            record("7.5 a2a_discover works via registry", False, f"{type(exc).__name__}: {exc}")

        # Peer leave/update behavior: stop Katana, force refresh on GPT, and require
        # that direct peer list no longer includes Katana. Registration TTL may keep
        # a recent registration visible briefly, so this check is based on live peers.
        stop_runtime(katana)
        deadline = time.monotonic() + 10
        last_peers: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            last_peers = list_peers(gpt)
            if not peer_seen(last_peers, katana.manager.state.last_peer_id):
                break
            time.sleep(POLL_INTERVAL_SECONDS)
        require(
            not peer_seen(last_peers, katana.manager.state.last_peer_id),
            f"Katana still in GPT peer list after stop: {last_peers}",
        )
        refresh_team(gpt)
        record("7.5 peer leave updates live peer list", True)

    finally:
        cleanup(gpt, katana)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    log(f"Script: {SCRIPT_PATH}")
    log(f"Repo root: {REPO_ROOT}")
    log(f"SDK source: {SDK_SRC_DIR}")
    log(f"Hermes app: {HERMES_APP_DIR}")
    log(f"Registry: {os.environ.get('AGENTANYCAST_REGISTRY_ADDRS')}")
    log(f"Relay: {RELAY_MULTIADDR}")

    try:
        validate_plugin_load()
        validate_lan()
    except Exception as exc:
        record("script exception", False, f"{type(exc).__name__}: {exc}")

    signal.alarm(0)
    log("==== Phase 7 full e2e results ====")
    for result in RESULTS:
        print(
            f"{'PASS' if result.ok else 'FAIL'}: {result.name}"
            + (f" - {result.detail}" if result.detail else ""),
            flush=True,
        )
    if ARTIFACTS:
        print(
            "ARTIFACTS:",
            json.dumps(ARTIFACTS, indent=2, sort_keys=True, default=str)[:12000],
            flush=True,
        )
    if FAILURES:
        log("Failures:")
        for failure in FAILURES:
            log(f"  - {failure}")
        return 1
    log("All Phase 7 local/LAN checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OverallTimeout as exc:
        record("Overall timeout", False, str(exc))
        raise SystemExit(1)
