#!/usr/bin/env python3
"""Standalone end-to-end test for the Hermes Hermes Agency plugin.

This is intentionally *not* pytest. It starts real Hermes Agency SDK nodes/daemons,
sends real P2P tasks, and prints PASS/FAIL for each scenario.

Run from the repository root with:
    python3 hermes-agency/tests/test_e2e.py

The script imports the plugin NodeManager directly and uses isolated daemon homes
for additional local nodes so multiple daemons can run in one process.
"""

from __future__ import annotations

import importlib
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

OVERALL_TIMEOUT_SECONDS = float(os.getenv("AGENTANYCAST_E2E_TIMEOUT", "90"))
PEER_DISCOVERY_TIMEOUT_SECONDS = float(os.getenv("AGENTANYCAST_E2E_PEER_TIMEOUT", "10"))
TASK_TIMEOUT_SECONDS = float(os.getenv("AGENTANYCAST_E2E_TASK_TIMEOUT", "10"))
POLL_INTERVAL_SECONDS = 0.25
RELAY_MULTIADDR = os.getenv("AGENTANYCAST_E2E_RELAY", "").strip()
REGISTRY_ADDR = os.getenv("AGENTANYCAST_E2E_REGISTRY", "").strip()

SCRIPT_PATH = Path(__file__).resolve()
PLUGIN_DIR = SCRIPT_PATH.parents[1]
REPO_ROOT = PLUGIN_DIR.parent
SDK_SRC_DIR = REPO_ROOT / "src"
GPT_PROFILE_HOME = Path.home() / ".hermes" / "profiles" / "gpt"
KATANA_PROFILE_HOME = Path.home() / ".hermes" / "profiles" / "katana"

# Let local checkout imports win over any installed copy.
sys.path.insert(0, str(SDK_SRC_DIR))
sys.path.insert(0, str(PLUGIN_DIR))
if REGISTRY_ADDR:
    os.environ["AGENTANYCAST_REGISTRY_ADDRS"] = REGISTRY_ADDR
else:
    # The lightweight localhost e2e suite should not accidentally talk to a
    # developer's live relay/registry. Cross-network coverage belongs in
    # test_e2e_full.py or explicit manual validation.
    os.environ.pop("AGENTANYCAST_REGISTRY_ADDRS", None)
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


def install_minimal_hermes_stubs() -> None:
    """Provide tiny Hermes modules needed at plugin import time.

    The e2e script exercises NodeManager, not Hermes CLI/config loading. In a
    source checkout the Hermes application modules may not be importable, so we
    install minimal stubs and then patch NodeManager's get_config/build_card per
    runtime below.
    """

    if "hermes_constants" not in sys.modules:
        constants = types.ModuleType("hermes_constants")
        setattr(
            constants,
            "get_hermes_home",
            lambda: Path(os.environ.get("HERMES_HOME", str(GPT_PROFILE_HOME))),
        )
        sys.modules["hermes_constants"] = constants

    if "hermes_cli" not in sys.modules:
        hermes_cli = types.ModuleType("hermes_cli")
        hermes_cli.__path__ = []  # mark as package
        sys.modules["hermes_cli"] = hermes_cli

    if "hermes_cli.config" not in sys.modules:
        config = types.ModuleType("hermes_cli.config")
        setattr(config, "load_config", lambda: {})
        setattr(config, "cfg_get", lambda cfg, *path, default=None: default)
        sys.modules["hermes_cli.config"] = config


def load_plugin_modules() -> Any:
    """Load node_manager.py from hermes-agency with a synthetic package name.

    A bare `sys.path.insert(0, hermes_plugin_dir); import node_manager` does not
    work with this checkout because node_manager.py uses relative imports. This
    imports the plugin files directly from hermes-agency while assigning a valid
    package name for Python's import machinery, without executing __init__.py.
    """

    install_minimal_hermes_stubs()
    package_name = "agency_hermes_plugin_e2e"
    package = types.ModuleType(package_name)
    package.__path__ = [str(PLUGIN_DIR)]
    sys.modules[package_name] = package
    return importlib.import_module(f"{package_name}.node_manager")


