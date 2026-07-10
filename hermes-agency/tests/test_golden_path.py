from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _nested_cfg_get(config, *path, default=None):
    value = config
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


@pytest.fixture()
def agency_modules(tmp_path, monkeypatch):
    """Load Hermes Agency as a synthetic package with an isolated Hermes home."""

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
    hermes_cli.config = hermes_cli_config
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_cli_config)

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
    ):
        full_name = f"hermes_plugin.{module_name}"
        spec = importlib.util.spec_from_file_location(full_name, PLUGIN_DIR / f"{module_name}.py")
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full_name, module)
        spec.loader.exec_module(module)
        loaded[module_name] = module

    return types.SimpleNamespace(**loaded, hermes_home=hermes_home)


class _IncomingPart:
    def __init__(self, text: str):
        self.text = text


class _IncomingMessage:
    def __init__(self, text: str):
        self.parts = [_IncomingPart(text)]


class _IncomingTask:
    target_skill_id = ""
    sender_card = None

    def __init__(self, text: str, *, peer_id: str, task_id: str):
        self.task_id = task_id
        self.peer_id = peer_id
        self.messages = [_IncomingMessage(text)]
        self.metadata = {}
        self.completed = None
        self.failed = None
        self.status_updates = []

    async def complete(self, artifacts):
        self.completed = artifacts

    async def fail(self, error):
        self.failed = error

    async def update_status(self, status):
        self.status_updates.append(status)


def _notify_policy(action: str, agent: str) -> dict[str, object]:
    return {
        "action": action,
        "agent": agent,
        "decision": "notify",
        "autonomous": False,
        "notify": True,
        "requires_approval": False,
        "prohibited": False,
    }


