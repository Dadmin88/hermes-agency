from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_compat():
    path = Path(__file__).resolve().parents[1] / "docker" / "hermes_compat.py"
    spec = importlib.util.spec_from_file_location("docker_hermes_compat_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_create_board_rejects_path_traversal_slug(tmp_path, monkeypatch):
    compat = _load_compat()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    outside = tmp_path / "pwn"

    with pytest.raises(ValueError, match="invalid Kanban board slug"):
        compat.create_board("agency-/../../pwn")

    assert not outside.exists()


def test_create_board_accepts_safe_slug_under_board_root(tmp_path, monkeypatch):
    compat = _load_compat()
    home = tmp_path / "home"
    monkeypatch.setenv("HERMES_HOME", str(home))

    compat.create_board("Agency-Backend")

    assert (home / "kanban" / "boards" / "agency-backend" / "board.json").exists()
    assert (home / "kanban" / "boards" / "agency-backend" / "kanban.db").exists()