nm = load_plugin_modules()
config_mod = importlib.import_module("agency_hermes_plugin_e2e.config")
kanban_mod = importlib.import_module("agency_hermes_plugin_e2e.kanban_bridge")
NodeManager = nm.NodeManager
AgencyConfig = config_mod.AgencyConfig
IncomingConfig = config_mod.IncomingConfig
TeamConfig = config_mod.TeamConfig

# Keep background worker code paths in this lightweight localhost suite from
# reaching a developer's real Kanban DB. test_e2e_full.py covers Kanban paths.
_DISABLED_KANBAN_CFG = AgencyConfig(
    enabled=True,
    team=TeamConfig(kanban_integration=False),
)
kanban_mod.get_config = lambda: _DISABLED_KANBAN_CFG
kanban_mod.current_profile_name = lambda: "e2e"

from agentanycast import AgentCard, Skill  # noqa: E402


def make_card(profile_name: str) -> AgentCard:
    return AgentCard(
        name=f"test-{profile_name}",
        description=f"Hermes Agency e2e test card for {profile_name}",
        version="1.0.0",
        skills=[
            Skill(id="test", description="E2E test skill"),
            Skill(id="hermes-chat", description="Receive a natural-language task"),
        ],
    )


@dataclass
class ProfileRuntime:
    name: str
    profile_home: Path
    daemon_home: Path
    manager: Any
    owns_daemon_home: bool = False

    @property
    def cfg(self) -> Any:
        return AgencyConfig(
            enabled=True,
            relay=RELAY_MULTIADDR or None,
            auto_start=False,
            skills_from_profile=False,
            allow_remote_tasks=True,
            trusted_peers=(),
            incoming_queue_limit=100,
            incoming=IncomingConfig(mode="template"),
            home=self.daemon_home,
            team=TeamConfig(
                auto_discover=False,
                auto_register=False,
                inject_context=False,
                kanban_integration=False,
            ),
        )


@contextmanager
def plugin_context(runtime: ProfileRuntime):
    """Patch plugin module globals for one manager operation.

    NodeManager was written for one active Hermes profile per process. The e2e
    test runs multiple managers in one process, so each public call temporarily
    supplies the target profile's card/config.
    """

    old_home = os.environ.get("HERMES_HOME")
    old_get_config = nm.get_config
    old_build_card = nm.build_card
    old_kanban_get_config = kanban_mod.get_config
    old_kanban_current_profile_name = kanban_mod.current_profile_name
    os.environ["HERMES_HOME"] = str(runtime.profile_home)
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


def call(runtime: ProfileRuntime, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    with plugin_context(runtime):
        return fn(*args, **kwargs)


def new_runtime(name: str, profile_home: Path, daemon_home: Path | None = None) -> ProfileRuntime:
    owns_daemon_home = daemon_home is None
    if daemon_home is None:
        daemon_home = Path(tempfile.mkdtemp(prefix=f"agency-e2e-{name}-")) / ".agency"
    return ProfileRuntime(
        name=name,
        profile_home=profile_home,
        daemon_home=daemon_home,
        manager=NodeManager(),
        owns_daemon_home=owns_daemon_home,
    )


def start_runtime(runtime: ProfileRuntime) -> Any:
    runtime.daemon_home.mkdir(parents=True, exist_ok=True)
    state = call(runtime, runtime.manager.start_sync, timeout=45)
    if state.error:
        raise RuntimeError(state.error)
    return state


def stop_runtime(runtime: ProfileRuntime) -> Any:
    return call(runtime, runtime.manager.stop_sync, timeout=20)


def list_peers(runtime: ProfileRuntime) -> list[dict[str, Any]]:
    return call(runtime, runtime.manager.list_peers_sync, timeout=5)


def send_task_checked(
    runtime: ProfileRuntime,
    *,
    message: str,
    peer_id: str | None = None,
    skill: str | None = None,
    wait_seconds: float = 0,
    timeout: float = 20,
) -> dict[str, Any]:
    """Direct NodeManager send with the same validation as the plugin tool."""

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
    )


