from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _install_stubs(monkeypatch) -> None:
    package = sys.modules.get("hermes_plugin")
    if package is None:
        package = types.ModuleType("hermes_plugin")
        package.__path__ = [str(PLUGIN_DIR)]
        monkeypatch.setitem(sys.modules, "hermes_plugin", package)

    doctor = types.ModuleType("hermes_plugin.doctor")

    class Report:
        exit_code = 0
        summary = {"pass": 1, "warn": 0, "fail": 0, "na": 0}

    doctor.run_doctor = lambda: Report()
    monkeypatch.setitem(sys.modules, "hermes_plugin.doctor", doctor)

    kanban = types.ModuleType("hermes_plugin.kanban_bridge")
    kanban.list_tasks = lambda filters=None: {"available": True, "ok": True, "tasks": []}
    kanban.create_task = lambda **kwargs: {
        "available": True,
        "ok": True,
        "task_id": "task-1",
        "kwargs": kwargs,
    }
    monkeypatch.setitem(sys.modules, "hermes_plugin.kanban_bridge", kanban)

    node_manager = types.ModuleType("hermes_plugin.node_manager")

    class Manager:
        def info(self):
            return {}

        def list_peers_sync(self):
            return []

        def create_orchestrator_task(self, description, **kwargs):
            return {"task_id": "orch-1", "description": description, **kwargs}

    node_manager.manager = Manager()
    monkeypatch.setitem(sys.modules, "hermes_plugin.node_manager", node_manager)


def _load_agency_module(monkeypatch, module_name: str):
    _install_stubs(monkeypatch)
    full_name = f"hermes_plugin.{module_name}"
    spec = importlib.util.spec_from_file_location(full_name, PLUGIN_DIR / f"{module_name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, full_name, module)
    spec.loader.exec_module(module)
    return module


def test_extended_status_renderer_minimal(monkeypatch):
    extended_status = _load_agency_module(monkeypatch, "extended_status")
    rendered = extended_status.render_extended_status(
        {
            "node": {
                "started": True,
                "peer_id": "peer-1",
                "card_name": "Orchestrator",
                "uptime_seconds": 65,
                "serve_task_running": True,
                "connected_peers": 2,
                "incoming": {
                    "records": 1,
                    "queued": 0,
                    "processing": 0,
                    "completed": 1,
                    "failed": 0,
                },
            },
            "doctor": {"exit_code": 0, "summary": {"pass": 17, "warn": 0, "fail": 0, "na": 0}},
            "models": {
                "ok": True,
                "active_set": "economic",
                "profiles_checked": 84,
                "drift": 0,
                "missing": 0,
                "unchanged": 84,
            },
            "roster": {"ok": True, "online": 1, "total": 84, "offline": 83, "recently_seen_24h": 1},
            "kanban": {
                "ok": True,
                "task_count": 1,
                "status_counts": {"done": 1},
                "throughput_24h": {"created": 1, "completed": 1, "failed_or_blocked_completed": 0},
                "departments": {
                    "Engineering": {
                        "board": "agency-engineering",
                        "total": 1,
                        "active": 0,
                        "status_counts": {"done": 1},
                    }
                },
            },
        }
    )

    assert "Hermes Agency extended status" in rendered
    assert "models: active=economic" in rendered
    assert "missing=0 drift=0 unchanged=84" in rendered
    assert "department boards" in rendered
    assert "Engineering" in rendered


def test_model_status_counts_drift_missing_and_unchanged(monkeypatch):
    extended_status = _load_agency_module(monkeypatch, "extended_status")

    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli.__path__ = []
    hermes_config = types.ModuleType("hermes_cli.config")
    setattr(
        hermes_config,
        "load_config",
        lambda: {"agency": {"models": {"active_set": "test"}}},
    )
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_config)

    model_sets = types.ModuleType("hermes_plugin.model_sets")
    setattr(model_sets, "active_model_set_name", lambda config: "test")
    setattr(model_sets, "load_model_set", lambda name: name)
    monkeypatch.setitem(sys.modules, "hermes_plugin.model_sets", model_sets)

    writer = types.ModuleType("hermes_plugin.profile_config_writer")
    setattr(
        writer,
        "plan_model_set",
        lambda model_set: [
            types.SimpleNamespace(status="drift"),
            types.SimpleNamespace(status="missing"),
            types.SimpleNamespace(status="unchanged"),
            types.SimpleNamespace(status="unchanged"),
        ],
    )
    monkeypatch.setitem(sys.modules, "hermes_plugin.profile_config_writer", writer)

    assert extended_status._model_status() == {
        "ok": True,
        "active_set": "test",
        "profiles_checked": 4,
        "drift": 1,
        "missing": 1,
        "unchanged": 2,
        "status_counts": {"drift": 1, "missing": 1, "unchanged": 2},
    }
