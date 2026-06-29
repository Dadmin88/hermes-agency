from __future__ import annotations

import importlib.util
import sys
import threading
import types
from pathlib import Path

import pytest

POOL_MANAGER_PATH = Path(__file__).resolve().parents[1] / "pool" / "manager.py"


def load_pool_manager_module(monkeypatch):
    fake_yaml = types.ModuleType("yaml")
    fake_yaml.safe_load = lambda stream: {}
    monkeypatch.setitem(sys.modules, "yaml", fake_yaml)
    spec = importlib.util.spec_from_file_location("pool_manager_under_test", POOL_MANAGER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_manager(module, registry):
    manager = module.PoolManager.__new__(module.PoolManager)
    manager.config = {"pool": {"max_active_agents": 10, "idle_timeout_minutes": 5}}
    manager.registry = registry
    manager.allowed_agents = manager._registered_agent_names(registry)
    manager.active = {}
    manager.persistent_agents = {"agency-orchestrator"}
    manager.lock = threading.RLock()
    return manager


def test_wake_rejects_unregistered_agency_profile_before_startup(monkeypatch):
    module = load_pool_manager_module(monkeypatch)
    manager = make_manager(module, {"agents": [{"name": "agency-known"}]})

    monkeypatch.setattr(
        manager,
        "_ensure_profile",
        lambda name: pytest.fail("unregistered profiles must not create local profile state"),
    )
    monkeypatch.setattr(
        manager,
        "_start_cli_node",
        lambda name: pytest.fail("unregistered profiles must not start CLI nodes"),
    )
    monkeypatch.setattr(
        manager,
        "_start_runner_node",
        lambda name: pytest.fail("unregistered profiles must not start runner subprocesses"),
    )

    with pytest.raises(ValueError, match="Unknown agency profile: agency-attacker-poc"):
        manager.wake("agency-attacker-poc")


def test_wake_allows_registered_agency_profile(monkeypatch):
    module = load_pool_manager_module(monkeypatch)
    manager = make_manager(module, {"agents": [{"name": "agency-known"}]})

    monkeypatch.setattr(manager, "_ensure_profile", lambda name: Path("/tmp/profile"))
    monkeypatch.setattr(manager, "_start_cli_node", lambda name: (None, "", False))
    monkeypatch.setattr(
        manager,
        "_start_runner_node",
        lambda name: ("12D3KooWRegisteredPeer", None, "started"),
    )

    assert manager.wake("agency-known") == "12D3KooWRegisteredPeer"
