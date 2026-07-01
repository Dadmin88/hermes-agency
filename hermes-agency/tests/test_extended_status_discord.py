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
    kanban.list_tasks = lambda filters=None: {
        "available": True,
        "ok": True,
        "tasks": [],
    }
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


def test_discord_parse_task_message(monkeypatch):
    discord_intake = _load_agency_module(monkeypatch, "discord_intake")

    assert (
        discord_intake._parse_task_message(
            {"content": "!agency build the dashboard"}, prefix="!agency"
        )
        == "build the dashboard"
    )
    assert (
        discord_intake._parse_task_message(
            {"content": "!agency task wire discord"}, prefix="!agency"
        )
        == "wire discord"
    )
    assert discord_intake._parse_task_message({"content": "hello"}, prefix="!agency") is None
    assert (
        discord_intake._parse_task_message({"content": "!agency status"}, prefix="!agency") is None
    )


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
            "doctor": {
                "exit_code": 0,
                "summary": {"pass": 17, "warn": 0, "fail": 0, "na": 0},
            },
            "models": {
                "ok": True,
                "active_set": "economic",
                "profiles_checked": 84,
                "drift": 0,
                "missing": 0,
            },
            "gpt_bridge": {"total": 0, "counts": {}},
            "roster": {
                "ok": True,
                "online": 1,
                "total": 84,
                "offline": 83,
                "recently_seen_24h": 1,
            },
            "kanban": {
                "ok": True,
                "task_count": 1,
                "status_counts": {"done": 1},
                "throughput_24h": {
                    "created": 1,
                    "completed": 1,
                    "failed_or_blocked_completed": 0,
                },
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
    assert "department boards" in rendered
    assert "Engineering" in rendered


def test_discord_poll_requires_sender_allowlist(monkeypatch, tmp_path):
    discord_intake = _load_agency_module(monkeypatch, "discord_intake")
    monkeypatch.delenv("HERMES_AGENCY_DISCORD_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("HERMES_AGENCY_DISCORD_ALLOWED_ROLE_IDS", raising=False)
    monkeypatch.setenv("HERMES_AGENCY_DISCORD_INTAKE_STATE", str(tmp_path / "discord_state.json"))
    monkeypatch.setattr(
        discord_intake,
        "fetch_recent_messages",
        lambda limit=25: [
            {
                "id": "msg-1",
                "content": "!agency task do unauthorized work",
                "author": {"id": "user-1", "username": "mallory", "bot": False},
            }
        ],
    )

    result = discord_intake.poll_discord_tasks(dry_run=True)

    assert result["authorization_required"] is True
    assert result["allowed_user_count"] == 0
    assert result["allowed_role_count"] == 0
    assert result["queued_count"] == 0
    assert result["skipped_count"] == 1


def test_discord_poll_accepts_allowed_user(monkeypatch, tmp_path):
    discord_intake = _load_agency_module(monkeypatch, "discord_intake")
    monkeypatch.setenv("HERMES_AGENCY_DISCORD_ALLOWED_USER_IDS", "user-1")
    monkeypatch.setenv("HERMES_AGENCY_DISCORD_INTAKE_STATE", str(tmp_path / "discord_state.json"))
    monkeypatch.setattr(
        discord_intake,
        "fetch_recent_messages",
        lambda limit=25: [
            {
                "id": "msg-1",
                "content": "!agency task do authorized work",
                "author": {"id": "user-1", "username": "alice", "bot": False},
            }
        ],
    )

    result = discord_intake.poll_discord_tasks(dry_run=True)

    assert result["allowed_user_count"] == 1
    assert result["queued_count"] == 1
    assert result["queued"][0]["task_text"] == "do authorized work"


def test_discord_poll_accepts_allowed_role(monkeypatch, tmp_path):
    discord_intake = _load_agency_module(monkeypatch, "discord_intake")
    monkeypatch.setenv("HERMES_AGENCY_DISCORD_ALLOWED_ROLE_IDS", "role-1")
    monkeypatch.setenv("HERMES_AGENCY_DISCORD_INTAKE_STATE", str(tmp_path / "discord_state.json"))
    monkeypatch.setattr(
        discord_intake,
        "fetch_recent_messages",
        lambda limit=25: [
            {
                "id": "msg-1",
                "content": "!agency task do role-authorized work",
                "author": {"id": "user-2", "username": "bob", "bot": False},
                "member": {"roles": ["role-1"]},
            }
        ],
    )

    result = discord_intake.poll_discord_tasks(dry_run=True)

    assert result["allowed_role_count"] == 1
    assert result["queued_count"] == 1
    assert result["queued"][0]["task_text"] == "do role-authorized work"
