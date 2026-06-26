"""Tests for the ``hermes agency dashboard`` CLI subcommand.

These tests verify argument parsing, default values, safety guards,
and error handling without actually starting a server.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from argparse import ArgumentParser, Namespace
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
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
    """Load the plugin as a synthetic package and stub Hermes-only imports."""
    for name in list(sys.modules):
        if name == "hermes_plugin" or name.startswith("hermes_plugin."):
            sys.modules.pop(name, None)
    sys.modules.pop("agentanycast", None)

    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()

    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: hermes_home
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli_config = types.ModuleType("hermes_cli.config")
    hermes_cli_config.cfg_get = _nested_cfg_get
    hermes_cli_config.load_config = lambda: {}
    hermes_cli_config.get_config_path = lambda: tmp_path / "config.yaml"
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
        "config",
        "trust",
        "incoming_security",
        "kanban_workspace",
        "registration",
        "bidding",
        "card_builder",
        "context_packet",
        "conversation",
        "departments",
        "task_processor",
        "announcements",
        "kanban_bridge",
        "proactive",
        "node_manager",
        "tools",
        "doctor",
        "cli",
        "dashboard_models",
        "dashboard_security",
        "dashboard_static",
        "dashboard_api",
        "dashboard_server",
    ):
        full_name = f"hermes_plugin.{module_name}"
        sys.modules.pop(full_name, None)
        spec = importlib.util.spec_from_file_location(full_name, PLUGIN_DIR / f"{module_name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full_name, module)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        loaded[module_name] = module
    return types.SimpleNamespace(**loaded, hermes_home=hermes_home, cli_config=hermes_cli_config)


@pytest.fixture()
def agency_parser(plugin_modules):
    """Build an argparse parser with all agency subcommands registered."""
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="agency_command")
    plugin_modules.cli.setup_agency_parser(sub)
    return parser


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDashboardCommandExists:
    """The 'dashboard' subcommand must be registered."""

    def test_dashboard_subparser_registered(self, agency_parser):
        args = agency_parser.parse_args(["dashboard"])
        assert getattr(args, "agency_command", None) == "dashboard"

    def test_dashboard_func_is_cmd_agency(self, agency_parser, plugin_modules):
        args = agency_parser.parse_args(["dashboard"])
        assert args.func is plugin_modules.cli.cmd_agency


class TestDashboardDefaultHostPort:
    """Default host and port values."""

    def test_default_host(self, agency_parser):
        args = agency_parser.parse_args(["dashboard"])
        assert args.host == "127.0.0.1"

    def test_default_port(self, agency_parser):
        args = agency_parser.parse_args(["dashboard"])
        assert args.port == 8765

    def test_custom_host_port(self, agency_parser):
        args = agency_parser.parse_args(["dashboard", "--host", "localhost", "--port", "9999"])
        assert args.host == "localhost"
        assert args.port == 9999


class TestDashboardNoOpen:
    """The --no-open flag suppresses browser launch."""

    def test_no_open_flag(self, agency_parser):
        args = agency_parser.parse_args(["dashboard", "--no-open"])
        assert args.no_open is True

    def test_no_open_default_false(self, agency_parser):
        args = agency_parser.parse_args(["dashboard"])
        assert args.no_open is False


class TestDashboardAllowLan:
    """The --allow-lan flag is parsed."""

    def test_allow_lan_flag(self, agency_parser):
        args = agency_parser.parse_args(["dashboard", "--allow-lan"])
        assert args.allow_lan is True

    def test_allow_lan_default_false(self, agency_parser):
        args = agency_parser.parse_args(["dashboard"])
        assert args.allow_lan is False


class TestDashboardUnsafeHostRejected:
    """Binding to 0.0.0.0 must be refused without --allow-lan."""

    def test_0_0_0_0_rejected_without_allow_lan(self, plugin_modules):
        args = Namespace(
            agency_command="dashboard",
            host="0.0.0.0",
            port=8765,
            no_open=False,
            allow_lan=False,
        )
        with pytest.raises(SystemExit, match="0.0.0.0"):
            plugin_modules.cli.cmd_agency(args)

    def test_0_0_0_0_error_mentions_security(self, plugin_modules):
        args = Namespace(
            agency_command="dashboard",
            host="0.0.0.0",
            port=8765,
            no_open=False,
            allow_lan=False,
        )
        with pytest.raises(SystemExit, match="security"):
            plugin_modules.cli.cmd_agency(args)

    def test_0_0_0_0_allowed_with_lan_flag(self, plugin_modules, monkeypatch):
        """With --allow-lan, 0.0.0.0 should not be rejected (server start is mocked)."""
        started_with = {}

        def fake_start_server(**kwargs):
            started_with.update(kwargs)

        monkeypatch.setattr(plugin_modules.dashboard_server, "start_server", fake_start_server)

        args = Namespace(
            agency_command="dashboard",
            host="0.0.0.0",
            port=8765,
            no_open=True,
            allow_lan=True,
        )
        plugin_modules.cli.cmd_agency(args)
        assert started_with["host"] == "0.0.0.0"


class TestDashboardMissingAssetsMessage:
    """When the frontend dist/ is missing, a helpful error is shown."""

    def test_missing_assets_produces_actionable_error(self, plugin_modules, tmp_path, monkeypatch):
        """Simulate the dashboard_server raising FileNotFoundError for missing dist/."""
        def fake_start_server(**kwargs):
            raise FileNotFoundError(
                "Dashboard frontend build not found. "
                "Run `make dashboard-build` to generate the frontend assets."
            )

        monkeypatch.setattr(
            plugin_modules.dashboard_server, "start_server", fake_start_server
        )

        args = Namespace(
            agency_command="dashboard",
            host="127.0.0.1",
            port=8765,
            no_open=True,
            allow_lan=False,
        )
        with pytest.raises(SystemExit, match="dashboard-build"):
            plugin_modules.cli.cmd_agency(args)