def test_golden_path_wakes_trusted_specialist_and_returns_artifact(
    agency_modules, monkeypatch, tmp_path
):
    nm = agency_modules.node_manager
    cfg_mod = agency_modules.config
    orchestrator = importlib.import_module("hermes_plugin.orchestrator")

    sender_cfg = cfg_mod.AgencyConfig(
        relay_security=cfg_mod.RelaySecurityConfig(allowlist=("peer-receiver",)),
        trust=cfg_mod.TrustConfig(store_path=tmp_path / "sender-trust.json"),
        team=cfg_mod.TeamConfig(auto_discover=False, auto_register=False),
        orchestrator=cfg_mod.OrchestratorConfig(enabled=True, agent="agency-orchestrator"),
    )
    receiver_cfg = cfg_mod.AgencyConfig(
        allow_remote_tasks=True,
        relay_security=cfg_mod.RelaySecurityConfig(allowlist=("peer-sender",)),
        trust=cfg_mod.TrustConfig(store_path=tmp_path / "receiver-trust.json"),
        incoming=cfg_mod.IncomingConfig(
            mode="delegation",
            tool_access="none",
            max_iterations=2,
            handler_timeout_seconds=5,
        ),
        team=cfg_mod.TeamConfig(auto_discover=False, auto_register=False),
    )
    agency_modules.trust.store_for_config(sender_cfg).set_trust(
        "peer-receiver", trust_level="full", name="Backend Engineer"
    )
    agency_modules.trust.store_for_config(receiver_cfg).set_trust(
        "peer-sender", trust_level="full", name="Agency Orchestrator"
    )

    active = {"config": sender_cfg, "profile": "agency-orchestrator"}
    monkeypatch.setattr(nm, "get_config", lambda: active["config"])
    monkeypatch.setattr(nm, "current_profile_name", lambda: active["profile"])
    monkeypatch.setattr(orchestrator, "get_config", lambda: sender_cfg)
    monkeypatch.setattr(orchestrator, "current_profile_name", lambda: "agency-orchestrator")
    monkeypatch.setattr(orchestrator, "check_autonomy", _notify_policy)
    monkeypatch.setattr(
        agency_modules.task_processor,
        "_call_delegate_task",
        lambda **_kwargs: "Golden-path artifact: specialist completed the task.",
    )

    board = {"tasks": {}, "updates": [], "comments": [], "pending_review": []}

    def create_task(
        title,
        description="",
        assigned_to=None,
        skills=None,
        dependencies=None,
        metadata=None,
        **_kwargs,
    ):
        task_id = "kanban-golden-1"
        task = board["tasks"].setdefault(
            task_id,
            {
                "id": task_id,
                "title": title,
                "description": description,
                "assigned_to": assigned_to,
                "skills": list(skills or []),
                "dependencies": list(dependencies or []),
                "metadata": dict(metadata or {}),
                "status": "backlog",
                "result": None,
                "error": None,
            },
        )
        return {"available": True, "ok": True, "task_id": task_id, "task": dict(task)}

    def track_delegation(
        message,
        assigned_to=None,
        skills=None,
        a2a_task_id=None,
        kanban_task_id=None,
        metadata=None,
        description=None,
        **_kwargs,
    ):
        task_id = kanban_task_id or "kanban-golden-1"
        if task_id not in board["tasks"]:
            create_task(
                message,
                description=description or message,
                assigned_to=assigned_to,
                skills=skills,
                metadata=metadata,
            )
        board["tasks"][task_id]["a2a_task_id"] = a2a_task_id
        return {
            "available": True,
            "ok": True,
            "task_id": task_id,
            "task": dict(board["tasks"][task_id]),
        }

    def update_task(task_id, status=None, result=None, error=None, **_kwargs):
        task = board["tasks"][task_id]
        if status is not None:
            task["status"] = status
        if result is not None:
            task["result"] = result
        if error is not None:
            task["error"] = error
        board["updates"].append((task_id, status, result, error))
        return {"available": True, "ok": True, "task_id": task_id, "task": dict(task)}

    def add_comment(task_id, body, **_kwargs):
        board["comments"].append((task_id, body))
        return {"available": True, "ok": True, "task_id": task_id}

    monkeypatch.setattr(orchestrator, "kanban_create_task", create_task)
    monkeypatch.setattr(orchestrator, "kanban_update_task", update_task)
    monkeypatch.setattr(nm, "kanban_track_delegation", track_delegation)
    monkeypatch.setattr(nm, "kanban_update_task", update_task)
    monkeypatch.setattr(nm, "kanban_add_comment", add_comment)
    monkeypatch.setattr(
        nm.NodeManager,
        "_ensure_agency_board",
        lambda self, **_kwargs: "agency-engineering",
    )
    monkeypatch.setattr(
        nm.NodeManager,
        "_call_on_agency_board",
        lambda self, _board, fn, *args, **kwargs: fn(*args, **kwargs),
    )
    monkeypatch.setattr(
        nm.NodeManager,
        "_mark_agency_board_pending_review",
        lambda self, board_slug, task_id=None, result=None: board["pending_review"].append(
            (board_slug, task_id, result)
        ),
    )

    receiver = nm.NodeManager()
    receiver._incoming_queue = asyncio.Queue()
    receiver.state.card_name = "Backend Engineer"
    receiver.state.skill_count = 3

    class FakeHandle:
        def __init__(self, incoming):
            self.task_id = incoming.task_id
            self._task = types.SimpleNamespace(
                task_id=incoming.task_id,
                context_id="golden-context",
                status=types.SimpleNamespace(value="completed"),
                target_skill_id=incoming.target_skill_id,
                originator_peer_id="peer-sender",
                artifacts=list(incoming.completed or []),
                metadata=dict(incoming.metadata),
            )

        async def wait(self, timeout=None):
            return self._task

    class LoopbackTransport:
        async def send_task(self, message, peer_id=None, skill=None, metadata=None):
            assert peer_id == "peer-receiver"
            incoming = _IncomingTask(
                message["parts"][0]["text"],
                peer_id="peer-sender",
                task_id="a2a-golden-1",
            )
            incoming.metadata = dict(metadata or {})
            worker = None
            active.update(config=receiver_cfg, profile="agency-backend-engineer")
            try:
                worker = asyncio.create_task(receiver._incoming_worker())
                await receiver._handle_incoming_task(incoming)
                await asyncio.wait_for(receiver._incoming_queue.join(), timeout=3)
            finally:
                if worker is not None:
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
                active.update(config=sender_cfg, profile="agency-orchestrator")
            assert incoming.failed is None
            assert incoming.completed is not None
            return FakeHandle(incoming)

    sender = nm.NodeManager()
    sender._node = LoopbackTransport()
    sender.state.started = True

    async def already_started():
        return sender.state

    sender._ensure_started_impl = already_started
    monkeypatch.setattr(orchestrator, "manager", sender)

    roster_state = {
        "name": "agency-backend-engineer",
        "description": "Backend specialist",
        "skills": ["python", "api-design"],
        "online": False,
        "peer_id": None,
    }
    monkeypatch.setattr(
        orchestrator,
        "_persistent_roster",
        lambda: {"profiles": [dict(roster_state)]},
    )
    wake_calls = []

    def wake_profile(profile_name):
        wake_calls.append(profile_name)
        roster_state["online"] = True
        roster_state["peer_id"] = "peer-receiver"
        return "woke agency-backend-engineer"

    monkeypatch.setattr(orchestrator, "_wake_profile", wake_profile)

    try:
        payload = json.loads(
            orchestrator.orch_route(
                {
                    "task_description": "Build a harmless API health report",
                    "target_agent": "agency-backend-engineer",
                    "wait_seconds": 2,
                    "validation": "Return a concrete artifact.",
                },
                user_task="Prove the Hermes Agency golden path",
                profile="agency-orchestrator",
                session_id="golden-session",
            )
        )
    finally:
        sender.state.started = False
        sender._stop_loop_if_idle()

    assert payload["ok"] is True
    assert payload["task"]["status"] == "completed"
    assert payload["task"]["artifact_text"] == (
        "Golden-path artifact: specialist completed the task."
    )
    assert payload["local_task"]["status"] == "completed"
    assert payload["local_task"]["result_text"] == (
        "Golden-path artifact: specialist completed the task."
    )
    assert wake_calls == ["agency-backend-engineer"]
    assert receiver._incoming_records["a2a-golden-1"].status == "completed"
    assert receiver._incoming_records["a2a-golden-1"].sender_peer_id == "peer-sender"
    assert board["tasks"]["kanban-golden-1"]["status"] == "done"
    assert any(update[1] == "running" for update in board["updates"])
    assert any(update[1] == "done" for update in board["updates"])
    assert board["pending_review"]


