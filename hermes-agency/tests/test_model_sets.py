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


def test_economic_model_set_resolves_backend_engineer(monkeypatch, tmp_path):
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: tmp_path / "hermes_home")
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    model_sets = _load_agency_module(monkeypatch, "model_sets")
    model_set = model_sets.load_model_set("economic")
    validation = model_sets.validate_model_set(model_set, strict=True)

    assert validation.ok
    resolved = model_sets.resolve_profile_model("agency-backend-engineer", model_set)
    assert resolved.family == "coding_worker"
    assert resolved.provider == "opencode-go"
    assert resolved.model == "deepseek-v4-pro"


def test_profile_config_writer_dry_run_preserves_files(monkeypatch, tmp_path):
    hermes_home = tmp_path / "hermes_home"
    profile_dir = hermes_home / "profiles" / "agency-backend-engineer"
    profile_dir.mkdir(parents=True)
    config_path = profile_dir / "config.yaml"
    original = (
        "plugins:\n  enabled:\n    - agency\nmodel:\n  provider: openai-codex\n  default: gpt-5.5\n"
    )
    config_path.write_text(original, encoding="utf-8")

    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: hermes_home)
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    model_sets = _load_agency_module(monkeypatch, "model_sets")
    writer = _load_agency_module(monkeypatch, "profile_config_writer")
    model_set = model_sets.load_model_set("economic")
    result = writer.apply_model_set(model_set, dry_run=True)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert config_path.read_text(encoding="utf-8") == original
    assert result["results"][0]["status"] == "drift"


def test_openai_codex_only_uses_only_openai_codex(monkeypatch, tmp_path):
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: tmp_path / "hermes_home")
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    model_sets = _load_agency_module(monkeypatch, "model_sets")
    model_set = model_sets.load_model_set("openai-codex-only")
    validation = model_sets.validate_model_set(model_set, strict=True)

    assert validation.ok, validation.as_dict()
    assert {family.provider for family in model_set.families.values()} == {"openai-codex"}
    assert model_sets.resolve_profile_model("agency-backend-engineer", model_set).model == "gpt-5.4"
    assert model_sets.resolve_profile_model("agency-orchestrator", model_set).model == "gpt-5.5"


def test_required_target_metadata_must_be_paired(monkeypatch, tmp_path):
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: tmp_path / "hermes_home")
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    model_sets = _load_agency_module(monkeypatch, "model_sets")
    model_set = model_sets.load_model_set("economic")
    metadata = {**model_set.metadata, "required_provider": "openai-codex"}

    validation = model_sets.validate_model_set(replace(model_set, metadata=metadata))

    assert not validation.ok
    assert (
        "metadata.required_provider and metadata.required_model must be set together"
        in validation.errors
    )


def test_required_target_metadata_validates_every_family(monkeypatch, tmp_path):
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: tmp_path / "hermes_home")
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    model_sets = _load_agency_module(monkeypatch, "model_sets")
    model_set = model_sets.load_model_set("openai-codex-only")
    metadata = {
        **model_set.metadata,
        "required_provider": "openai-codex",
        "required_model": "gpt-5.4-mini",
    }

    validation = model_sets.validate_model_set(replace(model_set, metadata=metadata))

    assert not validation.ok
    assert any(
        "Family coding_worker violates required model policy" in error
        for error in validation.errors
    )
