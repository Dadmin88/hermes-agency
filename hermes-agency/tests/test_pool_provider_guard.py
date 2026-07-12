"""Regression tests for provider failures in the registered pool tool path."""

import importlib.util
import sys
import time
import types
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture()
def pool_tools(monkeypatch):
    """Load pool/tools.py with an isolated roster module."""

    package = types.ModuleType("provider_guard_plugin")
    package.__path__ = [str(PLUGIN_DIR)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    pool_package = types.ModuleType("provider_guard_plugin.pool")
    pool_package.__path__ = [str(PLUGIN_DIR / "pool")]
    monkeypatch.setitem(sys.modules, pool_package.__name__, pool_package)

    roster = types.ModuleType("provider_guard_plugin.pool.roster")
    for name in (
        "_atomic_write_json",
        "_load_json",
        "build_roster",
        "ensure_profile_plugins",
        "find_agent",
        "load_roster",
        "queue_offline_task",
        "record_wake_attempt",
        "roster_state_path",
        "save_roster",
        "update_agent_status",
    ):
        setattr(roster, name, MagicMock())
    monkeypatch.setitem(sys.modules, roster.__name__, roster)

    spec = importlib.util.spec_from_file_location(
        "provider_guard_plugin.pool.tools", PLUGIN_DIR / "pool" / "tools.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("startup_error", "category", "retryable", "source"),
    [
        ("HTTP 401 unauthorized: api_key=abc123456789", "auth", "false", "runner"),
        ("insufficient_quota: token=quota-secret-123", "quota", "false", "runner"),
        (
            "HTTP 503 service unavailable; Bearer outage-secret-123",
            "outage",
            "true",
            "runner",
        ),
        ("HTTP 401 unauthorized: api_key=abc123456789", "auth", "false", "daemon"),
    ],
)
def test_pool_wake_classifies_and_sanitizes_provider_failures(
    pool_tools, monkeypatch, tmp_path, startup_error, category, retryable, source
):
    profile_dir = tmp_path / "profiles" / "agency-backend-engineer"
    profile_dir.mkdir(parents=True)
    (profile_dir / "config.yaml").write_text(
        "model:\n  provider: openai-codex\n  default: gpt-test\n", encoding="utf-8"
    )

    class FailedRunner:
        pid = 4321

        @staticmethod
        def poll():
            return 1

    def failed_popen(*args, **kwargs):
        if source == "runner":
            kwargs["stdout"].write(startup_error)
            kwargs["stdout"].flush()
        else:
            daemon_log = profile_dir / ".agency" / "logs" / "daemon.log"
            daemon_log.parent.mkdir(parents=True, exist_ok=True)
            daemon_log.write_text(startup_error, encoding="utf-8")
        return FailedRunner()

    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools, "_WakeLock", lambda: nullcontext())
    monkeypatch.setattr(pool_tools, "_pool_wake_decision", lambda name: None)
    monkeypatch.setattr(pool_tools, "_pool_wake_block_reason", lambda name: None)
    monkeypatch.setattr(pool_tools, "_ensure_worker_trusts_current_orchestrator", MagicMock())
    monkeypatch.setattr(pool_tools, "stop_profile_runner_processes", MagicMock())
    monkeypatch.setattr(pool_tools, "_stop_profile_daemon_processes", MagicMock())
    monkeypatch.setattr(pool_tools.subprocess, "Popen", failed_popen)
    pool_tools.ensure_profile_plugins.return_value = {}
    pool_tools.build_roster.return_value = {"profiles": []}

    result = pool_tools.pool_wake("agency-backend-engineer")

    recorded = pool_tools.record_wake_attempt.call_args.kwargs["error"]
    assert result == f"Error: {recorded}"
    assert "Agency infrastructure provider blocker" in recorded
    assert f"category={category}" in recorded
    assert "provider=openai-codex" in recorded
    assert "model=gpt-test" in recorded
    assert f"retryable={retryable}" in recorded
    assert "abc123456789" not in recorded
    assert "quota-secret-123" not in recorded
    assert "outage-secret-123" not in recorded
    assert "<redacted>" in recorded


