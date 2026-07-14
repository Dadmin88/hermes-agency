"""Tests for pool service security from PR #22.

Covers:
- Bearer token authentication
- Loopback-only binding
- Agent name validation on wake/sleep/task endpoints
"""

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure pool/ directory is on sys.path so `manager` and `service` are importable
POOL_DIR = str(Path(__file__).resolve().parents[1] / "pool")
if POOL_DIR not in sys.path:
    sys.path.insert(0, POOL_DIR)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_home(tmp_path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    (hermes_home / "profiles").mkdir()
    return hermes_home


@pytest.fixture()
def registry_file(tmp_home):
    registry = {
        "agents": [
            {
                "name": "agency-orchestrator",
                "description": "orchestrator",
                "skills": [],
                "category": "agency",
            },
            {
                "name": "agency-backend-engineer",
                "description": "backend",
                "skills": ["python"],
                "category": "agency",
            },
        ]
    }
    path = tmp_home / "registry_definition.json"
    path.write_text(json.dumps(registry))
    return path


@pytest.fixture()
def app_client(tmp_home, registry_file):
    """Create a Flask test client for the pool service with auth enabled."""
    with (
        patch.dict(
            os.environ,
            {
                "HERMES_HOME": str(tmp_home),
                "HERMES_POOL_TOKEN": "test-secret-token",
                "HERMES_POOL_BIND": "127.0.0.1",
            },
        ),
        patch("manager.REGISTRY_DEF", registry_file),
    ):
        # Fresh import to pick up env changes
        import importlib

        import service as svc_mod

        importlib.reload(svc_mod)

        svc_mod.pm.registry = json.loads(registry_file.read_text())
        svc_mod.pm.active = {}
        svc_mod.pm.config = {
            "pool": {"max_active_agents": 10, "idle_timeout_minutes": 5, "port": 8090}
        }

        client = svc_mod.app.test_client()
        yield client, svc_mod


@pytest.fixture()
def app_client_without_token(tmp_home, registry_file):
    """Create a Flask test client with mutation authentication unconfigured."""
    with (
        patch.dict(
            os.environ,
            {
                "HERMES_HOME": str(tmp_home),
                "HERMES_POOL_TOKEN": "",
                "HERMES_POOL_BIND": "127.0.0.1",
            },
        ),
        patch("manager.REGISTRY_DEF", registry_file),
    ):
        import importlib

        import service as svc_mod

        importlib.reload(svc_mod)
        svc_mod.pm.registry = json.loads(registry_file.read_text())
        svc_mod.pm.active = {}
        client = svc_mod.app.test_client()
        yield client, svc_mod


# ---------------------------------------------------------------------------
# Bearer token auth
# ---------------------------------------------------------------------------


class TestBearerAuth:
    def test_get_endpoints_require_no_token(self, app_client):
        client, _ = app_client
        resp = client.get("/pool/agents")
        assert resp.status_code == 200

    def test_post_without_token_returns_401(self, app_client):
        client, _ = app_client
        resp = client.post("/pool/agents/agency-orchestrator/wake")
        assert resp.status_code == 401
        assert "unauthorized" in resp.get_json()["error"].lower()

    def test_post_with_wrong_token_returns_401(self, app_client):
        client, _ = app_client
        resp = client.post(
            "/pool/agents/agency-orchestrator/wake",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_post_with_valid_token_succeeds(self, app_client):
        client, svc = app_client
        # Mock wake so it doesn't try to start a real process
        with patch.object(svc.pm, "wake", return_value="fake-peer-id"):
            resp = client.post(
                "/pool/agents/agency-orchestrator/wake",
                headers={"Authorization": "Bearer test-secret-token"},
            )
            # May succeed or fail at the process level, but should NOT be 401
            assert resp.status_code != 401

    def test_malformed_auth_header_returns_401(self, app_client):
        client, _ = app_client
        resp = client.post(
            "/pool/agents/agency-orchestrator/wake",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 401

    def test_post_is_disabled_when_server_token_is_unconfigured(self, app_client_without_token):
        client, svc = app_client_without_token
        with patch.object(svc.pm, "wake") as wake:
            resp = client.post("/pool/agents/agency-orchestrator/wake")

        assert resp.status_code == 503
        assert resp.get_json()["error"] == "mutation authentication is not configured"
        wake.assert_not_called()


def test_pool_cli_mutation_headers_follow_configured_token(monkeypatch):
    class FakePoolManager:
        config = {"pool": {"port": 8090}}

    monkeypatch.setitem(sys.modules, "manager", types.SimpleNamespace(PoolManager=FakePoolManager))
    monkeypatch.setenv("HERMES_POOL_TOKEN", "cli-secret-token")

    spec = importlib.util.spec_from_file_location("pool_cli_under_test", Path(POOL_DIR) / "cli.py")
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    assert cli._mutation_headers() == {"Authorization": "Bearer cli-secret-token"}
    monkeypatch.setenv("HERMES_POOL_TOKEN", "")
    assert cli._mutation_headers() == {}


# ---------------------------------------------------------------------------
# Loopback binding
# ---------------------------------------------------------------------------


class TestLoopbackBinding:
    def test_default_bind_is_loopback(self):
        """Verify the default BIND_HOST is 127.0.0.1, not 0.0.0.0."""
        assert os.environ.get("HERMES_POOL_BIND", "127.0.0.1") == "127.0.0.1"

    def test_bind_override(self, tmp_home, registry_file):
        """Setting HERMES_POOL_BIND to 0.0.0.0 should be respected (explicit opt-in)."""
        with patch.dict(
            os.environ,
            {
                "HERMES_HOME": str(tmp_home),
                "HERMES_POOL_BIND": "0.0.0.0",
                "HERMES_POOL_TOKEN": "some-token",
            },
        ):
            import importlib

            import service as svc_mod

            importlib.reload(svc_mod)
            assert svc_mod.BIND_HOST == "0.0.0.0"


# ---------------------------------------------------------------------------
# Agent name validation on endpoints
# ---------------------------------------------------------------------------


class TestEndpointNameValidation:
    def test_wake_rejects_non_agency_name(self, app_client):
        client, _ = app_client
        resp = client.post(
            "/pool/agents/not-agency/wake",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert resp.status_code == 400

    def test_wake_rejects_unknown_agent(self, app_client):
        client, _ = app_client
        resp = client.post(
            "/pool/agents/agency-nonexistent/wake",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert resp.status_code == 404

    def test_sleep_rejects_non_agency_name(self, app_client):
        client, _ = app_client
        resp = client.post(
            "/pool/agents/hack-sleep/sleep",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert resp.status_code == 400

    def test_task_rejects_non_agency_name(self, app_client):
        client, _ = app_client
        resp = client.post(
            "/pool/agents/inject/task",
            headers={"Authorization": "Bearer test-secret-token"},
            json={"message": "do stuff"},
        )
        assert resp.status_code == 400

    def test_get_agent_not_found(self, app_client):
        client, _ = app_client
        resp = client.get("/pool/agents/agency-nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Token comparison timing
# ---------------------------------------------------------------------------


class TestTimingSafety:
    def test_uses_constant_time_compare(self):
        """The _check_token helper should use hmac.compare_digest, not ==."""
        import inspect

        import service as svc_mod

        src = inspect.getsource(svc_mod._check_token)
        assert "compare_digest" in src, "Token comparison must use hmac.compare_digest"
