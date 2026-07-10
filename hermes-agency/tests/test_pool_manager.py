"""Tests for pool manager security methods from PR #22."""

import importlib.util
import json
import sys
import time
import types
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure pool/ directory is on sys.path so `manager` is importable
POOL_DIR = str(Path(__file__).resolve().parents[1] / "pool")
if POOL_DIR not in sys.path:
    sys.path.insert(0, POOL_DIR)

from manager import PoolManager  # noqa: E402

ORIGINAL_WAKE = PoolManager.wake
PLUGIN_DIR = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_home(tmp_path):
    """Provide a temporary HERMES_HOME with a minimal registry."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    profiles = hermes_home / "profiles"
    profiles.mkdir()
    return hermes_home


@pytest.fixture()
def pool_manager(tmp_home):
    """Import and instantiate PoolManager with a temp HERMES_HOME."""
    with (
        patch.dict("os.environ", {"HERMES_HOME": str(tmp_home)}),
        patch("manager.REGISTRY_DEF", tmp_home / "registry_definition.json"),
    ):
        # Write a minimal registry so the manager has agents to validate against
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
                {
                    "name": "agency-frontend-engineer",
                    "description": "frontend",
                    "skills": ["react"],
                    "category": "agency",
                },
            ]
        }
        (tmp_home / "registry_definition.json").write_text(json.dumps(registry))

        # Patch startup so it doesn't try to start a real orchestrator process
        with patch.object(
            __import__("manager", fromlist=["PoolManager"]).PoolManager,
            "wake",
            return_value="fake-peer-id",
        ):
            from manager import PoolManager

            pm = PoolManager()
            yield pm


@pytest.fixture()
def pool_tools_module(tmp_path, monkeypatch):
    """Load pool.tools in package mode so relative imports resolve."""

    for name in list(sys.modules):
        if name == "hermes_plugin" or name.startswith("hermes_plugin."):
            sys.modules.pop(name, None)

    package = types.ModuleType("hermes_plugin")
    package.__path__ = [str(PLUGIN_DIR)]
    monkeypatch.setitem(sys.modules, "hermes_plugin", package)
    pool_pkg = types.ModuleType("hermes_plugin.pool")
    pool_pkg.__path__ = [str(PLUGIN_DIR / "pool")]
    monkeypatch.setitem(sys.modules, "hermes_plugin.pool", pool_pkg)

    for module_name, path in (
        ("hermes_plugin.provider_preflight", PLUGIN_DIR / "provider_preflight.py"),
        ("hermes_plugin.pool.roster", PLUGIN_DIR / "pool" / "roster.py"),
        ("hermes_plugin.pool.tools", PLUGIN_DIR / "pool" / "tools.py"),
    ):
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)

    tools = sys.modules["hermes_plugin.pool.tools"]
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr(tools, "PROFILES", profiles)
    monkeypatch.setattr(tools, "ensure_profile_plugins", lambda: {"profiles_errors": 0})
    monkeypatch.setattr(
        tools,
        "_pool_wake_decision",
        lambda _name: types.SimpleNamespace(allowed=True, sleep_candidate=None),
    )
    monkeypatch.setattr(tools, "stop_profile_runner_processes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(tools, "_stop_profile_daemon_processes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tools, "_ensure_worker_trusts_current_orchestrator", lambda *_args: False)
    monkeypatch.setattr(tools, "save_roster", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tools, "build_roster", lambda: {"profiles": []})
    monkeypatch.setattr(tools, "update_agent_status", lambda *_args, **_kwargs: None)
    return tools


# ---------------------------------------------------------------------------
# _registered_agent_names
# ---------------------------------------------------------------------------


class TestRegisteredAgentNames:
    def test_returns_set_of_names(self, pool_manager):
        names = pool_manager._registered_agent_names()
        assert isinstance(names, set)
        assert "agency-orchestrator" in names
        assert "agency-backend-engineer" in names
        assert "agency-frontend-engineer" in names

    def test_empty_registry(self, pool_manager):
        pool_manager.registry = {"agents": []}
        assert pool_manager._registered_agent_names() == set()

    def test_agents_without_name_key(self, pool_manager):
        pool_manager.registry = {"agents": [{"skills": []}]}
        # None is included in the set for agents missing 'name'
        names = pool_manager._registered_agent_names()
        assert None in names


# ---------------------------------------------------------------------------
# _validate_agent_name
# ---------------------------------------------------------------------------


class TestValidateAgentName:
    def test_valid_agent(self, pool_manager):
        # Should not raise for a known agent
        pool_manager._validate_agent_name("agency-orchestrator")

    def test_rejects_non_agency_prefix(self, pool_manager):
        with pytest.raises(ValueError, match="Only agency-"):
            pool_manager._validate_agent_name("admin-bot")

    def test_rejects_empty_string(self, pool_manager):
        with pytest.raises(ValueError):
            pool_manager._validate_agent_name("")

    def test_rejects_non_string(self, pool_manager):
        with pytest.raises(ValueError):
            pool_manager._validate_agent_name(None)
        with pytest.raises(ValueError):
            pool_manager._validate_agent_name(42)

    def test_rejects_unknown_agency_name(self, pool_manager):
        with pytest.raises(KeyError, match="agency-nonexistent"):
            pool_manager._validate_agent_name("agency-nonexistent")

    def test_detects_injection_attempts(self, pool_manager):
        """Names with path traversal or shell metacharacters must be rejected."""
        bad_names = [
            "../../../etc/passwd",
            "agency-orchestrator; rm -rf /",
            "agency-backend\x00engineer",
        ]
        for name in bad_names:
            with pytest.raises((ValueError, KeyError)):
                pool_manager._validate_agent_name(name)


# ---------------------------------------------------------------------------
# wake
# ---------------------------------------------------------------------------


class TestWake:
    def test_wake_preserves_registry_entries(self, pool_manager):
        """Waking an agent must not remove it from pool discovery metadata."""
        target = "agency-backend-engineer"
        before_agents = list(pool_manager.registry["agents"])

        with (
            patch.object(pool_manager, "_is_agent_disabled", return_value=False),
            patch.object(pool_manager, "_effective_max_agents", return_value=10),
            patch.object(pool_manager, "_model_config_preflight_error", return_value=None),
            patch.object(pool_manager, "_ensure_profile"),
            patch.object(pool_manager, "_start_cli_node", return_value=(None, "", False)),
            patch.object(
                pool_manager,
                "_start_runner_node",
                return_value=("12D3KooWfakebackendengineer", None, ""),
            ),
            patch.object(pool_manager, "_record_roster_wake"),
        ):
            peer_id = ORIGINAL_WAKE(pool_manager, target)

        assert peer_id == "12D3KooWfakebackendengineer"
        assert pool_manager.registry["agents"] == before_agents
        assert any(agent.get("name") == target for agent in pool_manager.registry["agents"])
        assert target in pool_manager.active

    def test_wake_classifies_runner_provider_auth_failure(self, pool_manager):
        target = "agency-backend-engineer"
        proc = FakeRunnerProc()
        wake_errors = []

        def record_wake(_name, *, success, peer_id=None, error=None):
            wake_errors.append({"success": success, "peer_id": peer_id, "error": error})

        with (
            patch.object(pool_manager, "_is_agent_disabled", return_value=False),
            patch.object(pool_manager, "_effective_max_agents", return_value=10),
            patch.object(pool_manager, "_model_config_preflight_error", return_value=None),
            patch.object(pool_manager, "_ensure_profile"),
            patch.object(pool_manager, "_start_cli_node", return_value=(None, "", False)),
            patch.object(
                pool_manager,
                "_start_runner_node",
                return_value=(None, proc, "HTTP 401 invalid api key sk-test-token"),
            ),
            patch.object(pool_manager, "_record_roster_wake", side_effect=record_wake),
        ):
            with pytest.raises(RuntimeError) as exc:
                ORIGINAL_WAKE(pool_manager, target)

        message = str(exc.value)
        assert "Agency infrastructure provider blocker" in message
        assert "category=auth_failed" in message
        assert "retryable=false" in message
        assert proc.terminated is True
        assert wake_errors[-1]["success"] is False
        assert "category=auth_failed" in wake_errors[-1]["error"]


class FakePoolToolsPopen:
    def __init__(self, *_args, stdout=None, **_kwargs):
        self.pid = 4242
        self._poll = 1
        if stdout is not None:
            stdout.write(FakePoolToolsPopen.output)
            stdout.flush()

    def poll(self):
        return self._poll


@pytest.mark.parametrize(
    ("output", "category", "retryable"),
    [
        ("HTTP 401 unauthorized: api_key=abc123456789", "auth_failed", "false"),
        ("HTTP 429 monthly usage limit reached", "quota_exhausted", "false"),
        ("HTTP 503 service unavailable: read timeout", "provider_unavailable", "true"),
    ],
)
def test_pool_tools_wake_classifies_provider_startup_failures(
    pool_tools_module, monkeypatch, output, category, retryable
):
    tools = pool_tools_module
    profile_dir = tools.PROFILES / "agency-backend-engineer"
    profile_dir.mkdir(parents=True)
    (profile_dir / "config.yaml").write_text(
        "model:\n  provider: openai-codex\n  default: gpt-5.5\n",
        encoding="utf-8",
    )
    FakePoolToolsPopen.output = output
    wake_errors = []

    monkeypatch.setattr(tools.subprocess, "Popen", FakePoolToolsPopen)
    monkeypatch.setattr(
        tools,
        "record_wake_attempt",
        lambda _name, *, success, peer_id=None, error=None: wake_errors.append(error),
    )

    result = tools.pool_wake("agency-backend-engineer")

    assert result.startswith("Error: Agency infrastructure provider blocker")
    assert f"category={category}" in result
    assert f"retryable={retryable}" in result
    assert "source=pool_tools_runner_start" in result
    assert "abc123456789" not in result
    assert wake_errors and wake_errors[-1] in result
    assert "abc123456789" not in wake_errors[-1]


def test_pool_tools_send_respects_nonretryable_provider_cooldown(pool_tools_module, monkeypatch):
    tools = pool_tools_module
    blocker = (
        "Agency infrastructure provider blocker: category=auth_failed retryable=false "
        "provider=openai-codex model=gpt-5.5 source=pool_tools_runner_start. "
        "Provider credentials or permissions failed. evidence=api_key=[REDACTED]"
    )
    queued_reasons = []

    monkeypatch.setattr(
        tools,
        "find_agent",
        lambda _name: {
            "name": "agency-backend-engineer",
            "online": False,
            "peer_id": None,
            "last_wake_error": blocker,
            "last_wake_attempt_at": time.time() - 120,
        },
    )
    monkeypatch.setattr(
        tools,
        "pool_wake",
        lambda _name: pytest.fail("pool_send retried a non-retryable provider blocker"),
    )

    def queue_offline(_name, _message, *, metadata=None, reason=None):
        queued_reasons.append(reason)
        return {"task": {"id": "queued-1"}, "queue_path": "/tmp/offline_task_queue.json"}

    monkeypatch.setattr(tools, "queue_offline_task", queue_offline)

    result = tools.pool_send("agency-backend-engineer", "hello")

    assert "recent wake failure is still cooling down" in result
    assert "queue_id=queued-1" in result
    assert queued_reasons == [f"recent wake failure: {blocker}"]


# ---------------------------------------------------------------------------
# runner process cleanup
# ---------------------------------------------------------------------------


class FakeRunnerProc:
    def __init__(self):
        self.terminated = False
        self.killed = False
        self.wait_timeouts = []

    def poll(self):
        return None if not self.terminated and not self.killed else 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        return 0


def test_terminate_runner_proc_stops_live_process(pool_manager):
    proc = FakeRunnerProc()

    pool_manager._terminate_runner_proc(proc)

    assert proc.terminated is True
    assert proc.killed is False
    assert proc.wait_timeouts == [20]
