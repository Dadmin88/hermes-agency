"""Regression tests for the container dashboard exposure defaults."""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_compose_publishes_dashboard_on_loopback_only() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"127.0.0.1:8765:8765"' in compose
    assert '"8765:8765"' not in compose
    assert "HERMES_DASHBOARD_HOST: 127.0.0.1" in compose
    assert 'HERMES_DASHBOARD_ALLOW_LAN: "0"' in compose


def test_docker_entrypoint_defaults_to_localhost_without_lan(monkeypatch) -> None:
    entrypoint_path = REPO_ROOT / "docker" / "run-dashboard.py"
    spec = importlib.util.spec_from_file_location("hermes_docker_run_dashboard", entrypoint_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    started_with: dict[str, object] = {}
    fake_dashboard = types.SimpleNamespace(
        start_server=lambda **kwargs: started_with.update(kwargs)
    )
    monkeypatch.setattr(module, "_load_plugin_module", lambda name: fake_dashboard)
    monkeypatch.delenv("HERMES_DASHBOARD_HOST", raising=False)
    monkeypatch.delenv("HERMES_DASHBOARD_ALLOW_LAN", raising=False)
    monkeypatch.delenv("HERMES_DASHBOARD_PORT", raising=False)
    monkeypatch.delenv("HERMES_DASHBOARD_TOKEN", raising=False)

    module.main()

    assert started_with["host"] == "127.0.0.1"
    assert started_with["port"] == 8765
    assert started_with["allow_lan"] is False
    assert started_with["session_token"] is None
