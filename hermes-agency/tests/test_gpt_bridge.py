from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load_agency_module(monkeypatch, module_name: str):
    package = sys.modules.get("hermes_plugin")
    if package is None:
        package = types.ModuleType("hermes_plugin")
        package.__path__ = [str(PLUGIN_DIR)]
        monkeypatch.setitem(sys.modules, "hermes_plugin", package)
    full_name = f"hermes_plugin.{module_name}"
    spec = importlib.util.spec_from_file_location(full_name, PLUGIN_DIR / f"{module_name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, full_name, module)
    spec.loader.exec_module(module)
    return module


def test_gpt_bridge_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_AGENCY_GPT_BRIDGE_DIR", str(tmp_path / "gpt_bridge"))
    bridge = _load_agency_module(monkeypatch, "gpt_bridge")

    created = bridge.enqueue_task(
        "Fix the model routing bug.",
        reason="Needs senior review.",
        expected_output="Patch summary and tests.",
        urgency="high",
        source_profile="agency-orchestrator",
    )

    assert created["ok"] is True
    task_id = created["task"]["task_id"]
    assert bridge.summary()["counts"] == {"queued": 1}

    claimed = bridge.claim_task(task_id, claimed_by="GPT-5.5")
    assert claimed["ok"] is True
    assert claimed["task"]["status"] == "claimed"

    completed = bridge.complete_task(task_id, "Done.", completed_by="GPT-5.5")
    assert completed["ok"] is True
    assert completed["task"]["status"] == "completed"
    assert completed["task"]["result"] == "Done."
    assert bridge.summary()["counts"] == {"completed": 1}


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_gpt_bridge_writes_private_task_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_AGENCY_GPT_BRIDGE_DIR", str(tmp_path / "gpt_bridge"))
    bridge = _load_agency_module(monkeypatch, "gpt_bridge")

    old_umask = os.umask(0o022)
    try:
        created = bridge.enqueue_task("Handle sensitive escalation.", metadata={"secret": "marker"})
    finally:
        os.umask(old_umask)

    assert created["ok"] is True
    task_path = Path(created["path"])
    assert _mode(bridge.bridge_dir()) == 0o700
    assert _mode(bridge.tasks_dir()) == 0o700
    assert _mode(task_path) == 0o600


def test_gpt_bridge_repairs_existing_task_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_AGENCY_GPT_BRIDGE_DIR", str(tmp_path / "gpt_bridge"))
    bridge = _load_agency_module(monkeypatch, "gpt_bridge")

    created = bridge.enqueue_task("Handle sensitive escalation.")
    task_id = created["task"]["task_id"]
    task_path = Path(created["path"])
    bridge.bridge_dir().chmod(0o755)
    bridge.tasks_dir().chmod(0o755)
    task_path.chmod(0o644)

    loaded = bridge.get_task(task_id)

    assert loaded["ok"] is True
    assert _mode(bridge.bridge_dir()) == 0o700
    assert _mode(bridge.tasks_dir()) == 0o700
    assert _mode(task_path) == 0o600


def test_gpt_bridge_updates_do_not_downgrade_private_task_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_AGENCY_GPT_BRIDGE_DIR", str(tmp_path / "gpt_bridge"))
    bridge = _load_agency_module(monkeypatch, "gpt_bridge")

    created = bridge.enqueue_task("Handle sensitive escalation.")
    task_id = created["task"]["task_id"]
    task_path = Path(created["path"])
    assert _mode(task_path) == 0o600

    old_umask = os.umask(0o022)
    try:
        claimed = bridge.claim_task(task_id, claimed_by="GPT-5.5")
        completed = bridge.complete_task(task_id, "Done.", completed_by="GPT-5.5")
    finally:
        os.umask(old_umask)

    assert claimed["ok"] is True
    assert completed["ok"] is True
    assert _mode(task_path) == 0o600
