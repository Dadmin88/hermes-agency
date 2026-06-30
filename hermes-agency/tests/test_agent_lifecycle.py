"""Tests for the agent lifecycle tools: create, disable, enable, prune, reset."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


@pytest.fixture()
def agent_home(tmp_path):
    """Provide an isolated HERMES_HOME for testing."""
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "profiles").mkdir()
    (home / "agency").mkdir()
    return home


@pytest.fixture()
def mock_hermes(agent_home, monkeypatch):
    """Mock hermes_constants and set up the environment."""
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: str(agent_home))
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)
    monkeypatch.setenv("HERMES_HOME", str(agent_home))
    return agent_home


def _import_roster(monkeypatch, agent_home):
    """Import pool.roster with isolated paths."""
    import importlib

    # Ensure fresh import
    for mod_name in list(sys.modules):
        if "hermes_agency" in mod_name or "hermes_plugin" in mod_name:
            monkeypatch.delitem(sys.modules, mod_name, raising=False)

    plugin_dir = Path(__file__).resolve().parents[1]
    package = sys.modules.get("hermes_plugin")
    if package is None:
        package = types.ModuleType("hermes_plugin")
        package.__path__ = [str(plugin_dir)]
        monkeypatch.setitem(sys.modules, "hermes_plugin", package)

    spec = importlib.util.spec_from_file_location(
        "hermes_plugin.pool.roster", plugin_dir / "pool" / "roster.py"
    )
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "hermes_plugin.pool.roster", mod)
    spec.loader.exec_module(mod)
    # Override paths for test isolation
    mod.PROFILES = agent_home / "profiles"
    mod.LEGACY_ROSTER_PATH = None
    return mod


def test_set_and_check_disabled(mock_hermes, monkeypatch):
    roster = _import_roster(monkeypatch, mock_hermes)
    name = "agency-test-agent"
    assert not roster.is_agent_disabled(name)
    roster.set_agent_disabled(name, True, "test")
    assert roster.is_agent_disabled(name)
    roster.set_agent_disabled(name, False)
    assert not roster.is_agent_disabled(name)


def test_update_roster_state_creates_entry(mock_hermes, monkeypatch):
    roster = _import_roster(monkeypatch, mock_hermes)
    roster._update_roster_state("agency-new", {"foo": "bar"})
    persisted = roster._persisted_state_by_name()
    assert persisted["agency-new"]["foo"] == "bar"


def test_update_roster_state_merges(mock_hermes, monkeypatch):
    roster = _import_roster(monkeypatch, mock_hermes)
    roster._update_roster_state("agency-x", {"a": 1})
    roster._update_roster_state("agency-x", {"b": 2})
    persisted = roster._persisted_state_by_name()
    assert persisted["agency-x"]["a"] == 1
    assert persisted["agency-x"]["b"] == 2


def test_agent_created_by_default(mock_hermes, monkeypatch):
    roster = _import_roster(monkeypatch, mock_hermes)
    # Unknown agent not in registry
    assert roster.agent_created_by("agency-unknown") == "default_staff"


def test_set_agent_created_by(mock_hermes, monkeypatch):
    roster = _import_roster(monkeypatch, mock_hermes)
    roster.set_agent_created_by("agency-custom", "lifecycle")
    assert roster.agent_created_by("agency-custom") == "lifecycle"


def test_disable_preserves_other_fields(mock_hermes, monkeypatch):
    roster = _import_roster(monkeypatch, mock_hermes)
    roster._update_roster_state("agency-y", {"peer_id": "abc123"})
    roster.set_agent_disabled("agency-y", True, "test-reason")
    persisted = roster._persisted_state_by_name()
    assert persisted["agency-y"]["peer_id"] == "abc123"
    assert persisted["agency-y"]["disabled"] is True
    assert persisted["agency-y"]["disabled_reason"] == "test-reason"
    assert persisted["agency-y"]["disabled_at"] is not None


def test_enable_clears_disabled_fields(mock_hermes, monkeypatch):
    roster = _import_roster(monkeypatch, mock_hermes)
    roster.set_agent_disabled("agency-z", True, "test")
    assert roster.is_agent_disabled("agency-z")
    roster.set_agent_disabled("agency-z", False)
    persisted = roster._persisted_state_by_name()
    assert persisted["agency-z"]["disabled"] is False
    assert persisted["agency-z"]["disabled_at"] is None
    assert persisted["agency-z"]["disabled_reason"] is None


def _import_pool_tools(monkeypatch, agent_home):
    """Import pool.tools with isolated paths."""
    import importlib

    roster = _import_roster(monkeypatch, agent_home)
    plugin_dir = Path(__file__).resolve().parents[1]

    pool_package = sys.modules.get("hermes_plugin.pool")
    if pool_package is None:
        pool_package = types.ModuleType("hermes_plugin.pool")
        pool_package.__path__ = [str(plugin_dir / "pool")]
        monkeypatch.setitem(sys.modules, "hermes_plugin.pool", pool_package)

    spec = importlib.util.spec_from_file_location(
        "hermes_plugin.pool.tools", plugin_dir / "pool" / "tools.py"
    )
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "hermes_plugin.pool.tools", mod)
    spec.loader.exec_module(mod)
    mod.PROFILES = agent_home / "profiles"
    roster.PROFILES = mod.PROFILES
    return mod


def test_prune_rejects_absolute_path_without_deleting(mock_hermes, monkeypatch, tmp_path):
    import json

    tools = _import_pool_tools(monkeypatch, mock_hermes)
    victim = tmp_path / "victim"
    victim.mkdir()
    marker = victim / "marker.txt"
    marker.write_text("keep", encoding="utf-8")

    result = json.loads(tools.pool_prune_agent(str(victim), force=True))

    assert result == {"ok": False, "error": "name must start with 'agency-'"}
    assert marker.exists()


def test_prune_rejects_traversal_without_deleting(mock_hermes, monkeypatch, tmp_path):
    import json

    tools = _import_pool_tools(monkeypatch, mock_hermes)
    victim = tmp_path / "victim"
    victim.mkdir()
    marker = victim / "marker.txt"
    marker.write_text("keep", encoding="utf-8")

    result = json.loads(tools.pool_prune_agent("agency-../../victim", force=True))

    assert result == {"ok": False, "error": "name must be lowercase alphanumeric with hyphens"}
    assert marker.exists()


def test_disable_and_enable_reject_invalid_names(mock_hermes, monkeypatch):
    import json

    tools = _import_pool_tools(monkeypatch, mock_hermes)

    disable_result = json.loads(tools.pool_disable_agent("../agency-target"))
    enable_result = json.loads(tools.pool_enable_agent("Agency-Target"))

    assert disable_result == {"ok": False, "error": "name must start with 'agency-'"}
    assert enable_result == {"ok": False, "error": "name must start with 'agency-'"}
