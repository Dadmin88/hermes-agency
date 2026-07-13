"""Remote subprocess environment must not inherit ambient credentials."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture()
def task_processor(monkeypatch, tmp_path):
    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()
    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: hermes_home
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli_config = types.ModuleType("hermes_cli.config")
    hermes_cli_config.cfg_get = lambda config, *path, default=None: default
    hermes_cli_config.load_config = lambda: {}
    hermes_cli.config = hermes_cli_config
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_cli_config)

    pkg = types.ModuleType("hermes_plugin")
    pkg.__path__ = [str(PLUGIN_DIR)]
    monkeypatch.setitem(sys.modules, "hermes_plugin", pkg)

    for name in ("conversation", "trust", "config", "task_processor"):
        full = f"hermes_plugin.{name}"
        if name == "task_processor":
            path = PLUGIN_DIR / "task_processor.py"
        else:
            path = PLUGIN_DIR / f"{name}.py"
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location(full, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full, module)
        try:
            spec.loader.exec_module(module)
        except Exception:
            if name != "task_processor":
                continue
            raise
    return sys.modules["hermes_plugin.task_processor"]


def test_build_remote_subprocess_env_excludes_secrets(task_processor, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/tmp/home")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-openai")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/ssh.sock")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy")
    monkeypatch.setenv("HERMES_SESSION_ID", "session-should-not-leak")
    monkeypatch.setenv("HERMES_HOME", "/tmp/hermes")

    env = task_processor.build_remote_subprocess_env(
        profile_name="agency-backend-engineer",
        allow_hooks=False,
    )
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/tmp/home"
    assert env["HERMES_HOME"] == "/tmp/hermes"
    assert env["HERMES_PROFILE"] == "agency-backend-engineer"
    assert "OPENAI_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "SSH_AUTH_SOCK" not in env
    assert "HTTP_PROXY" not in env
    assert "HERMES_SESSION_ID" not in env
    assert "HERMES_YOLO_MODE" not in env
    assert env.get("HERMES_ACCEPT_HOOKS") is None


def test_build_remote_subprocess_env_allow_hooks(task_processor, monkeypatch):
    monkeypatch.setenv("PATH", "/bin")
    env = task_processor.build_remote_subprocess_env(profile_name="agency-qa", allow_hooks=True)
    assert env["HERMES_ACCEPT_HOOKS"] == "1"
