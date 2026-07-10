"""End-to-end coverage for Hermes Agency's Keryx transport wiring."""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "hermes_plugin"
DAEMON_ENDPOINT = "127.0.0.1:50051"


def _cfg_get(config: dict[str, Any], *path: str, default: Any = None) -> Any:
    value: Any = config
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _clear_plugin_modules() -> None:
    for name in list(sys.modules):
        if name == PACKAGE_NAME or name.startswith(f"{PACKAGE_NAME}."):
            sys.modules.pop(name, None)


def _load_plugin_module(module_name: str):
    module_path = PLUGIN_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.{module_name}", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{PACKAGE_NAME}.{module_name}"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def fake_keryx_sdk(monkeypatch):
    """Install an in-memory Keryx SDK with the public imports Agency needs."""

    @dataclass
    class Skill:
        id: str
        description: str

        def to_dict(self) -> dict[str, str]:
            return {"id": self.id, "description": self.description}

    @dataclass
    class AgentCard:
        name: str
        description: str
        version: str
        skills: list[Skill]

        def to_dict(self) -> dict[str, Any]:
            return {
                "name": self.name,
                "description": self.description,
                "version": self.version,
                "skills": [skill.to_dict() for skill in self.skills],
            }

    class KeryxNode:
        instances: list[KeryxNode] = []

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.card = kwargs["card"]
            self.peer_id = "peer-keryx-e2e"
            self._task_handlers: list[Any] = []
            self.register_calls: list[dict[str, Any]] = []
            self.started = False
            self.stopped = False
            KeryxNode.instances.append(self)

        async def start(self) -> None:
            self.started = True

        def on_task(self, handler: Any) -> None:
            self._task_handlers.append(handler)

        async def serve_forever(self) -> None:
            await asyncio.Future()

        async def stop(self) -> None:
            self.stopped = True

        async def register_skills(self, card: Any, **kwargs: Any) -> dict[str, Any]:
            self.register_calls.append({"card": card, **kwargs})
            return {"accepted": True, "peer_id": self.peer_id}

    keryx_module = types.ModuleType("keryx")
    keryx_module.__spec__ = importlib.machinery.ModuleSpec("keryx", loader=None, is_package=True)
    keryx_module.__path__ = []
    setattr(keryx_module, "KeryxNode", KeryxNode)
    setattr(keryx_module, "AgentCard", AgentCard)
    setattr(keryx_module, "Skill", Skill)
    setattr(keryx_module, "peer_id_to_did_key", lambda peer_id: f"did:key:{peer_id}")

    node_module = types.ModuleType("keryx.node")
    node_module.__spec__ = importlib.machinery.ModuleSpec("keryx.node", loader=None)
    setattr(node_module, "KeryxNode", KeryxNode)

    monkeypatch.setitem(sys.modules, "keryx", keryx_module)
    monkeypatch.setitem(sys.modules, "keryx.node", node_module)
    return {"KeryxNode": KeryxNode, "AgentCard": AgentCard, "Skill": Skill}


@pytest.fixture()
def keryx_config_data(tmp_path: Path) -> dict[str, Any]:
    return {
        "agency": {
            "enabled": True,
            "transport_backend": "keryx",
            "home": str(tmp_path / "agency-home"),
            "keryx": {
                "daemon_endpoint": DAEMON_ENDPOINT,
                "registry_endpoint": "127.0.0.1:50052",
                "relay_endpoint": "memory://relay",
                "relay_config": {"mode": "test"},
                "worker_id": "pytest-worker",
                "default_lease_duration_ms": 120_000,
                "request_timeout_ms": 5_000,
            },
            "team": {
                "auto_register": False,
                "auto_discover": False,
                "tenant": "default",
            },
            "incoming_max_queue_size": 5,
        }
    }


@pytest.fixture()
def plugin_base(monkeypatch, tmp_path: Path, keryx_config_data: dict[str, Any]):
    _clear_plugin_modules()

    profile_home = tmp_path / "profile-home"
    profile_home.mkdir()

    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: profile_home)
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli_config = types.ModuleType("hermes_cli.config")
    setattr(hermes_cli_config, "cfg_get", _cfg_get)
    setattr(hermes_cli_config, "load_config", lambda: keryx_config_data)
    setattr(hermes_cli, "config", hermes_cli_config)
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_cli_config)

    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(PLUGIN_DIR)]
    monkeypatch.setitem(sys.modules, PACKAGE_NAME, package)

    return {"profile_home": profile_home, "config_data": keryx_config_data}


