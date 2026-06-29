import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

POOL_DIR = Path(__file__).resolve().parents[1] / "pool"


def load_manager_module(monkeypatch):
    yaml_stub = types.ModuleType("yaml")
    yaml_stub.safe_load = lambda f: {}
    yaml_stub.dump = lambda data, f: None
    monkeypatch.setitem(sys.modules, "yaml", yaml_stub)
    spec = importlib.util.spec_from_file_location("pool_manager_for_test", POOL_DIR / "manager.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_wake_rejects_unregistered_agency_name_before_profile_creation(monkeypatch):
    manager_module = load_manager_module(monkeypatch)
    pm = manager_module.PoolManager.__new__(manager_module.PoolManager)
    pm.registry = {"agents": [{"name": "agency-known"}]}

    try:
        manager_module.PoolManager.wake(pm, "agency-unknown")
    except ValueError as exc:
        assert str(exc) == "Unknown agency profile: agency-unknown"
    else:
        raise AssertionError("unregistered agency name was accepted")


def test_wake_preserves_existing_prefix_error(monkeypatch):
    manager_module = load_manager_module(monkeypatch)
    pm = manager_module.PoolManager.__new__(manager_module.PoolManager)
    pm.registry = {"agents": [{"name": "agency-known"}]}

    try:
        manager_module.PoolManager.wake(pm, "not-agency")
    except ValueError as exc:
        assert str(exc) == "Only agency-* profiles allowed"
    else:
        raise AssertionError("non-agency profile name was accepted")


def load_service_module(monkeypatch):
    pytest.importorskip("flask")
    manager_stub = types.ModuleType("manager")

    class FakePoolManager:
        def __init__(self):
            self.config = {"pool": {"port": 8090}}
            self.registry = {"agents": []}
            self.wake = Mock(return_value="peer-id")
            self.sleep = Mock(return_value=True)
            self.status = Mock(return_value={})

    manager_stub.PoolManager = FakePoolManager
    monkeypatch.setitem(sys.modules, "manager", manager_stub)
    spec = importlib.util.spec_from_file_location("pool_service_for_test", POOL_DIR / "service.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_pool_post_routes_require_bearer_token(monkeypatch):
    monkeypatch.delenv("HERMES_POOL_TOKEN", raising=False)
    service = load_service_module(monkeypatch)
    client = service.app.test_client()

    response = client.post("/pool/agents/agency-known/wake")

    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}
    service.pm.wake.assert_not_called()


def test_pool_post_routes_accept_configured_bearer_token(monkeypatch):
    monkeypatch.setenv("HERMES_POOL_TOKEN", "test-token")
    service = load_service_module(monkeypatch)
    client = service.app.test_client()

    response = client.post(
        "/pool/agents/agency-known/wake", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "waking", "peer_id": "peer-id"}
    service.pm.wake.assert_called_once_with("agency-known")


def test_run_binds_to_loopback_by_default(monkeypatch):
    service = load_service_module(monkeypatch)
    run_mock = Mock()
    monkeypatch.setattr(service.app, "run", run_mock)

    service.run()

    run_mock.assert_called_once_with(host="127.0.0.1", port=8090, threaded=True)
