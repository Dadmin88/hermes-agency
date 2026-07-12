"""Regression tests for safe public pool lifecycle profile validation."""

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
    package = types.ModuleType("profile_validation_plugin")
    package.__path__ = [str(PLUGIN_DIR)]
    monkeypatch.setitem(sys.modules, package.__name__, package)

    pool_package = types.ModuleType("profile_validation_plugin.pool")
    pool_package.__path__ = [str(PLUGIN_DIR / "pool")]
    monkeypatch.setitem(sys.modules, pool_package.__name__, pool_package)

    roster = types.ModuleType("profile_validation_plugin.pool.roster")
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
        "profile_validation_plugin.pool.tools", PLUGIN_DIR / "pool" / "tools.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("entrypoint", ["pool_wake", "pool_sleep", "pool_send"])
@pytest.mark.parametrize(
    "name",
    [
        None,
        "agency-",
        "agency-.*",
        "agency-x/../../other",
        "agency-UPPER",
        "agency-" + ("a" * 59),
    ],
)
def test_lifecycle_operations_reject_invalid_names_before_side_effects(
    pool_tools, monkeypatch, tmp_path, entrypoint, name
):
    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    run, popen, kill = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(pool_tools.subprocess, "run", run)
    monkeypatch.setattr(pool_tools.subprocess, "Popen", popen)
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    result = (
        pool_tools.pool_send(name, "work")
        if entrypoint == "pool_send"
        else getattr(pool_tools, entrypoint)(name)
    )

    assert result.startswith("Error:")
    run.assert_not_called()
    popen.assert_not_called()
    kill.assert_not_called()
    pool_tools.record_wake_attempt.assert_not_called()
    pool_tools.queue_offline_task.assert_not_called()
    pool_tools.ensure_profile_plugins.assert_not_called()
    pool_tools.find_agent.assert_not_called()
    pool_tools.save_roster.assert_not_called()
    pool_tools.update_agent_status.assert_not_called()


@pytest.mark.parametrize("entrypoint", ["pool_wake", "pool_sleep"])
def test_wake_and_sleep_reject_unknown_profiles_before_side_effects(
    pool_tools, monkeypatch, tmp_path, entrypoint
):
    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    run, popen, kill = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(pool_tools.subprocess, "run", run)
    monkeypatch.setattr(pool_tools.subprocess, "Popen", popen)
    monkeypatch.setattr(pool_tools.os, "kill", kill)

    result = getattr(pool_tools, entrypoint)("agency-unknown")

    assert result == "Error: profile agency-unknown not found"
    run.assert_not_called()
    popen.assert_not_called()
    kill.assert_not_called()
    pool_tools.record_wake_attempt.assert_not_called()
    pool_tools.queue_offline_task.assert_not_called()
    pool_tools.ensure_profile_plugins.assert_not_called()
    pool_tools.find_agent.assert_not_called()
    pool_tools.save_roster.assert_not_called()
    pool_tools.update_agent_status.assert_not_called()


def test_resolver_normalizes_short_name_to_existing_profile(pool_tools, monkeypatch, tmp_path):
    profile = tmp_path / "profiles" / "agency-safe"
    profile.mkdir(parents=True)
    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")

    assert pool_tools._resolve_existing_pool_profile("safe") == (
        "agency-safe",
        profile.resolve(),
    )


def test_send_normalizes_short_name_without_requiring_profile_directory(pool_tools):
    pool_tools.find_agent.return_value = None

    assert pool_tools.pool_send("safe", "work") == "Error: agent 'agency-safe' not found in roster"
    pool_tools.find_agent.assert_called_once_with("agency-safe")
    pool_tools.queue_offline_task.assert_not_called()


def test_wake_normalizes_short_name_before_existing_runner_check(pool_tools, monkeypatch, tmp_path):
    profile = tmp_path / "profiles" / "agency-safe"
    agency_dir = profile / ".agency"
    agency_dir.mkdir(parents=True)
    (agency_dir / "daemon.sock").touch()
    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools, "_read_runner_pid", lambda _profile: 1234)
    monkeypatch.setattr(pool_tools, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(pool_tools, "_resolve_runner_peer_id", lambda *_args: "peer-safe")
    pool_tools.ensure_profile_plugins.return_value = {}
    popen = MagicMock()
    monkeypatch.setattr(pool_tools.subprocess, "Popen", popen)

    assert pool_tools.pool_wake("safe") == "agency-safe is already online — peer_id: peer-safe..."
    pool_tools.ensure_profile_plugins.assert_called_once_with()
    pool_tools.update_agent_status.assert_called_once_with(
        "agency-safe", online=True, peer_id="peer-safe"
    )
    popen.assert_not_called()


def test_sleep_normalizes_short_name_and_uses_canonical_profile_path(
    pool_tools, monkeypatch, tmp_path
):
    profile = tmp_path / "profiles" / "agency-safe"
    (profile / ".agency").mkdir(parents=True)
    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    stop_runner = MagicMock()
    monkeypatch.setattr(pool_tools, "stop_profile_runner_processes", stop_runner)
    monkeypatch.setattr(pool_tools, "_stop_profile_daemon_processes", MagicMock())
    monkeypatch.setattr(pool_tools.subprocess, "run", MagicMock())
    popen = MagicMock()
    monkeypatch.setattr(pool_tools.subprocess, "Popen", popen)
    monkeypatch.setattr(pool_tools.time, "sleep", lambda _seconds: None)

    assert pool_tools.pool_sleep("safe") == "agency-safe offline"
    stop_runner.assert_called_once_with("agency-safe", profile.resolve())
    popen.assert_not_called()
