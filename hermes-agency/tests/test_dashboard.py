"""Unit tests for the Hermes Agency dashboard modules.

Tests cover:
- dashboard_models.py: Pydantic model instantiation
- dashboard_security.py: token generation, validation, origin checking
- dashboard_static.py: resolve_dashboard_dist, missing assets handling
- dashboard_api.py: router factory, task normalisation helpers
- dashboard_server.py: app creation
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _nested_cfg_get(config, *path, default=None):
    value = config
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


@pytest.fixture()
def plugin_modules(tmp_path, monkeypatch):
    """Load dashboard modules into a synthetic package context."""
    for name in list(sys.modules):
        if name == "hermes_plugin" or name.startswith("hermes_plugin."):
            sys.modules.pop(name, None)

    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()

    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: hermes_home
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli_config = types.ModuleType("hermes_cli.config")
    hermes_cli_config.cfg_get = _nested_cfg_get
    hermes_cli_config.load_config = lambda: {}
    hermes_cli.config = hermes_cli_config
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_cli_config)

    if importlib.util.find_spec("yaml") is None:
        fake_yaml = types.ModuleType("yaml")
        fake_yaml.safe_load = lambda text: {}
        monkeypatch.setitem(sys.modules, "yaml", fake_yaml)

    package = types.ModuleType("hermes_plugin")
    package.__path__ = [str(PLUGIN_DIR)]
    monkeypatch.setitem(sys.modules, "hermes_plugin", package)

    loaded = {}
    for module_name in (
        "dashboard_models",
        "dashboard_security",
        "dashboard_static",
        "dashboard_api",
        "dashboard_server",
    ):
        full_name = f"hermes_plugin.{module_name}"
        sys.modules.pop(full_name, None)
        spec = importlib.util.spec_from_file_location(full_name, PLUGIN_DIR / f"{module_name}.py")
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full_name, module)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        loaded[module_name] = module
    return types.SimpleNamespace(**loaded, hermes_home=hermes_home)


# =========================================================================
# dashboard_models.py
# =========================================================================


class TestDashboardModels:
    """All Pydantic models must be instantiable with minimal args."""

    def test_dashboard_health_minimal(self, plugin_modules):
        m = plugin_modules.dashboard_models
        h = m.DashboardHealth(ok=True)
        assert h.ok is True
        assert h.warnings == []

    def test_dashboard_health_full(self, plugin_modules):
        m = plugin_modules.dashboard_models
        w = m.DashboardWarning(id="w1", label="test", status="warn", message="something")
        h = m.DashboardHealth(
            ok=True,
            profile_home="<home>/test",
            active_profile="agency-orchestrator",
            active_model_set="default",
            daemon_running=True,
            registry_configured=True,
            kanban_available=True,
            incoming_queue_count=3,
            warnings=[w],
        )
        assert len(h.warnings) == 1
        assert h.warnings[0].id == "w1"

    def test_dashboard_warning(self, plugin_modules):
        m = plugin_modules.dashboard_models
        w = m.DashboardWarning(id="w1", label="Test", status="warn", message="msg")
        assert w.id == "w1"
        assert w.remediation is None

    def test_dashboard_doctor_summary(self, plugin_modules):
        m = plugin_modules.dashboard_models
        d = m.DashboardDoctorSummary(summary={"pass": 5, "fail": 1}, exit_code=1)
        assert d.exit_code == 1

    def test_dashboard_agent(self, plugin_modules):
        m = plugin_modules.dashboard_models
        a = m.DashboardAgent(name="agency-orchestrator", skills=["orchestration"])
        assert a.name == "agency-orchestrator"
        assert a.discoverable is False

    def test_dashboard_agent_with_label_and_department(self, plugin_modules):
        m = plugin_modules.dashboard_models
        a = m.DashboardAgent(name="agency-orchestrator", label="Orchestrator", department="core")
        assert a.label == "Orchestrator"
        assert a.department == "core"

    def test_dashboard_department(self, plugin_modules):
        m = plugin_modules.dashboard_models
        d = m.DashboardDepartment(name="Engineering", agent_count=2)
        assert d.name == "Engineering"
        assert d.agents == []

    def test_dashboard_skill(self, plugin_modules):
        m = plugin_modules.dashboard_models
        s = m.DashboardSkill(name="web-search", description="Search the web")
        assert s.agent_count == 0

    def test_dashboard_task_minimal(self, plugin_modules):
        m = plugin_modules.dashboard_models
        t = m.DashboardTask(id="task-1", title="Test task")
        assert t.source == "agency_incoming"
        assert t.linked_kanban_status == "none"

    def test_dashboard_task_all_fields(self, plugin_modules):
        m = plugin_modules.dashboard_models
        t = m.DashboardTask(
            id="task-1",
            source="kanban",
            title="Test",
            status="running",
            created_at=1000.0,
            updated_at=2000.0,
            message_text="hello",
            result_text="done",
            error_text=None,
            kanban_task_id="k-1",
            linked_kanban_status="present",
            available_actions=["complete", "archive"],
        )
        assert t.source == "kanban"
        assert len(t.available_actions) == 2

    def test_dashboard_event(self, plugin_modules):
        m = plugin_modules.dashboard_models
        e = m.DashboardEvent(id="evt-1", message="Something happened", severity="info")
        assert e.related_task_id is None

    def test_dashboard_config(self, plugin_modules):
        m = plugin_modules.dashboard_models
        c = m.DashboardConfig()
        assert c.active_model_set == ""

    def test_dashboard_dispatch_request(self, plugin_modules):
        m = plugin_modules.dashboard_models
        r = m.DashboardDispatchRequest(message="Do something")
        assert r.priority == 0
        assert r.create_kanban_task is True

    def test_dashboard_dispatch_response(self, plugin_modules):
        m = plugin_modules.dashboard_models
        r = m.DashboardDispatchResponse(ok=True, task_id="t-1")
        assert r.ok is True

    def test_dashboard_settings(self, plugin_modules):
        m = plugin_modules.dashboard_models
        s = m.DashboardSettings(host="127.0.0.1", port=8765)
        assert s.local_only is True
        assert s.version == "0.1.0"


# =========================================================================
# dashboard_security.py
# =========================================================================


class TestDashboardSecurity:
    """Token generation, validation, and origin checking."""

    def test_generate_session_token_returns_nonempty_string(self, plugin_modules):
        token = plugin_modules.dashboard_security.generate_session_token()
        assert isinstance(token, str)
        assert len(token) > 0

    def test_generate_session_token_is_random(self, plugin_modules):
        t1 = plugin_modules.dashboard_security.generate_session_token()
        t2 = plugin_modules.dashboard_security.generate_session_token()
        assert t1 != t2

    def test_validate_token_correct(self, plugin_modules):
        sec = plugin_modules.dashboard_security
        token = sec.generate_session_token()
        assert sec.validate_token(token, token) is True

    def test_validate_token_wrong(self, plugin_modules):
        sec = plugin_modules.dashboard_security
        token = sec.generate_session_token()
        assert sec.validate_token("wrong-token", token) is False

    def test_validate_token_empty_candidate(self, plugin_modules):
        sec = plugin_modules.dashboard_security
        token = sec.generate_session_token()
        assert sec.validate_token("", token) is False

    def test_validate_token_empty_expected(self, plugin_modules):
        sec = plugin_modules.dashboard_security
        assert sec.validate_token("something", "") is False

    def test_validate_token_none_candidate(self, plugin_modules):
        sec = plugin_modules.dashboard_security
        token = sec.generate_session_token()
        assert sec.validate_token(None, token) is False

    def test_validate_origin_localhost(self, plugin_modules):
        sec = plugin_modules.dashboard_security
        assert sec.validate_origin("http://localhost:3000", ["http://localhost"]) is True

    def test_validate_origin_127_0_0_1(self, plugin_modules):
        sec = plugin_modules.dashboard_security
        assert sec.validate_origin("http://127.0.0.1:3000", ["http://127.0.0.1"]) is True

    def test_validate_origin_malicious_rejected(self, plugin_modules):
        sec = plugin_modules.dashboard_security
        assert sec.validate_origin("http://evil.com", ["http://localhost"]) is False

    def test_validate_origin_empty_allowed_hosts_rejects(self, plugin_modules):
        sec = plugin_modules.dashboard_security
        assert sec.validate_origin("http://evil.com", []) is False

    def test_validate_origin_none_origin_allows_same_origin(self, plugin_modules):
        """None origin means same-origin request (no Origin header) — allowed."""
        sec = plugin_modules.dashboard_security
        assert sec.validate_origin(None, ["http://localhost"]) is True

    def test_set_and_get_expected_token(self, plugin_modules):
        sec = plugin_modules.dashboard_security
        token = sec.generate_session_token()
        sec._set_expected_token(token)
        assert sec._get_expected_token() == token

    def test_require_token_is_callable(self, plugin_modules):
        """require_token should be a callable (FastAPI dependency)."""
        sec = plugin_modules.dashboard_security
        assert callable(sec.require_token)


# =========================================================================
# dashboard_static.py
# =========================================================================


class TestDashboardStatic:
    """Static asset resolution and serving."""

    def test_resolve_dashboard_dist_returns_path(self, plugin_modules):
        """resolve_dashboard_dist() returns a Path."""
        static = plugin_modules.dashboard_static
        result = static.resolve_dashboard_dist()
        assert isinstance(result, Path)

    def test_resolve_dashboard_dist_ends_with_dist(self, plugin_modules):
        static = plugin_modules.dashboard_static
        result = static.resolve_dashboard_dist()
        assert result.name == "dist"

    def test_static_router_exists(self, plugin_modules):
        """The module-level static_router must exist."""
        static = plugin_modules.dashboard_static
        assert hasattr(static, "static_router")

    def test_inject_token_inserts_meta_tag(self, plugin_modules):
        static = plugin_modules.dashboard_static
        html = "<html><head><title>Test</title></head><body></body></html>"
        result = static._inject_token(html, "my-token")
        assert 'name="hermes-dashboard-token"' in result
        assert 'content="my-token"' in result

    def test_inject_token_no_head_prepends(self, plugin_modules):
        static = plugin_modules.dashboard_static
        html = "<html><body>no head</body></html>"
        result = static._inject_token(html, "token-123")
        assert 'content="token-123"' in result

    def test_missing_build_response_returns_503(self, plugin_modules):
        static = plugin_modules.dashboard_static
        resp = static._missing_build_response()
        assert resp.status_code == 503


# =========================================================================
# dashboard_api.py
# =========================================================================


class TestDashboardAPI:
    """API router factory and helper functions."""

    def test_create_api_router_returns_router(self, plugin_modules):
        fastapi = pytest.importorskip("fastapi")
        api = plugin_modules.dashboard_api
        models = plugin_modules.dashboard_models
        settings = models.DashboardSettings(host="127.0.0.1", port=8765)
        router = api.create_api_router(settings)
        assert isinstance(router, fastapi.APIRouter)

    def test_title_from_message_short(self, plugin_modules):
        api = plugin_modules.dashboard_api
        assert api._title_from_message("Hello world") == "Hello world"

    def test_title_from_message_empty(self, plugin_modules):
        api = plugin_modules.dashboard_api
        assert api._title_from_message("") == "(no message)"

    def test_title_from_message_long_truncated(self, plugin_modules):
        api = plugin_modules.dashboard_api
        long_msg = "x" * 200
        title = api._title_from_message(long_msg)
        assert len(title) <= 80
        assert title.endswith("…")

    def test_title_from_message_multiline_uses_first(self, plugin_modules):
        api = plugin_modules.dashboard_api
        title = api._title_from_message("First line\nSecond line\nThird")
        assert title == "First line"

    def test_check_kanban_link_empty_returns_none(self, plugin_modules):
        api = plugin_modules.dashboard_api
        assert api._check_kanban_link("") == "none"

    def test_agency_actions_processing(self, plugin_modules):
        api = plugin_modules.dashboard_api
        actions = api._agency_actions("processing")
        assert "archive" in actions

    def test_agency_actions_completed(self, plugin_modules):
        api = plugin_modules.dashboard_api
        actions = api._agency_actions("completed")
        assert "archive" in actions

    def test_agency_actions_archived(self, plugin_modules):
        api = plugin_modules.dashboard_api
        actions = api._agency_actions("archived")
        assert actions == []

    def test_kanban_actions_running(self, plugin_modules):
        api = plugin_modules.dashboard_api
        actions = api._kanban_actions("running", "")
        assert "complete" in actions
        assert "archive" in actions

    def test_kanban_actions_done(self, plugin_modules):
        api = plugin_modules.dashboard_api
        actions = api._kanban_actions("done", "")
        assert "complete" not in actions
        assert "retry" in actions
        assert "archive" in actions

    def test_kanban_actions_archived(self, plugin_modules):
        api = plugin_modules.dashboard_api
        actions = api._kanban_actions("archived", "")
        assert actions == []


# =========================================================================
# dashboard_server.py
# =========================================================================


class TestDashboardServer:
    """Server creation."""

    def test_create_app_returns_tuple(self, plugin_modules, monkeypatch):
        """create_app() should return (app, token)."""
        fastapi = pytest.importorskip("fastapi")
        srv = plugin_modules.dashboard_server
        result = srv.create_app()
        assert isinstance(result, tuple)
        assert len(result) == 2
        app, token = result
        assert isinstance(app, fastapi.FastAPI)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_app_stores_token_on_state(self, plugin_modules):
        srv = plugin_modules.dashboard_server
        app, token = srv.create_app()
        assert app.state.dashboard_token == token

    def test_create_app_stores_settings_on_state(self, plugin_modules):
        srv = plugin_modules.dashboard_server
        app, _token = srv.create_app(host="127.0.0.1", port=9999)
        settings = app.state.dashboard_settings
        assert settings.host == "127.0.0.1"
        assert settings.port == 9999

    def test_create_app_has_api_routes(self, plugin_modules):
        srv = plugin_modules.dashboard_server
        app, _token = srv.create_app()
        assert app.routes
        api_router = srv.create_api_router(app.state.dashboard_settings)
        route_paths = {getattr(r, "path", "") for r in api_router.routes}
        assert "/api/health" in route_paths
        assert "/api/agency/moa/status" in route_paths
