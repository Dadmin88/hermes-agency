"""Agency-facing adapter for native Hermes Agent Mixture-of-Agents.

This module intentionally delegates execution/config normalization to Hermes
Agent. Hermes Agency adds policy, visibility, recommendation metadata, and
optional orchestration around the native ``provider=moa`` surface; it does not
own a reference-model fan-out loop or aggregator runtime.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .config import AgencyConfig, get_config

HIGH_LEVERAGE_TRIGGERS = (
    "architecture",
    "security",
    "release",
    "destructive_change",
    "blocker",
)

_TRIGGER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "architecture": (
        "architecture",
        "architectural",
        "design review",
        "system design",
        "refactor",
        "routing",
        "orchestrator",
        "adapter",
    ),
    "security": (
        "security",
        "secret",
        "token",
        "auth",
        "permission",
        "exploit",
        "vulnerability",
        "ssrf",
        "destructive",
    ),
    "release": ("release", "deploy", "deployment", "publish", "pypi", "tag", "ship"),
    "destructive_change": (
        "delete",
        "remove",
        "drop",
        "migration",
        "overwrite",
        "destructive",
        "irreversible",
    ),
    "blocker": ("blocker", "blocked", "stuck", "critical", "production down"),
}


class NativeMoAUnavailableError(RuntimeError):
    """Raised when the installed Hermes Agent does not expose native MoA."""


def _native_modules() -> tuple[Any, Any]:
    try:
        from agent import moa_loop
        from hermes_cli import moa_config
    except Exception as exc:  # pragma: no cover - depends on installed Hermes Agent
        raise NativeMoAUnavailableError(f"native Hermes Agent MoA is unavailable: {exc}") from exc
    return moa_config, moa_loop


def _load_native_config() -> dict[str, Any]:
    from hermes_cli.config import load_config

    data = load_config()
    return data if isinstance(data, dict) else {}


def _provider(slot: Any) -> str:
    if not isinstance(slot, dict):
        return ""
    return str(slot.get("provider") or "").strip().lower()


def _model_pair(slot: Any) -> dict[str, str]:
    if not isinstance(slot, dict):
        return {"provider": "", "model": ""}
    return {
        "provider": str(slot.get("provider") or "").strip(),
        "model": str(slot.get("model") or "").strip(),
    }


def _raw_preset(raw_moa: Any, name: str) -> dict[str, Any] | None:
    if not isinstance(raw_moa, dict):
        return None
    raw_presets = raw_moa.get("presets")
    if isinstance(raw_presets, dict) and isinstance(raw_presets.get(name), dict):
        return raw_presets[name]
    if name == str(raw_moa.get("default_preset") or "default") or "presets" not in raw_moa:
        return raw_moa
    return None


def _validation_warnings(
    name: str, preset: dict[str, Any], raw_preset: dict[str, Any] | None = None
) -> list[str]:
    warnings: list[str] = []
    refs = preset.get("reference_models") or []
    if bool(preset.get("enabled", True)) and not refs:
        warnings.append("enabled preset has no reference models")
    aggregator = preset.get("aggregator") or {}
    if _provider(aggregator) == "moa":
        warnings.append("aggregator provider must not be moa")
    for index, ref in enumerate(refs, start=1):
        if _provider(ref) == "moa":
            warnings.append(f"reference model {index} provider must not be moa")

    if raw_preset:
        raw_aggregator = raw_preset.get("aggregator") if isinstance(raw_preset, dict) else None
        if _provider(raw_aggregator) == "moa":
            warnings.append("raw aggregator provider is moa; native config will reject/drop it")
        raw_refs = raw_preset.get("reference_models") if isinstance(raw_preset, dict) else None
        if isinstance(raw_refs, list):
            for index, ref in enumerate(raw_refs, start=1):
                if _provider(ref) == "moa":
                    warnings.append(
                        f"raw reference model {index} provider is moa; native config will reject/drop it"
                    )

    if (
        not isinstance(aggregator, dict)
        or not aggregator.get("provider")
        or not aggregator.get("model")
    ):
        warnings.append("aggregator provider/model is incomplete")
    return sorted(set(warnings))


def _policy(config: AgencyConfig | None = None) -> AgencyConfig:
    return config or get_config()


def _native_moa_config() -> tuple[dict[str, Any], dict[str, Any], Any]:
    moa_config, _moa_loop = _native_modules()
    native_config = _load_native_config()
    raw_moa = native_config.get("moa") if isinstance(native_config, dict) else {}
    normalized = moa_config.normalize_moa_config(raw_moa or {})
    return native_config, normalized, moa_config


def _effective_preset_name(
    normalized: dict[str, Any], agency_config: AgencyConfig | None = None
) -> str:
    policy = _policy(agency_config).moa
    override = (policy.default_preset or "").strip()
    if override:
        return override
    return str(normalized.get("default_preset") or "default")


def validate_native_moa_available(
    preset_name: str | None = None, *, agency_config: AgencyConfig | None = None
) -> dict[str, Any]:
    """Validate that Hermes Agent native MoA is installed and the preset is usable."""

    try:
        native_config, normalized, moa_config = _native_moa_config()
    except NativeMoAUnavailableError as exc:
        return {"ok": False, "available": False, "error": str(exc), "warnings": []}
    except Exception as exc:
        return {
            "ok": False,
            "available": False,
            "error": f"failed to load native MoA config: {type(exc).__name__}: {exc}",
            "warnings": [],
        }

    raw_moa = native_config.get("moa") if isinstance(native_config, dict) else {}
    presets = normalized.get("presets") if isinstance(normalized, dict) else {}
    preset = (preset_name or _effective_preset_name(normalized, agency_config)).strip()
    warnings: list[str] = []
    if preset not in presets:
        return {
            "ok": False,
            "available": True,
            "error": f"native MoA preset not found: {preset}",
            "preset": preset,
            "native_default_preset": normalized.get("default_preset"),
            "warnings": warnings,
        }
    try:
        resolved = moa_config.resolve_moa_preset(raw_moa or {}, preset)
    except KeyError:
        return {
            "ok": False,
            "available": True,
            "error": f"native MoA preset not found: {preset}",
            "preset": preset,
            "native_default_preset": normalized.get("default_preset"),
            "warnings": warnings,
        }
    except Exception as exc:
        return {
            "ok": False,
            "available": True,
            "error": f"failed to resolve native MoA preset {preset!r}: {type(exc).__name__}: {exc}",
            "preset": preset,
            "native_default_preset": normalized.get("default_preset"),
            "warnings": warnings,
        }
    warnings.extend(_validation_warnings(preset, resolved, _raw_preset(raw_moa, preset)))
    return {
        "ok": not warnings,
        "available": True,
        "preset": preset,
        "native_default_preset": normalized.get("default_preset"),
        "warnings": warnings,
    }


def get_native_moa_status(*, agency_config: AgencyConfig | None = None) -> dict[str, Any]:
    """Return Agency policy plus native Hermes Agent MoA status."""

    policy = _policy(agency_config)
    try:
        native_config, normalized, _moa_config = _native_moa_config()
    except Exception as exc:
        return {
            "ok": False,
            "available": False,
            "error": str(exc),
            "agency": policy.moa.as_dict(),
            "native": {},
            "effective_preset": None,
            "validation": {"ok": False, "warnings": []},
        }

    presets = normalized.get("presets") or {}
    effective = _effective_preset_name(normalized, policy)
    validation = validate_native_moa_available(effective, agency_config=policy)
    native_enabled = bool(normalized.get("enabled", False))
    return {
        "ok": bool(validation.get("available")) and effective in presets,
        "available": True,
        "agency": policy.moa.as_dict(),
        "native": {
            "default_preset": normalized.get("default_preset"),
            "active_preset": normalized.get("active_preset"),
            "enabled": native_enabled,
            "preset_names": list(presets.keys()),
            "preset_count": len(presets),
            "top_level_moa_configured": "moa" in native_config,
        },
        "agency_default_preset_override": policy.moa.default_preset,
        "effective_preset": effective,
        "kanban_tracking": policy.moa.kanban_tracking,
        "auto_moa": policy.moa.allow_auto_moa,
        "require_confirmation": policy.moa.require_confirmation,
        "validation": validation,
    }


def list_native_moa_presets(*, agency_config: AgencyConfig | None = None) -> list[dict[str, Any]]:
    """List normalized native MoA presets for Agency display surfaces."""

    native_config, normalized, _moa_config = _native_moa_config()
    raw_moa = native_config.get("moa") if isinstance(native_config, dict) else {}
    native_default = str(normalized.get("default_preset") or "")
    effective = _effective_preset_name(normalized, agency_config)
    presets = normalized.get("presets") or {}
    rows: list[dict[str, Any]] = []
    for name, preset in presets.items():
        refs = preset.get("reference_models") or []
        row = {
            "name": name,
            "enabled": bool(preset.get("enabled", True)),
            "reference_count": len(refs),
            "reference_models": [_model_pair(item) for item in refs],
            "aggregator": _model_pair(preset.get("aggregator") or {}),
            "reference_temperature": preset.get("reference_temperature"),
            "aggregator_temperature": preset.get("aggregator_temperature"),
            "max_tokens": preset.get("max_tokens"),
            "is_native_default": name == native_default,
            "is_agency_effective_default": name == effective,
            "validation_warnings": _validation_warnings(name, preset, _raw_preset(raw_moa, name)),
        }
        rows.append(row)
    return rows


def get_native_moa_preset(
    name: str, *, agency_config: AgencyConfig | None = None
) -> dict[str, Any]:
    """Return one normalized native MoA preset plus validation metadata."""

    clean = str(name or "").strip()
    if not clean:
        raise KeyError("preset name is required")
    native_config, normalized, moa_config = _native_moa_config()
    raw_moa = native_config.get("moa") if isinstance(native_config, dict) else {}
    preset = moa_config.resolve_moa_preset(raw_moa or {}, clean)
    return {
        "name": clean,
        "preset": deepcopy(preset),
        "native_default_preset": normalized.get("default_preset"),
        "is_native_default": clean == normalized.get("default_preset"),
        "is_agency_effective_default": clean == _effective_preset_name(normalized, agency_config),
        "validation_warnings": _validation_warnings(clean, preset, _raw_preset(raw_moa, clean)),
    }


def recommend_moa(
    task_text: str, trigger: str | None = None, *, agency_config: AgencyConfig | None = None
) -> dict[str, Any]:
    """Recommend native MoA for high-leverage Agency tasks without running it."""

    policy = _policy(agency_config)
    status = get_native_moa_status(agency_config=policy)
    clean_trigger = str(trigger or "").strip().lower()
    allowed = set(policy.moa.recommend_for_triggers)
    text = str(task_text or "")
    haystack = text.lower()
    matched_trigger = clean_trigger if clean_trigger in allowed else ""
    matched_keyword = ""
    if not matched_trigger:
        for candidate in policy.moa.recommend_for_triggers:
            for keyword in _TRIGGER_KEYWORDS.get(candidate, (candidate,)):
                if keyword in haystack:
                    matched_trigger = candidate
                    matched_keyword = keyword
                    break
            if matched_trigger:
                break

    recommended = bool(
        policy.enabled and policy.moa.enabled and status.get("available") and matched_trigger
    )
    reason = "MoA is not recommended for this routine task."
    if not policy.enabled:
        reason = "Agency is disabled."
    elif not policy.moa.enabled:
        reason = "Agency MoA policy is disabled; native Hermes MoA remains untouched."
    elif not status.get("available"):
        reason = f"Native Hermes Agent MoA unavailable: {status.get('error') or 'unknown error'}"
    elif matched_trigger:
        reason = f"Task matches Agency MoA trigger {matched_trigger!r}" + (
            f" via keyword {matched_keyword!r}." if matched_keyword else "."
        )

    return {
        "ok": True,
        "recommended": recommended,
        "preset": status.get("effective_preset"),
        "trigger": matched_trigger or clean_trigger or None,
        "reason": reason,
        "auto_run_allowed": bool(
            recommended and policy.moa.allow_auto_moa and not policy.moa.require_confirmation
        ),
        "requires_confirmation": bool(recommended and policy.moa.require_confirmation),
        "status": status,
    }


def set_agency_moa_policy(**updates: Any) -> dict[str, Any]:
    """Persist minimal ``agency.moa`` policy updates in the active profile config.

    This intentionally does not create/edit/delete native MoA presets. Native
    preset editing stays with Hermes Agent surfaces such as ``hermes moa configure``.
    """

    allowed = {
        "enabled",
        "default_preset",
        "allow_auto_moa",
        "require_confirmation",
        "kanban_tracking",
        "attach_trace_to_cards",
        "recommend_for_triggers",
    }
    clean_updates = {key: value for key, value in updates.items() if key in allowed}
    if not clean_updates:
        return {"ok": True, "changed": False, "updated": {}, "path": None}

    try:
        import yaml
        from hermes_cli.config import ensure_hermes_home, get_config_path
        from utils import atomic_yaml_write
    except Exception as exc:  # pragma: no cover - Hermes runtime dependency
        raise RuntimeError(f"Unable to update Hermes config: {exc}") from exc

    ensure_hermes_home()
    path = Path(get_config_path()).expanduser()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    config = data if isinstance(data, dict) else {}
    agency = config.setdefault("agency", {})
    if not isinstance(agency, dict):
        agency = {}
        config["agency"] = agency
    policy = agency.setdefault("moa", {})
    if not isinstance(policy, dict):
        policy = {}
        agency["moa"] = policy
    for key, value in clean_updates.items():
        if key == "default_preset" and str(value or "").strip() == "":
            policy[key] = None
        elif key == "recommend_for_triggers":
            policy[key] = [str(item).strip() for item in (value or []) if str(item).strip()]
        else:
            policy[key] = value
    atomic_yaml_write(path, config, sort_keys=False)
    return {"ok": True, "changed": True, "updated": clean_updates, "path": str(path)}