@pytest.fixture()
def plugin_tools(plugin_base, fake_keryx_sdk, monkeypatch):
    # Keep this fixture focused on tool-level transport functions; node lifecycle
    # is loaded separately in the daemon-connection test below.
    autonomous_tools = types.ModuleType(f"{PACKAGE_NAME}.autonomous_tools")
    setattr(autonomous_tools, "AUTONOMOUS_TOOLS", [])
    monkeypatch.setitem(sys.modules, f"{PACKAGE_NAME}.autonomous_tools", autonomous_tools)

    card_builder = types.ModuleType(f"{PACKAGE_NAME}.card_builder")
    setattr(card_builder, "build_card", lambda *args, **kwargs: None)
    setattr(card_builder, "card_to_dict", lambda card: {})
    monkeypatch.setitem(sys.modules, f"{PACKAGE_NAME}.card_builder", card_builder)

    node_manager = types.ModuleType(f"{PACKAGE_NAME}.node_manager")
    setattr(node_manager, "manager", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, f"{PACKAGE_NAME}.node_manager", node_manager)

    config_module = _load_plugin_module("config")
    tools_module = _load_plugin_module("tools")
    return {"config": config_module, "tools": tools_module}


@pytest.fixture()
def node_manager_module(plugin_base, fake_keryx_sdk):
    return _load_plugin_module("node_manager")


def test_transport_selection_returns_keryx(plugin_tools):
    assert plugin_tools["tools"].get_transport_backend() == "keryx"


def test_keryx_sdk_availability_check(plugin_tools):
    assert plugin_tools["tools"].check_keryx_available() is True


def test_keryx_sdk_import_chain(fake_keryx_sdk):
    from keryx import AgentCard, KeryxNode, Skill

    assert KeryxNode is fake_keryx_sdk["KeryxNode"]
    assert AgentCard is fake_keryx_sdk["AgentCard"]
    assert Skill is fake_keryx_sdk["Skill"]


def test_config_loading_reads_keryx_transport(plugin_tools):
    cfg = plugin_tools["config"].get_config()

    assert cfg.transport_backend == "keryx"
    assert cfg.keryx.daemon_endpoint == DAEMON_ENDPOINT
    assert cfg.keryx.registry_endpoint == "127.0.0.1:50052"
    assert cfg.keryx.relay_endpoint == "memory://relay"
    assert cfg.keryx.relay_config == {"mode": "test"}
    assert cfg.keryx.worker_id == "pytest-worker"
    assert cfg.keryx.default_lease_duration_ms == 120_000
    assert cfg.keryx.request_timeout_ms == 5_000
    assert cfg.team.auto_register is False
    assert cfg.team.auto_discover is False


def test_keryx_config_as_dict_redacts_secret_relay_config_values(plugin_tools):
    cfg_mod = plugin_tools["config"]
    cfg = cfg_mod.KeryxTransportConfig(
        relay_config={
            "mode": "test",
            "authorization": "Bearer SECRET_TOKEN_12345",
            "api-key": "APIKEY-SECRET-67890",
            "nested": {
                "password": "NESTED-PASS",
                "safe": "visible",
                "items": [{"client_secret": "CLIENT-SECRET"}],
            },
        }
    )

    data = cfg.as_dict()

    assert data["relay_config"] == {
        "mode": "test",
        "authorization": "<redacted>",
        "api-key": "<redacted>",
        "nested": {
            "password": "<redacted>",
            "safe": "visible",
            "items": [{"client_secret": "<redacted>"}],
        },
    }
    assert cfg.relay_config["authorization"] == "Bearer SECRET_TOKEN_12345"


def test_config_loading_accepts_keryx_relay_registry_env(plugin_tools, monkeypatch):
    monkeypatch.delenv("HERMES_KERYX_REGISTRY_ENDPOINT", raising=False)
    monkeypatch.delenv("KERYX_REGISTRY_ENDPOINT", raising=False)
    plugin_tools["config"].load_config = lambda: {
        "agency": {
            "transport_backend": "keryx",
            "keryx": {"daemon_endpoint": DAEMON_ENDPOINT},
        }
    }
    monkeypatch.setenv("HERMES_KERYX_RELAY_REGISTRY_ENDPOINT", "http://127.0.0.1:51053")

    cfg = plugin_tools["config"].get_config()

    assert cfg.keryx.registry_endpoint == "http://127.0.0.1:51053"


@pytest.mark.asyncio
async def test_mock_daemon_connection_uses_keryx_transport(node_manager_module, fake_keryx_sdk):
    manager = node_manager_module.NodeManager()

    # This test verifies transport startup/constructor wiring only; do not start
    # queue workers or perform live registry/team discovery.
    manager._ensure_incoming_runtime = lambda cfg: None
    manager._requeue_persisted_incoming_tasks = lambda: 0

    async def refresh_team_context(*, force: bool = False) -> None:
        return None

    manager._refresh_team_context_impl = refresh_team_context

    try:
        state = await manager._start_impl()

        assert state.started is True
        assert state.error is None
        assert state.peer_id == "peer-keryx-e2e"
        assert state.did_key == "did:key:peer-keryx-e2e"
        assert state.config.transport_backend == "keryx"

        instances = fake_keryx_sdk["KeryxNode"].instances
        assert len(instances) == 1
        node = instances[0]
        assert node.started is True
        assert len(node._task_handlers) == 1
        assert node.kwargs["daemon_addr"] == DAEMON_ENDPOINT
        assert node.kwargs["registry_endpoint"] == "127.0.0.1:50052"
        assert node.kwargs["transport"] == "keryx"
        assert node.kwargs["namespace"] == "default"
        assert node.kwargs["relay"] == "memory://relay"
        assert node.kwargs["home"] == state.config.home
        assert node.kwargs["card"].name == "profile-home"
    finally:
        await manager._stop_impl()


