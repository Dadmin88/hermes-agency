"""Tests for pool manager security methods from PR #22."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure pool/ directory is on sys.path so `manager` is importable
POOL_DIR = str(Path(__file__).resolve().parents[1] / "pool")
if POOL_DIR not in sys.path:
    sys.path.insert(0, POOL_DIR)

from manager import PoolManager  # noqa: E402

ORIGINAL_WAKE = PoolManager.wake


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