def task_status(runtime: ProfileRuntime, task_id: str) -> dict[str, Any] | None:
    return call(runtime, runtime.manager.task_status_sync, task_id, timeout=5)


def inbox(runtime: ProfileRuntime, limit: int = 20) -> list[dict[str, Any]]:
    return call(runtime, runtime.manager.incoming_tasks_sync, limit=limit, timeout=5)


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


def cleanup(*runtimes: ProfileRuntime) -> None:
    for runtime in runtimes:
        try:
            stop_runtime(runtime)
        except Exception as exc:  # best-effort cleanup
            log(f"cleanup warning for {runtime.name}: {type(exc).__name__}: {exc}")
        if runtime.owns_daemon_home:
            shutil.rmtree(runtime.daemon_home.parent, ignore_errors=True)


def scenario_a() -> None:
    name = "Scenario A: Node lifecycle"
    runtime = new_runtime("gpt", GPT_PROFILE_HOME)
    try:
        t0 = time.monotonic()
        state1 = start_runtime(runtime)
        first_peer = state1.peer_id
        require(bool(first_peer), "peer_id was not set")
        require(state1.started is True, "state.started is not True")
        require(
            runtime.manager._node is not None and runtime.manager._node.is_running,
            "node.is_running is not True",
        )
        log(f"{name}: first start peer_id={first_peer} latency={time.monotonic() - t0:.2f}s")

        stopped1 = stop_runtime(runtime)
        require(stopped1.started is False, "state.started still True after stop")
        require(runtime.manager._node is None, "manager node was not cleared after stop")

        t1 = time.monotonic()
        state2 = start_runtime(runtime)
        second_peer = state2.peer_id
        require(
            second_peer == first_peer, f"persistent identity changed: {first_peer} -> {second_peer}"
        )
        log(f"{name}: second start peer_id={second_peer} latency={time.monotonic() - t1:.2f}s")
        stopped2 = stop_runtime(runtime)
        require(stopped2.started is False, "state.started still True after second stop")
        record(name, True)
    except Exception as exc:
        record(name, False, f"{type(exc).__name__}: {exc}")
        cleanup(runtime)


def scenario_b() -> None:
    name = "Scenario B: Self-send (two localhost nodes)"
    tmp = Path(tempfile.mkdtemp(prefix="agency-e2e-katana-"))
    a = new_runtime("gpt", GPT_PROFILE_HOME)
    b = new_runtime("katana", KATANA_PROFILE_HOME, tmp / ".agency")
    try:
        start_runtime(a)
        start_runtime(b)
        log(f"{name}: A={a.manager.state.peer_id} B={b.manager.state.peer_id}")
        wait_for_peers(a, b)
        record("Scenario B: a2a_list_peers both directions", True)

        sent_ab = send_task_checked(
            a, message="e2e hello from gpt to katana", peer_id=b.manager.state.peer_id
        )
        done_ab = wait_completed(a, sent_ab["task_id"])
        require(done_ab.get("status") == "completed", f"A->B status={done_ab.get('status')}")
        require(bool(done_ab.get("artifact_text")), "A->B artifact_text empty")
        log(f"{name}: A->B task={sent_ab['task_id']} completed")

        sent_ba = send_task_checked(
            b, message="e2e hello from katana to gpt", peer_id=a.manager.state.peer_id
        )
        done_ba = wait_completed(b, sent_ba["task_id"])
        require(done_ba.get("status") == "completed", f"B->A status={done_ba.get('status')}")
        require(bool(done_ba.get("artifact_text")), "B->A artifact_text empty")
        log(f"{name}: B->A task={sent_ba['task_id']} completed")
        record(name, True)
    except Exception as exc:
        record(name, False, f"{type(exc).__name__}: {exc}")
    finally:
        cleanup(a, b)
        shutil.rmtree(tmp, ignore_errors=True)


