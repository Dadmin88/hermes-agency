"""Regression tests for pool runner process ownership checks."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def pool_tools(monkeypatch):
    package = types.ModuleType("process_safety_plugin")
    package.__path__ = [str(PLUGIN_DIR)]
    monkeypatch.setitem(sys.modules, package.__name__, package)

    pool_package = types.ModuleType("process_safety_plugin.pool")
    pool_package.__path__ = [str(PLUGIN_DIR / "pool")]
    monkeypatch.setitem(sys.modules, pool_package.__name__, pool_package)

    roster = types.ModuleType("process_safety_plugin.pool.roster")
    for name in (
        "_atomic_write_json",
        "_load_json",
        "build_roster",
        "ensure_profile_plugins",
        "find_agent",
        "load_roster",
        "queue_offline_task",
        "record_wake_attempt",
        "roster_state_path",
        "save_roster",
        "update_agent_status",
    ):
        setattr(roster, name, MagicMock())
    monkeypatch.setitem(sys.modules, roster.__name__, roster)

    spec = importlib.util.spec_from_file_location(
        "process_safety_plugin.pool.tools", PLUGIN_DIR / "pool" / "tools.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    def pidfd_open(pid: int, _flags: int = 0) -> int:
        return pid + 10_000

    def pidfd_send_signal(pidfd: int, sig: int, *_args) -> None:
        module.os.kill(pidfd - 10_000, sig)

    monkeypatch.setattr(module.os, "pidfd_open", pidfd_open)
    monkeypatch.setattr(module.os, "close", lambda _pidfd: None)
    monkeypatch.setattr(module.signal, "pidfd_send_signal", pidfd_send_signal)
    return module


def _write_proc_process(proc_root: Path, pid: int, argv: list[str], env: dict[str, str]) -> None:
    process = proc_root / str(pid)
    process.mkdir(parents=True, exist_ok=True)
    (process / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
    (process / "environ").write_bytes(
        "\0".join(f"{key}={value}" for key, value in env.items()).encode() + b"\0"
    )


def test_stop_removes_unrelated_live_pidfile_without_signaling(pool_tools, monkeypatch, tmp_path):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    pidfile = profile_dir / ".agency" / "runner.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("4321", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _write_proc_process(proc_root, 4321, ["python", "unrelated.py"], {})
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)
    monkeypatch.setattr(pool_tools, "_pid_alive", lambda _pid: True)

    assert pool_tools.stop_profile_runner_processes("safe", profile_dir, proc_root=proc_root) == []

    kill.assert_not_called()
    assert not pidfile.exists()


def test_stop_removes_zombie_pidfile_without_signaling(pool_tools, monkeypatch, tmp_path):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    pidfile = profile_dir / ".agency" / "runner.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("4321", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _write_proc_process(
        proc_root,
        4321,
        ["python", "agency_node_runner.py"],
        {"HERMES_PROFILE": "agency-safe"},
    )
    (proc_root / "4321" / "status").write_text("State:\tZ (zombie)\n", encoding="utf-8")
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools.stop_profile_runner_processes("safe", profile_dir, proc_root=proc_root) == []

    kill.assert_not_called()
    assert not pidfile.exists()


@pytest.mark.parametrize(
    ("argv", "env"),
    [
        (["python", "unrelated.py"], {}),
        (["python", "agency_node_runner.py"], {"HERMES_PROFILE": "agency-other"}),
        (
            ["python", "agency_node_runner.py"],
            {"HERMES_PROFILE": "agency-safe", "HERMES_HOME": "/tmp/other-profile"},
        ),
    ],
)
def test_stop_removes_mismatched_pidfile_without_signaling(
    pool_tools, monkeypatch, tmp_path, argv, env
):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    pidfile = profile_dir / ".agency" / "runner.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("4321", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _write_proc_process(proc_root, 4321, argv, env)
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools.stop_profile_runner_processes("safe", profile_dir, proc_root=proc_root) == []

    kill.assert_not_called()
    assert not pidfile.exists()


def _daemon_argv(profile_dir: Path) -> list[str]:
    return [
        str(profile_dir / ".agency" / "bin" / "agentanycastd"),
        f"--grpc-listen=unix://{profile_dir / '.agency' / 'daemon.sock'}",
    ]


def _daemon_env(name: str, profile_dir: Path) -> dict[str, str]:
    return {"HERMES_PROFILE": name, "HERMES_HOME": str(profile_dir)}


def test_stop_terminates_verified_profile_daemon(pool_tools, monkeypatch, tmp_path):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    profile_dir.mkdir(parents=True)
    proc_root = tmp_path / "proc"
    _write_proc_process(
        proc_root, 4321, _daemon_argv(profile_dir), _daemon_env("agency-safe", profile_dir)
    )
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools._stop_profile_daemon_processes(
        "safe", proc_root=proc_root, grace_seconds=0
    ) == [4321]
    assert kill.call_args_list[0] == ((4321, pool_tools.signal.SIGTERM),)


@pytest.mark.parametrize("basename", ["notagentanycastd", "AGENTANYCASTD"])
def test_stop_rejects_lookalike_daemon_executable(pool_tools, monkeypatch, tmp_path, basename):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    profile_dir.mkdir(parents=True)
    proc_root = tmp_path / "proc"
    argv = _daemon_argv(profile_dir)
    argv[0] = str(profile_dir / ".agency" / "bin" / basename)
    _write_proc_process(proc_root, 4321, argv, _daemon_env("agency-safe", profile_dir))
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools._stop_profile_daemon_processes("safe", proc_root=proc_root) == []
    kill.assert_not_called()


@pytest.mark.parametrize(
    "env",
    [
        {"HERMES_PROFILE": "agency-other", "HERMES_HOME": "/tmp/profile"},
        {"HERMES_PROFILE": "agency-safe", "HERMES_HOME": "/tmp/other-profile"},
        {},
    ],
)
def test_stop_rejects_unverified_profile_daemon(pool_tools, monkeypatch, tmp_path, env):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    profile_dir.mkdir(parents=True)
    proc_root = tmp_path / "proc"
    if env.get("HERMES_PROFILE") == "agency-safe":
        env["HERMES_HOME"] = "/tmp/other-profile"
    _write_proc_process(proc_root, 4321, _daemon_argv(profile_dir), env)
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools._stop_profile_daemon_processes("safe", proc_root=proc_root) == []
    kill.assert_not_called()


def test_terminate_ignores_unverified_bare_pid_list(pool_tools, monkeypatch):
    kill = MagicMock()
    monkeypatch.setattr(pool_tools.os, "kill", kill)
    monkeypatch.setattr(pool_tools, "_pid_alive", lambda _pid: True)

    assert pool_tools._terminate_pids([4321], grace_seconds=0) == []

    kill.assert_not_called()


def test_stop_fails_closed_when_pidfds_are_unavailable(pool_tools, monkeypatch, tmp_path):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    pidfile = profile_dir / ".agency" / "runner.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("4321", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _write_proc_process(
        proc_root,
        4321,
        ["python", "agency_node_runner.py"],
        {"HERMES_PROFILE": "agency-safe", "HERMES_HOME": str(profile_dir)},
    )
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)
    monkeypatch.setattr(
        pool_tools.os, "pidfd_open", lambda *_args: (_ for _ in ()).throw(OSError())
    )

    assert pool_tools.stop_profile_runner_processes("safe", proc_root=proc_root) == []

    kill.assert_not_called()
    assert not pidfile.exists()


def test_stop_sends_term_to_verified_pidfile_runner(pool_tools, monkeypatch, tmp_path):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    pidfile = profile_dir / ".agency" / "runner.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("4321", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _write_proc_process(
        proc_root,
        4321,
        ["python", "agency_node_runner.py"],
        {"HERMES_PROFILE": "agency-safe", "HERMES_HOME": str(profile_dir)},
    )
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools.stop_profile_runner_processes(
        "safe", profile_dir, proc_root=proc_root, grace_seconds=0
    ) == [4321]

    assert kill.call_args_list == [
        ((4321, pool_tools.signal.SIGTERM),),
        ((4321, pool_tools.signal.SIGKILL),),
    ]


def test_terminate_skips_kill_when_pid_identity_changes_after_term(
    pool_tools, monkeypatch, tmp_path
):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    proc_root = tmp_path / "proc"
    _write_proc_process(
        proc_root,
        4321,
        ["python", "agency_node_runner.py"],
        {"HERMES_PROFILE": "agency-safe", "HERMES_HOME": str(profile_dir)},
    )
    kill = MagicMock()

    def signal_process(pid, sig):
        kill(pid, sig)
        if sig == pool_tools.signal.SIGTERM:
            _write_proc_process(
                proc_root,
                pid,
                ["python", "unrelated.py"],
                {},
            )

    monkeypatch.setattr(pool_tools.os, "kill", signal_process)

    pool_tools._terminate_pids(
        pool_tools._RunnerPids([4321], "agency-safe", profile_dir, proc_root),
        grace_seconds=0,
    )

    assert kill.call_args_list == [((4321, pool_tools.signal.SIGTERM),)]


def test_terminate_uses_pidfd_when_identity_changes_after_validation(
    pool_tools, monkeypatch, tmp_path
):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    profile_dir.mkdir(parents=True)
    proc_root = tmp_path / "proc"
    _write_proc_process(
        proc_root,
        4321,
        ["python", "agency_node_runner.py"],
        {"HERMES_PROFILE": "agency-safe", "HERMES_HOME": str(profile_dir)},
    )
    sent: list[tuple[int, int]] = []

    monkeypatch.setattr(pool_tools.os, "pidfd_open", lambda _pid, _flags=0: 99)

    def send_pidfd(pidfd, sig, *_args):
        if sig == pool_tools.signal.SIGTERM:
            _write_proc_process(proc_root, 4321, ["python", "unrelated.py"], {})
        sent.append((pidfd, sig))

    monkeypatch.setattr(pool_tools.signal, "pidfd_send_signal", send_pidfd)
    monkeypatch.setattr(pool_tools.os, "close", lambda _pidfd: None)

    pool_tools._terminate_pids(
        pool_tools._RunnerPids([4321], "agency-safe", profile_dir, proc_root),
        grace_seconds=0,
    )

    assert sent == [(99, pool_tools.signal.SIGTERM)]


def test_stop_terminates_verified_proc_discovered_runner(pool_tools, monkeypatch, tmp_path):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    profile_dir.mkdir(parents=True)
    proc_root = tmp_path / "proc"
    _write_proc_process(
        proc_root,
        5678,
        ["python", "agency_node_runner.py"],
        {"HERMES_PROFILE": "agency-safe", "HERMES_HOME": str(profile_dir)},
    )
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools.stop_profile_runner_processes(
        "safe", proc_root=proc_root, grace_seconds=0
    ) == [5678]

    assert kill.call_args_list[0] == ((5678, pool_tools.signal.SIGTERM),)


def test_stop_rejects_non_python_cwd_runner_argument(pool_tools, monkeypatch, tmp_path):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    profile_dir.mkdir(parents=True)
    pidfile = profile_dir / ".agency" / "runner.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("4321", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _write_proc_process(
        proc_root,
        4321,
        ["bash", "-c", "echo", str(pool_tools.NODE_RUNNER)],
        {},
    )
    (proc_root / "4321" / "cwd").symlink_to(profile_dir)
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools.stop_profile_runner_processes("safe", proc_root=proc_root) == []

    kill.assert_not_called()
    assert not pidfile.exists()


def test_stop_rejects_conflicting_environment_despite_valid_cwd_fallback(
    pool_tools, monkeypatch, tmp_path
):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    profile_dir.mkdir(parents=True)
    pidfile = profile_dir / ".agency" / "runner.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("4321", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _write_proc_process(
        proc_root,
        4321,
        ["python", str(pool_tools.NODE_RUNNER)],
        {"HERMES_PROFILE": "agency-other", "HERMES_HOME": str(profile_dir)},
    )
    (proc_root / "4321" / "cwd").symlink_to(profile_dir)
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools.stop_profile_runner_processes("safe", proc_root=proc_root) == []

    kill.assert_not_called()
    assert not pidfile.exists()


def test_stop_rejects_non_python_legacy_runner_path(pool_tools, monkeypatch, tmp_path):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    profile_dir.mkdir(parents=True)
    pidfile = profile_dir / ".agency" / "runner.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("4321", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _write_proc_process(
        proc_root,
        4321,
        [
            "editor",
            "profiles/agency-safe/plugins/hermes-agency/pool/agency_node_runner.py",
        ],
        {},
    )
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools.stop_profile_runner_processes("safe", proc_root=proc_root) == []

    kill.assert_not_called()
    assert not pidfile.exists()


def test_stop_rejects_spoofed_runner_arguments_without_profile_cwd(
    pool_tools, monkeypatch, tmp_path
):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    profile_dir.mkdir(parents=True)
    pidfile = profile_dir / ".agency" / "runner.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("4321", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _write_proc_process(
        proc_root,
        4321,
        [
            "python",
            str(pool_tools.NODE_RUNNER),
            "profiles/agency-safe/plugins/hermes-agency/pool/agency_node_runner.py",
        ],
        {},
    )
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools.stop_profile_runner_processes("safe", proc_root=proc_root) == []

    kill.assert_not_called()
    assert not pidfile.exists()


def test_stop_accepts_profile_cwd_runner_fallback_when_environment_is_unreadable(
    pool_tools, monkeypatch, tmp_path
):
    profile_dir = tmp_path / "profiles" / "agency-safe"
    plugin_link = profile_dir / "plugins" / "hermes-agency"
    plugin_link.parent.mkdir(parents=True)
    plugin_link.symlink_to(pool_tools.PLUGIN_PATH)
    pidfile = profile_dir / ".agency" / "runner.pid"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("4321", encoding="utf-8")
    proc_root = tmp_path / "proc"
    runner_path = plugin_link / "pool" / "agency_node_runner.py"
    _write_proc_process(proc_root, 4321, ["python", str(runner_path)], {})
    (proc_root / "4321" / "environ").unlink()
    (proc_root / "4321" / "cwd").symlink_to(profile_dir)
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools.stop_profile_runner_processes(
        "safe", proc_root=proc_root, grace_seconds=0
    ) == [4321]

    assert kill.call_args_list[0] == ((4321, pool_tools.signal.SIGTERM),)


@pytest.mark.parametrize("name", [None, "agency-", "agency-UPPER", "agency-missing"])
def test_stop_rejects_invalid_or_unknown_profiles_before_signaling(
    pool_tools, monkeypatch, tmp_path, name
):
    kill = MagicMock()
    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools.stop_profile_runner_processes(name) == []

    kill.assert_not_called()


def test_stop_rejects_noncanonical_profile_dir_before_signaling(pool_tools, monkeypatch, tmp_path):
    canonical_profile = tmp_path / "profiles" / "agency-safe"
    canonical_profile.mkdir(parents=True)
    external_profile = tmp_path / "external"
    (external_profile / ".agency").mkdir(parents=True)
    (external_profile / ".agency" / "runner.pid").write_text("4321", encoding="utf-8")
    kill = MagicMock()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    assert pool_tools.stop_profile_runner_processes("safe", external_profile) == []

    kill.assert_not_called()
    assert (external_profile / ".agency" / "runner.pid").exists()