def test_pool_send_does_not_retry_recent_nonretryable_provider_failure(pool_tools, monkeypatch):
    blocker = (
        "Agency infrastructure provider blocker: category=auth provider=openai-codex "
        "model=gpt-test retryable=false evidence=HTTP 401 unauthorized: api_key=<redacted>"
    )
    pool_tools.find_agent.return_value = {
        "name": "agency-backend-engineer",
        "online": False,
        "peer_id": None,
        "last_wake_error": blocker,
        "last_wake_attempt_at": time.time() - 120,
    }
    pool_tools.queue_offline_task.return_value = {
        "task": {"id": "offline-1"},
        "queue_path": "/tmp/offline-queue.json",
    }
    wake = MagicMock(return_value="Error: should not run")
    monkeypatch.setattr(pool_tools, "pool_wake", wake)

    result = pool_tools.pool_send("agency-backend-engineer", "do work")

    wake.assert_not_called()
    assert "recent wake failure is still cooling down" in result
    assert pool_tools.queue_offline_task.call_args.kwargs["reason"] == (
        f"recent wake failure: {blocker}"
    )


def test_pool_send_classifies_and_sanitizes_provider_failure(pool_tools, monkeypatch, tmp_path):
    profile_dir = tmp_path / "profiles" / "agency-backend-engineer"
    profile_dir.mkdir(parents=True)
    (profile_dir / "config.yaml").write_text(
        "model:\n  provider: openai-codex\n  default: gpt-test\n", encoding="utf-8"
    )
    pool_tools.PROFILES = tmp_path / "profiles"
    pool_tools.find_agent.return_value = {
        "name": "agency-backend-engineer",
        "online": True,
        "peer_id": "peer-test",
    }
    pool_tools.queue_offline_task.return_value = {
        "task": {"id": "offline-2"},
        "queue_path": "/tmp/offline-queue.json",
    }

    class ProviderAuthError(RuntimeError):
        status_code = 401

    manager = MagicMock()
    manager.send_task_sync.side_effect = ProviderAuthError(
        "unauthorized Authorization: Bearer send-secret-123"
    )
    node_manager = types.ModuleType("provider_guard_plugin.node_manager")
    setattr(node_manager, "manager", manager)
    monkeypatch.setitem(sys.modules, node_manager.__name__, node_manager)

    result = pool_tools.pool_send("agency-backend-engineer", "do work")

    reason = pool_tools.queue_offline_task.call_args.kwargs["reason"]
    assert "Agency infrastructure provider blocker" in reason
    assert "category=auth" in reason
    assert "retryable=false" in reason
    assert "send-secret-123" not in reason
    assert "send-secret-123" not in result
    assert "<redacted>" in reason


def test_pool_send_keeps_generic_queue_behavior_but_sanitizes_evidence(
    pool_tools, monkeypatch, tmp_path
):
    profile_dir = tmp_path / "profiles" / "agency-backend-engineer"
    profile_dir.mkdir(parents=True)
    pool_tools.PROFILES = tmp_path / "profiles"
    pool_tools.find_agent.return_value = {
        "name": "agency-backend-engineer",
        "online": True,
        "peer_id": "peer-test",
    }
    pool_tools.queue_offline_task.return_value = {
        "task": {"id": "offline-3"},
        "queue_path": "/tmp/offline-queue.json",
    }

    manager = MagicMock()
    manager.send_task_sync.side_effect = RuntimeError("protocol mismatch api_key=generic-secret")
    node_manager = types.ModuleType("provider_guard_plugin.node_manager")
    setattr(node_manager, "manager", manager)
    monkeypatch.setitem(sys.modules, node_manager.__name__, node_manager)

    result = pool_tools.pool_send("agency-backend-engineer", "do work")

    reason = pool_tools.queue_offline_task.call_args.kwargs["reason"]
    assert reason == "RuntimeError: protocol mismatch api_key=<redacted>"
    assert "Agency infrastructure provider blocker" not in reason
    assert "generic-secret" not in result
    assert "Queued task" in result


def test_failure_sanitizer_redacts_prefixed_api_keys_and_bearer_tokens(pool_tools):
    sanitized = pool_tools._sanitize_startup_output(
        "OPENAI_API_KEY=fake-key-123 Authorization: Bearer fake-bearer-456"
    )

    assert "fake-key-123" not in sanitized
    assert "fake-bearer-456" not in sanitized
    assert sanitized.count("<redacted>") >= 2