def scenario_c() -> None:
    name = "Scenario C: Error handling"
    runtime = new_runtime("gpt", GPT_PROFILE_HOME)
    try:
        start_runtime(runtime)
        checks: list[tuple[str, Callable[[], Any]]] = [
            (
                "empty message",
                lambda: send_task_checked(
                    runtime, message="", peer_id=runtime.manager.state.peer_id
                ),
            ),
            (
                "both peer_id and skill",
                lambda: send_task_checked(
                    runtime,
                    message="bad target",
                    peer_id=runtime.manager.state.peer_id,
                    skill="test",
                ),
            ),
            (
                "neither peer_id nor skill",
                lambda: send_task_checked(runtime, message="bad target"),
            ),
        ]
        for check_name, fn in checks:
            try:
                fn()
            except Exception as exc:
                log(f"{name}: expected error for {check_name}: {type(exc).__name__}: {exc}")
            else:
                raise AssertionError(f"expected error for {check_name}")

        missing = task_status(runtime, "nonexistent-task-id")
        require(missing is None, f"nonexistent task status returned {missing!r}")

        fake_peer = "12D3KooW0000000000000000000000000000000000000000000000000"
        try:
            bad_send = send_task_checked(
                runtime,
                message="this should not reach a real peer",
                peer_id=fake_peer,
                wait_seconds=1,
                timeout=5,
            )
        except Exception as exc:
            log(f"{name}: expected nonexistent peer error: {type(exc).__name__}: {exc}")
        else:
            require(
                bad_send.get("wait_error") or bad_send.get("status") != "completed",
                f"nonexistent peer unexpectedly completed: {bad_send}",
            )
            log(f"{name}: nonexistent peer handled gracefully: {bad_send}")
        record(name, True)
    except Exception as exc:
        record(name, False, f"{type(exc).__name__}: {exc}")
    finally:
        cleanup(runtime)


def scenario_d() -> None:
    name = "Scenario D: Incoming task queue"
    tmp = Path(tempfile.mkdtemp(prefix="agency-e2e-queue-"))
    a = new_runtime("gpt", GPT_PROFILE_HOME)
    b = new_runtime("katana", KATANA_PROFILE_HOME, tmp / ".agency")
    try:
        start_runtime(a)
        start_runtime(b)
        log(f"{name}: A={a.manager.state.peer_id} B={b.manager.state.peer_id}")
        wait_for_peers(a, b)

        sent: list[dict[str, Any]] = []
        for idx in range(3):
            sent.append(
                send_task_checked(
                    a,
                    message=f"rapid queue task {idx + 1}",
                    peer_id=b.manager.state.peer_id,
                )
            )
        for item in sent:
            wait_completed(a, item["task_id"])

        records = inbox(b, limit=10)
        sent_ids = {item["task_id"] for item in sent}
        relevant = [rec for rec in records if rec.get("task_id") in sent_ids]
        require(
            len(relevant) == 3, f"expected 3 inbox records, got {len(relevant)}; records={records}"
        )
        for rec in relevant:
            require(rec.get("status") == "completed", f"record not completed: {rec}")
            for field in ("task_id", "sender_peer_id", "status", "result_text"):
                require(bool(rec.get(field)), f"record missing {field}: {rec}")
        record(name, True)
    except Exception as exc:
        record(name, False, f"{type(exc).__name__}: {exc}")
    finally:
        cleanup(a, b)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    log(f"Script: {SCRIPT_PATH}")
    log(f"Repo root: {REPO_ROOT}")
    log(f"SDK source: {SDK_SRC_DIR}")
    log(f"Registry: {os.environ.get('AGENTANYCAST_REGISTRY_ADDRS')}")
    log(f"Relay: {RELAY_MULTIADDR}")

    for scenario in (scenario_a, scenario_b, scenario_c, scenario_d):
        scenario()

    signal.alarm(0)
    log("==== Hermes Agency e2e results ====")
    for result in RESULTS:
        print(
            f"{'PASS' if result.ok else 'FAIL'}: {result.name}"
            + (f" - {result.detail}" if result.detail else ""),
            flush=True,
        )
    if FAILURES:
        log("Failures:")
        for failure in FAILURES:
            log(f"  - {failure}")
        return 1
    log("All scenarios passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OverallTimeout as exc:
        record("Overall timeout", False, str(exc))
        raise SystemExit(1)