@pytest.mark.asyncio
async def test_keryx_auto_register_starts_registry_refresh_loop(
    plugin_base, node_manager_module, fake_keryx_sdk
):
    plugin_base["config_data"]["agency"]["team"]["auto_register"] = True
    manager = node_manager_module.NodeManager()

    # This test verifies Keryx registry refresh lifecycle wiring only; avoid
    # queue workers and live team discovery.
    manager._ensure_incoming_runtime = lambda cfg: None
    manager._requeue_persisted_incoming_tasks = lambda: 0

    async def refresh_team_context(*, force: bool = False) -> None:
        return None

    manager._refresh_team_context_impl = refresh_team_context

    try:
        state = await manager._start_impl()

        assert state.started is True
        assert state.registration_healthy is True
        assert manager._registry_reregister_task is not None
        assert not manager._registry_reregister_task.done()

        node = fake_keryx_sdk["KeryxNode"].instances[-1]
        assert node.register_calls
        assert node.register_calls[0]["ttl_seconds"] == 60
    finally:
        await manager._stop_impl()


@pytest.mark.asyncio
async def test_startup_team_refresh_timeout_does_not_block_node_start(
    node_manager_module, fake_keryx_sdk, monkeypatch
):
    manager = node_manager_module.NodeManager()

    manager._ensure_incoming_runtime = lambda cfg: None
    manager._requeue_persisted_incoming_tasks = lambda: 0
    monkeypatch.setattr(node_manager_module, "STARTUP_TEAM_REFRESH_TIMEOUT_SECONDS", 0.01)

    async def refresh_team_context(*, force: bool = False) -> None:
        await asyncio.sleep(60)

    manager._refresh_team_context_impl = refresh_team_context

    try:
        state = await manager._start_impl()

        assert state.started is True
        assert state.error is None
        assert state.peer_id == "peer-keryx-e2e"
        assert state.team_last_error == (
            "startup team context refresh timed out; continuing node startup"
        )
    finally:
        await manager._stop_impl()


@pytest.mark.asyncio
async def test_keryx_client_discover_falls_back_when_skill_index_is_empty():
    from keryx import client as keryx_client

    daemon_client_cls = keryx_client.DaemonClient
    registry_pb2 = keryx_client.registry_pb2

    class RegistryStub:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def DiscoverBySkill(self, request):  # noqa: N802 - gRPC stub method name
            self.requests.append(request)
            if request.skill_id:
                return registry_pb2.DiscoverBySkillResponse()
            return registry_pb2.DiscoverBySkillResponse(
                registrations=[
                    registry_pb2.Registration(
                        peer_id="peer-local",
                        name="Local Agent",
                        description="local",
                        skills=[
                            registry_pb2.SkillInfo(skill_id="other", description="Other"),
                            registry_pb2.SkillInfo(
                                skill_id="hermes-chat",
                                description="Hermes chat",
                                tags=["chat"],
                            ),
                        ],
                    ),
                    registry_pb2.Registration(
                        peer_id="peer-filtered-out",
                        name="Wrong Agent",
                        description="wrong",
                        skills=[registry_pb2.SkillInfo(skill_id="other", description="Other")],
                    ),
                ]
            )

    registry = RegistryStub()
    client = daemon_client_cls(daemon_endpoint="127.0.0.1:50051")
    client._registry = registry

    results = await client.discover("hermes-chat", tags=["chat"], limit=1)

    assert results == [
        {
            "peer_id": "peer-local",
            "agent_name": "Local Agent",
            "agent_description": "local",
            "skills": ["other", "hermes-chat"],
        }
    ]
    assert [request.skill_id for request in registry.requests] == ["hermes-chat", ""]
    assert [request.limit for request in registry.requests] == [1, 1]


@pytest.mark.asyncio
async def test_keryx_client_discover_uses_bounded_full_registry_fallback_for_unlimited_call():
    from keryx import client as keryx_client

    daemon_client_cls = keryx_client.DaemonClient
    registry_pb2 = keryx_client.registry_pb2

    class RegistryStub:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def DiscoverBySkill(self, request):  # noqa: N802 - gRPC stub method name
            self.requests.append(request)
            return registry_pb2.DiscoverBySkillResponse()

    registry = RegistryStub()
    client = daemon_client_cls(daemon_endpoint="127.0.0.1:50051")
    client._registry = registry

    results = await client.discover("hermes-chat", limit=0)

    assert results == []
    assert [request.skill_id for request in registry.requests] == ["hermes-chat", ""]
    assert [request.limit for request in registry.requests] == [0, 100]