def test_golden_path_persists_queue_when_offline_wake_fails(agency_modules, monkeypatch):
    nm = agency_modules.node_manager
    cfg_mod = agency_modules.config
    orchestrator = importlib.import_module("hermes_plugin.orchestrator")
    cfg = cfg_mod.AgencyConfig(
        team=cfg_mod.TeamConfig(auto_discover=False, auto_register=False),
        orchestrator=cfg_mod.OrchestratorConfig(enabled=True, agent="agency-orchestrator"),
    )
    monkeypatch.setattr(orchestrator, "get_config", lambda: cfg)
    monkeypatch.setattr(orchestrator, "current_profile_name", lambda: "agency-orchestrator")
    monkeypatch.setattr(orchestrator, "check_autonomy", _notify_policy)
    monkeypatch.setattr(
        orchestrator,
        "_persistent_roster",
        lambda: {
            "profiles": [
                {
                    "name": "agency-backend-engineer",
                    "description": "Backend specialist",
                    "skills": ["python"],
                    "online": False,
                    "peer_id": None,
                }
            ]
        },
    )
    monkeypatch.setattr(orchestrator, "_wake_profile", lambda _profile: "wake failed")
    queued = []

    def queue_task(profile_name, message, metadata=None, reason=""):
        queued.append((profile_name, message, dict(metadata or {}), reason))
        return {"ok": True, "task": {"id": "offline-q-1", "status": "queued"}}

    monkeypatch.setattr(orchestrator, "_queue_offline_profile_task", queue_task)
    board = {"status": None, "result": None}
    monkeypatch.setattr(
        orchestrator,
        "kanban_create_task",
        lambda *_args, **_kwargs: {
            "available": True,
            "ok": True,
            "task_id": "kanban-queued-1",
            "task": {"id": "kanban-queued-1", "status": "backlog"},
        },
    )

    def update_task(_task_id, status=None, result=None, **_kwargs):
        board["status"] = status
        board["result"] = result
        return {"available": True, "ok": True, "task_id": "kanban-queued-1"}

    monkeypatch.setattr(orchestrator, "kanban_update_task", update_task)
    monkeypatch.setattr(nm, "kanban_update_task", update_task)
    manager = nm.NodeManager()
    monkeypatch.setattr(orchestrator, "manager", manager)

    payload = json.loads(
        orchestrator.orch_route(
            {
                "task_description": "Prepare a harmless backend report",
                "target_agent": "agency-backend-engineer",
            }
        )
    )

    assert payload["ok"] is True
    assert payload["task"]["status"] == "queued"
    assert payload["local_task"]["status"] == "queued"
    assert queued[0][0] == "agency-backend-engineer"
    assert queued[0][3] == "wake failed"
    assert board == {"status": "running", "result": "Queued for offline agent"}
