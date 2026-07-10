from __future__ import annotations

import importlib.util
import sys
import types
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
    assert {family.model for family in model_set.families.values()} == {"gpt-5.5"}
    assert model_sets.resolve_profile_model("agency-backend-engineer", model_set).model == "gpt-5.5"
    assert model_sets.resolve_profile_model("agency-backend", model_set).model == "gpt-5.5"
    assert model_sets.resolve_profile_model("agency-code-reviewer", model_set).model == "gpt-5.5"
    assert model_sets.resolve_profile_model("agency-copywriter", model_set).model == "gpt-5.5"
    assert model_sets.resolve_profile_model("agency-orchestrator", model_set).model == "gpt-5.5"
    assert model_set.task_routing["tiers"]["gpt55_rollback"]["model"] == "gpt-5.5"


def test_openai_codex_only_gpt55_profile_policy_counts(monkeypatch, tmp_path):
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: tmp_path / "hermes_home")
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    model_sets = _load_agency_module(monkeypatch, "model_sets")
    model_set = model_sets.load_model_set("openai-codex-only")
    resolved = [
        model_sets.resolve_profile_model(profile, model_set) for profile in model_set.profiles
    ]
    counts = {}
    family_counts = {}
    for item in resolved:
        counts[f"{item.provider}/{item.model}"] = counts.get(f"{item.provider}/{item.model}", 0) + 1
        family_counts[item.family] = family_counts.get(item.family, 0) + 1

    assert counts == {"openai-codex/gpt-5.5": len(model_set.profiles)}
    assert family_counts["coding_worker"] == 15
    assert family_counts["coding_light"] == 14
    assert family_counts["review_worker"] == 6
    assert family_counts["senior_review"] == 8
    assert family_counts["orchestration"] == 9


def test_model_config_audit_reports_drift(monkeypatch, tmp_path):
    profiles_dir = tmp_path / "profiles"
    profile_dir = profiles_dir / "agency-backend-engineer"
    profile_dir.mkdir(parents=True)
    (profile_dir / "config.yaml").write_text(
        "model:\n  provider: opencode-go\n  default: deepseek-v4-pro\n"
        "agency:\n  models:\n    active_set: economic\n",
        encoding="utf-8",
    )

    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    model_sets = _load_agency_module(monkeypatch, "model_sets")
    writer = _load_agency_module(monkeypatch, "profile_config_writer")
    model_set = model_sets.load_model_set("openai-codex-only")

    audit = writer.audit_model_set_configs(
        model_set,
        profiles=["agency-backend-engineer"],
        base=profiles_dir,
        include_roster=False,
    )

    assert audit.ok is False
    assert audit.missing_configs == []
    assert audit.drifted_configs[0]["profile"] == "agency-backend-engineer"
    assert audit.drifted_configs[0]["current"] == "opencode-go/deepseek-v4-pro"
    assert audit.drifted_configs[0]["target"] == "openai-codex/gpt-5.5"
    assert "active_set" in audit.drifted_configs[0]["message"]


def test_model_config_audit_reports_missing_roster_config(monkeypatch, tmp_path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True)

    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    model_sets = _load_agency_module(monkeypatch, "model_sets")
    writer = _load_agency_module(monkeypatch, "profile_config_writer")
    model_set = model_sets.load_model_set("openai-codex-only")

    audit = writer.audit_model_set_configs(
        model_set,
        profiles=["agency-backend-engineer"],
        base=profiles_dir,
        include_roster=False,
    )

    assert audit.ok is False
    assert audit.drifted_configs == []
    assert audit.missing_configs[0]["profile"] == "agency-backend-engineer"
    assert audit.missing_configs[0]["status"] == "missing"


def test_provider_failure_classification_quota(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")

    result = preflight.classify_provider_failure(
        "HTTP 429: monthly usage limit reached",
        provider="opencode-go",
        model="mimo-v2.5-pro",
    )

    assert result.ok is False
    assert result.category == "quota_exhausted"
    assert result.retryable is False
    assert "Do not retry Kanban workers" in result.actions[1]


def test_provider_failure_classification_auth_redacts_secret(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")

    result = preflight.classify_provider_failure(
        "HTTP 401 unauthorized: api_key=abc123456789",
        provider="openai-codex",
        model="gpt-5.5",
    )

    assert result.category == "auth_failed"
    assert result.retryable is False
    assert "abc123456789" not in (result.evidence or "")
    assert "[REDACTED]" in (result.evidence or "")


def test_provider_failure_classification_provider_unavailable(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")

    result = preflight.classify_provider_failure(
        "HTTP 503 service unavailable: read timeout",
        provider="openai-codex",
        model="gpt-5.5",
    )

    assert result.category == "provider_unavailable"
    assert result.retryable is True
    assert "outage" in result.actions[1]


def test_models_validate_health_reports_config_drift_nonzero(monkeypatch, tmp_path):
    profiles_dir = tmp_path / "profiles"
    profile_dir = profiles_dir / "agency-backend-engineer"
    profile_dir.mkdir(parents=True)
    (profile_dir / "config.yaml").write_text(
        "model:\n  provider: opencode-go\n  default: deepseek-v4-pro\n",
        encoding="utf-8",
    )

    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    cli = _load_agency_module(monkeypatch, "cli")

    text, code = cli._models_validate_text("openai-codex-only", health=True)

    assert code == 2
    assert "Config health:" in text
    assert "drift=" in text
    assert "Infrastructure blocker" in text


def test_model_set_validation_rejects_unknown_task_routing_tier_or_provider(monkeypatch, tmp_path):
    hermes_constants = types.ModuleType("hermes_constants")
    setattr(hermes_constants, "get_hermes_home", lambda: tmp_path / "hermes_home")
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    model_sets = _load_agency_module(monkeypatch, "model_sets")
    model_set = model_sets.load_model_set("openai-codex-only")
    bad = model_sets.ModelSet(
        name=model_set.name,
        description=model_set.description,
        version=model_set.version,
        defaults=model_set.defaults,
        families=model_set.families,
        profiles=model_set.profiles,
        task_routing={
            "default": {"tier": "missing"},
            "tiers": {"safe_default": {"provider": "unknown-provider", "model": "missing-model"}},
            "downgrade_rules": {"docs": {"tier": "missing"}},
        },
        escalation=model_set.escalation,
        budget=model_set.budget,
        metadata=model_set.metadata,
        source_path=model_set.source_path,
        source=model_set.source,
    )

    validation = model_sets.validate_model_set(bad, strict=True)

    assert validation.ok is False
    assert any("Unknown provider" in error for error in validation.errors)
    assert any("default.tier references missing tier" in error for error in validation.errors)
    assert any("downgrade_rules.docs.tier" in error for error in validation.errors)
