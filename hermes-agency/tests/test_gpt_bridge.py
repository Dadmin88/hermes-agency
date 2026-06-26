from __future__ import annotations

import importlib.util
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
