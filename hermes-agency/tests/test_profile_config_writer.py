from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("yaml")

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


def _load_modules_and_set(monkeypatch, tmp_path):
    hermes_home = tmp_path / "hermes_home"
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: hermes_home)
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)
    model_sets = _load_agency_module(monkeypatch, "model_sets")
    writer = _load_agency_module(monkeypatch, "profile_config_writer")
    return hermes_home, model_sets, writer, model_sets.load_model_set("openai-codex-only")


def _write_profile_config(hermes_home: Path, content: str) -> Path:
    profile_dir = hermes_home / "profiles" / "agency-backend-engineer"
    profile_dir.mkdir(parents=True)
    config_path = profile_dir / "config.yaml"
    config_path.write_text(content, encoding="utf-8")
    return config_path


def test_apply_writes_explicit_reasoning_effort_and_preserves_agent_keys(monkeypatch, tmp_path):
    hermes_home, model_sets, writer, model_set = _load_modules_and_set(monkeypatch, tmp_path)
    config_path = _write_profile_config(
        hermes_home,
        """plugins:
  enabled: [agency]
model:
  provider: openai-codex
  default: gpt-5.6-terra
  context_length: 128000
agent:
  max_turns: 42
  reasoning_effort: low
other:
  keep: true
""",
    )
    family = model_set.families["coding_worker"]
    model_set = replace(
        model_set,
        families={**model_set.families, "coding_worker": replace(family, reasoning_effort="high")},
    )

    result = writer.apply_model_set(model_set, dry_run=False, yes=True)
    data = writer._load_config(config_path)

    assert result["results"][0]["status"] == "updated"
    assert data["model"] == {
        "provider": "openai-codex",
        "default": "gpt-5.6-sol",
        "context_length": 128000,
    }
    assert data["agent"] == {"max_turns": 42, "reasoning_effort": "high"}
    assert data["other"] == {"keep": True}
    assert result["results"][0]["backup_path"]


def test_inherited_reasoning_effort_preserves_existing_unmanaged_value(monkeypatch, tmp_path):
    hermes_home, _model_sets, writer, model_set = _load_modules_and_set(monkeypatch, tmp_path)
    config_path = _write_profile_config(
        hermes_home,
        """model:
  provider: openai-codex
  default: gpt-5.6-terra
agent:
  reasoning_effort: ultra
  max_turns: 7
""",
    )

    plan = writer.profile_plan("agency-backend-engineer", model_set)
    result = writer.apply_model_set(model_set, dry_run=False, yes=True)
    data = writer._load_config(config_path)

    assert plan.status == "drift"
    assert plan.target == "openai-codex/gpt-5.6-sol (reasoning_effort=inherit)"
    assert (
        result["results"][0]["message"]
        == "Updated model; preserved inherited agent.reasoning_effort"
    )
    assert data["agent"] == {"reasoning_effort": "ultra", "max_turns": 7}
