"""Pool profile path resolution must honor HERMES_HOME / HERMES_PROFILES_DIR."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture()
def pool_tools(monkeypatch, tmp_path):
    path = PLUGIN_DIR / "pool" / "tools.py"
    # Load as a free module so we can exercise path helpers without full package boot.
    spec = importlib.util.spec_from_file_location("agency_pool_tools_paths", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Minimal stubs for roster imports at module import time.
    roster = type(sys)("roster_stub")
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
        setattr(roster, name, lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "roster", roster)
    # Relative import path: pool.tools does `from .roster import ...`
    # Loading via free module may fail on relative import — load package style.
    pkg = type(sys)("hermes_agency_pool_path_pkg")
    pkg.__path__ = [str(PLUGIN_DIR / "pool")]
    monkeypatch.setitem(sys.modules, "hermes_agency_pool_path_pkg", pkg)
    monkeypatch.setitem(sys.modules, "hermes_agency_pool_path_pkg.roster", roster)
    spec = importlib.util.spec_from_file_location(
        "hermes_agency_pool_path_pkg.tools",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    monkeypatch.setitem(sys.modules, "hermes_agency_pool_path_pkg.tools", module)
    try:
        spec.loader.exec_module(module)
    except Exception:
        # Fall back to already-installed package path if relative imports require it.
        sys.path.insert(0, str(PLUGIN_DIR.parent))
        from hermes_agency.pool import tools as module  # type: ignore
    return module


def test_profiles_dir_prefers_hermes_profiles_dir(pool_tools, monkeypatch, tmp_path):
    profiles = tmp_path / "custom-profiles"
    profiles.mkdir()
    monkeypatch.setenv("HERMES_PROFILES_DIR", str(profiles))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "ignored-home"))
    assert pool_tools.profiles_dir() == profiles


def test_profiles_dir_uses_hermes_home_profiles(pool_tools, monkeypatch, tmp_path):
    home = tmp_path / "hermes"
    profiles = home / "profiles"
    profiles.mkdir(parents=True)
    monkeypatch.delenv("HERMES_PROFILES_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(home))
    # Reset module override to default so env wins.
    pool_tools.PROFILES = Path.home() / ".hermes" / "profiles"
    assert pool_tools.profiles_dir() == profiles


def test_profiles_dir_uses_profile_home_parent(pool_tools, monkeypatch, tmp_path):
    profiles = tmp_path / "profiles"
    profile_home = profiles / "agency-backend-engineer"
    profile_home.mkdir(parents=True)
    monkeypatch.delenv("HERMES_PROFILES_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(profile_home))
    pool_tools.PROFILES = Path.home() / ".hermes" / "profiles"
    assert pool_tools.profiles_dir() == profiles


def test_profile_dir_for_agent_uses_resolved_root(pool_tools, monkeypatch, tmp_path):
    profiles = tmp_path / "profiles"
    target = profiles / "agency-backend-engineer"
    target.mkdir(parents=True)
    monkeypatch.setenv("HERMES_PROFILES_DIR", str(profiles))
    resolved = pool_tools._profile_dir_for_agent_name("agency-backend-engineer")
    assert resolved == target.resolve()
