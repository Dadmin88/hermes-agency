"""Model-set presets and resolution for Hermes Agency staff profiles.

This module intentionally belongs to Hermes Agency.  It does not assume Hermes
core supports profile inheritance or model override maps.  The selected model set
is resolved here, then callers can either report the plan or safely write the
resolved provider/model into installed agency profile config.yaml files.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - Hermes normally depends on PyYAML
    yaml = None  # type: ignore[assignment]

SECRET_KEY_FRAGMENTS = ("api_key", "apikey", "token", "secret", "password", "credential")
SUPPORTED_VERSION = 1
DEFAULT_MODEL_SET = "openai-codex-only"
CATEGORY_FAMILY_DEFAULTS: dict[str, str] = {
    "leadership": "orchestration",
    "engineering": "coding_worker",
    "qa": "review_worker",
    "design": "creative_worker",
    "content": "creative_worker",
    "marketing": "creative_worker",
    "product": "analysis_worker",
    "support": "general_worker",
    "operations": "general_worker",
    "security": "senior_review",
    "legal": "senior_review",
}
KNOWN_TOP_LEVEL_KEYS = {
    "version",
    "name",
    "description",
    "defaults",
    "families",
    "profiles",
    "task_routing",
    "escalation",
    "budget",
    "metadata",
}


@dataclass(frozen=True)
class ModelRef:
    provider: str
    model: str
    family: str
    reason: str | None = None


@dataclass(frozen=True)
class ModelFamily:
    name: str
    provider: str
    model: str
    reason: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class ModelSet:
    name: str
    description: str
    version: int
    defaults: dict[str, Any]
    families: dict[str, ModelFamily]
    profiles: dict[str, str]
    task_routing: dict[str, Any]
    escalation: dict[str, Any]
    budget: dict[str, Any]
    metadata: dict[str, Any]
    source_path: Path
    source: str


@dataclass(frozen=True)
class ModelCatalog:
    providers: dict[str, Any]
    source_path: Path


@dataclass(frozen=True)
class ResolvedProfileModel:
    profile: str
    family: str
    provider: str
    model: str
    reason: str | None
    source_preset: str
    source_path: str
    resolution_source: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class ModelSetValidationResult:
    ok: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "warnings": self.warnings, "errors": self.errors}


def plugin_root() -> Path:
    return Path(__file__).resolve().parent


def packaged_model_sets_dir() -> Path:
    return plugin_root() / "model_sets"


def user_model_sets_dir() -> Path:
    return Path(
        os.environ.get("HERMES_AGENCY_MODEL_SETS_DIR", "~/.hermes/agency/model_sets")
    ).expanduser()


def catalog_path() -> Path:
    return plugin_root() / "model_catalog.yaml"


def _require_yaml() -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required for Hermes Agency model sets")


class _UniqueKeyLoader(yaml.SafeLoader if yaml is not None else object):  # type: ignore[misc,valid-type]
    pass


def _construct_mapping(loader: Any, node: Any, deep: bool = False) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


if yaml is not None:  # pragma: no branch
    _UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
    )


def _load_yaml_file(path: Path) -> dict[str, Any]:
    _require_yaml()
    with open(path, encoding="utf-8") as handle:
        data = yaml.load(handle, Loader=_UniqueKeyLoader)  # noqa: S506 - safe loader subclass
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _contains_secret_key(value: Any, prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            path = f"{prefix}.{key}" if prefix else str(key)
            if any(fragment in key_text for fragment in SECRET_KEY_FRAGMENTS):
                hits.append(path)
            hits.extend(_contains_secret_key(child, path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            hits.extend(_contains_secret_key(child, f"{prefix}[{idx}]"))
    return hits


def discover_model_set_files() -> dict[str, Path]:
    """Return preset name to path. User presets override packaged presets."""
    discovered: dict[str, Path] = {}
    for directory in (packaged_model_sets_dir(), user_model_sets_dir()):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            if path.name.lower() == "readme.yaml":
                continue
            discovered[path.stem] = path
    return discovered


def load_catalog() -> ModelCatalog:
    path = catalog_path()
    data = _load_yaml_file(path) if path.exists() else {}
    providers = data.get("providers") if isinstance(data.get("providers"), dict) else {}
    return ModelCatalog(providers=providers, source_path=path)


def load_model_set(name: str) -> ModelSet:
    requested = (name or "").strip() or DEFAULT_MODEL_SET
    files = discover_model_set_files()
    path = files.get(requested)
    if path is None:
        raise ValueError(
            f"Unknown model set '{requested}'. Available: {', '.join(sorted(files)) or 'none'}"
        )
    raw = _load_yaml_file(path)
    version = raw.get("version")
    families_raw = raw.get("families") or {}
    if not isinstance(families_raw, dict):
        families_raw = {}
    families: dict[str, ModelFamily] = {}
    for family_name, family_data in families_raw.items():
        if not isinstance(family_data, dict):
            family_data = {}
        families[str(family_name)] = ModelFamily(
            name=str(family_name),
            provider=str(family_data.get("provider") or "").strip(),
            model=str(family_data.get("model") or "").strip(),
            reason=str(family_data.get("reason") or "").strip() or None,
            enabled=bool(family_data.get("enabled", True)),
        )
    profiles = raw.get("profiles") or {}
    if not isinstance(profiles, dict):
        profiles = {}
    source = "user" if user_model_sets_dir() in path.parents else "packaged"
    return ModelSet(
        name=str(raw.get("name") or path.stem),
        description=str(raw.get("description") or ""),
        version=int(version) if isinstance(version, int) else version,  # type: ignore[arg-type]
        defaults=raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {},
        families=families,
        profiles={str(k): str(v) for k, v in profiles.items()},
        task_routing=raw.get("task_routing") if isinstance(raw.get("task_routing"), dict) else {},
        escalation=raw.get("escalation") if isinstance(raw.get("escalation"), dict) else {},
        budget=raw.get("budget") if isinstance(raw.get("budget"), dict) else {},
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        source_path=path,
        source=source,
    )


def validate_model_set(
    model_set: ModelSet, catalog: ModelCatalog | None = None, *, strict: bool = False
) -> ModelSetValidationResult:
    result = ModelSetValidationResult()
    catalog = catalog or load_catalog()
    raw = _load_yaml_file(model_set.source_path)

    for hit in _contains_secret_key(raw):
        result.error(f"Preset must not contain secret-like key: {hit}")
    for key in raw:
        if key not in KNOWN_TOP_LEVEL_KEYS:
            result.warn(f"Unknown top-level key: {key}")
    if raw.get("version") is None:
        result.error("Missing required key: version")
    elif raw.get("version") != SUPPORTED_VERSION:
        result.error(f"Unsupported model-set version: {raw.get('version')}")
    default_family = model_set.defaults.get("family")
    if not default_family:
        result.error("Missing defaults.family")
    elif default_family not in model_set.families:
        result.error(f"defaults.family references missing family: {default_family}")

    for family_name, family in model_set.families.items():
        if not family.provider or not family.model:
            result.error(f"Family {family_name} must define non-empty provider and model")
        if not family.enabled:
            result.error(f"Family {family_name} is disabled but present in selectable families")
        provider = catalog.providers.get(family.provider)
        if provider is None:
            result.error(f"Unknown provider '{family.provider}' in family {family_name}")
            continue
        models = provider.get("models") if isinstance(provider, dict) else None
        if not isinstance(models, dict) or family.model not in models:
            message = f"Unknown model '{family.model}' for provider '{family.provider}' in family {family_name}"
            if strict:
                result.error(message)
            else:
                result.warn(message)
            continue
        model_meta = models.get(family.model) or {}
        if isinstance(model_meta, dict) and (
            model_meta.get("input_cost_per_1m") is None
            or model_meta.get("output_cost_per_1m") is None
        ):
            result.warn(f"Pricing is unknown for {family.provider}/{family.model}")

    for profile, family_name in model_set.profiles.items():
        if family_name not in model_set.families:
            result.error(f"Profile {profile} references missing family: {family_name}")

    escalation_family = model_set.escalation.get("default_family")
    if escalation_family and escalation_family not in model_set.families:
        result.error(f"escalation.default_family references missing family: {escalation_family}")

    _validate_task_routing(model_set, catalog, result, strict=strict)
    return result


def _validate_task_routing(
    model_set: ModelSet,
    catalog: ModelCatalog,
    result: ModelSetValidationResult,
    *,
    strict: bool = False,
) -> None:
    routing = model_set.task_routing
    if not routing:
        return
    tiers = routing.get("tiers") if isinstance(routing.get("tiers"), dict) else {}
    if not tiers:
        result.error("task_routing.tiers must define at least the safe_default tier")
        return
    for tier_name, tier in tiers.items():
        if not isinstance(tier, dict):
            result.error(f"task_routing.tiers.{tier_name} must be a mapping")
            continue
        provider_name = str(tier.get("provider") or "").strip()
        model_name = str(tier.get("model") or "").strip()
        if not provider_name or not model_name:
            result.error(f"task_routing.tiers.{tier_name} must define provider and model")
            continue
        provider = catalog.providers.get(provider_name)
        if provider is None:
            result.error(f"Unknown provider '{provider_name}' in task_routing tier {tier_name}")
            continue
        models = provider.get("models") if isinstance(provider, dict) else None
        if not isinstance(models, dict) or model_name not in models:
            message = f"Unknown model '{model_name}' for provider '{provider_name}' in task_routing tier {tier_name}"
            if strict:
                result.error(message)
            else:
                result.warn(message)
    default = routing.get("default") if isinstance(routing.get("default"), dict) else {}
    default_tier = str(default.get("tier") or "").strip()
    if default_tier and default_tier not in tiers:
        result.error(f"task_routing.default.tier references missing tier: {default_tier}")
    escalation = routing.get("escalation") if isinstance(routing.get("escalation"), dict) else {}
    force_tier = str(escalation.get("force_tier") or "").strip()
    if force_tier and force_tier not in tiers:
        result.error(f"task_routing.escalation.force_tier references missing tier: {force_tier}")
    downgrade_rules = (
        routing.get("downgrade_rules") if isinstance(routing.get("downgrade_rules"), dict) else {}
    )
    for rule_name, rule in downgrade_rules.items():
        if not isinstance(rule, dict):
            result.error(f"task_routing.downgrade_rules.{rule_name} must be a mapping")
            continue
        tier_name = str(rule.get("tier") or "").strip()
        if not tier_name or tier_name not in tiers:
            result.error(
                f"task_routing.downgrade_rules.{rule_name}.tier references missing tier: {tier_name or '<empty>'}"
            )


def active_model_set_name(
    cli_value: str | None = None, config: dict[str, Any] | None = None
) -> str:
    if cli_value:
        return cli_value
    env_value = os.environ.get("HERMES_AGENCY_MODEL_SET")
    if env_value:
        return env_value
    config = config or {}
    agency = config.get("agency") if isinstance(config, dict) else None
    models = agency.get("models") if isinstance(agency, dict) else None
    value = models.get("active_set") if isinstance(models, dict) else None
    return str(value or DEFAULT_MODEL_SET)


def _manifest_profile(name: str) -> dict[str, Any] | None:
    try:
        from .default_staff import get_profile_info, read_profile_metadata
    except Exception:
        return None
    info = get_profile_info(name) or {}
    metadata = read_profile_metadata(name) or {}
    merged = dict(info)
    merged.update({k: v for k, v in metadata.items() if k not in merged or v})
    return merged or None


def _family_from_manifest(profile: str) -> tuple[str | None, str, list[str]]:
    warnings: list[str] = []
    info = _manifest_profile(profile)
    if not info:
        warnings.append(
            f"{profile} is not in the packaged default staff manifest; using preset default"
        )
        return None, "preset_default", warnings
    model_family = info.get("model_family")
    if model_family:
        return str(model_family), "profile_metadata", warnings
    category = str(info.get("category") or "").strip().lower()
    if category and category in CATEGORY_FAMILY_DEFAULTS:
        return CATEGORY_FAMILY_DEFAULTS[category], "category_mapping", warnings
    warnings.append(f"{profile} has no model_family/category mapping; using preset default")
    return None, "preset_default", warnings


def resolve_profile_model(profile: str, model_set: ModelSet) -> ResolvedProfileModel:
    warnings: list[str] = []
    resolution_source = "profile_mapping"
    family_name = model_set.profiles.get(profile)
    if not family_name:
        inferred, resolution_source, inferred_warnings = _family_from_manifest(profile)
        warnings.extend(inferred_warnings)
        family_name = inferred or str(model_set.defaults.get("family") or "")
    family = model_set.families.get(family_name)
    if family is None:
        fallback = str(model_set.defaults.get("family") or "")
        warnings.append(
            f"Family {family_name!r} missing; fell back to defaults.family {fallback!r}"
        )
        family_name = fallback
        family = model_set.families.get(family_name)
    if family is None:
        raise ValueError(f"Could not resolve model family for profile {profile}")
    return ResolvedProfileModel(
        profile=profile,
        family=family_name,
        provider=family.provider,
        model=family.model,
        reason=family.reason,
        source_preset=model_set.name,
        source_path=str(model_set.source_path),
        resolution_source=resolution_source,
        warnings=warnings,
    )


def default_staff_names() -> list[str]:
    try:
        from .default_staff import list_default_staff
    except Exception:
        return []
    return sorted(
        str(item.get("name"))
        for item in list_default_staff()
        if str(item.get("name", "")).startswith("agency-")
    )


def resolve_roster(model_set: ModelSet) -> list[ResolvedProfileModel]:
    return [resolve_profile_model(profile, model_set) for profile in default_staff_names()]


def resolve_escalation_model(
    model_set: ModelSet, risk_tags: list[str] | None = None, profile: str = "agency-orchestrator"
) -> ResolvedProfileModel:
    risk_tags = [str(tag).lower() for tag in (risk_tags or [])]
    triggers = {str(tag).lower() for tag in model_set.escalation.get("triggers", [])}
    if risk_tags and triggers.intersection(risk_tags):
        family_name = str(
            model_set.escalation.get("default_family") or model_set.defaults.get("family") or ""
        )
        family = model_set.families.get(family_name)
        if family is None:
            raise ValueError(f"Escalation family {family_name!r} is not defined")
        return ResolvedProfileModel(
            profile=profile,
            family=family_name,
            provider=family.provider,
            model=family.model,
            reason=family.reason,
            source_preset=model_set.name,
            source_path=str(model_set.source_path),
            resolution_source="escalation_trigger",
            warnings=[],
        )
    return resolve_profile_model(profile, model_set)


def model_set_summary(model_set: ModelSet, *, strict: bool = False) -> dict[str, Any]:
    validation = validate_model_set(model_set, strict=strict)
    return {
        "name": model_set.name,
        "description": model_set.description,
        "source": model_set.source,
        "source_path": str(model_set.source_path),
        "families": {name: family.__dict__ for name, family in model_set.families.items()},
        "profiles": model_set.profiles,
        "task_routing": model_set.task_routing,
        "escalation": model_set.escalation,
        "budget": model_set.budget,
        "validation": validation.as_dict(),
    }


def to_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, default=str)
