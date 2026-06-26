"""Safe config writer for applying Hermes Agency model sets to profiles."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - Hermes normally depends on PyYAML
    yaml = None  # type: ignore[assignment]

from .model_sets import ModelSet, ResolvedProfileModel, resolve_profile_model


@dataclass(frozen=True)
class ProfileWriteResult:
    profile: str
    config_path: str
    status: str
    current: str | None = None
    target: str | None = None
    backup_path: str | None = None
    message: str | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "config_path": self.config_path,
            "status": self.status,
            "current": self.current,
            "target": self.target,
            "backup_path": self.backup_path,
            "message": self.message,
            "warnings": self.warnings,
        }


def _require_yaml() -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to write Hermes profile config.yaml files")


def hermes_profiles_dir() -> Path:
    try:
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home()).expanduser()
    except Exception:
        home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
    if home.parent.name == "profiles":
        return home.parent
    return home / "profiles"


def installed_agency_profiles(base: Path | None = None) -> list[str]:
    root = base or hermes_profiles_dir()
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir() and path.name.startswith("agency-"))


def _load_config(path: Path) -> dict[str, Any]:
    _require_yaml()
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _atomic_yaml_write(path: Path, data: dict[str, Any]) -> None:
    _require_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def _backup_path(config_path: Path, backup_id: str) -> Path:
    return config_path.parent / ".agency-model-set-backups" / backup_id / "config.yaml"


def render_target_model(resolved: ResolvedProfileModel) -> dict[str, str]:
    """Render the Hermes-compatible model block used by installed profiles."""
    return {"provider": resolved.provider, "default": resolved.model}


def profile_plan(profile: str, model_set: ModelSet, *, base: Path | None = None) -> ProfileWriteResult:
    root = base or hermes_profiles_dir()
    config_path = root / profile / "config.yaml"
    resolved = resolve_profile_model(profile, model_set)
    target_model = render_target_model(resolved)
    target_label = f"{resolved.provider}/{resolved.model}"
    current_label = None
    status = "missing"
    message = "Installed profile config.yaml was not found"
    if config_path.exists():
        data = _load_config(config_path)
        current = data.get("model") if isinstance(data.get("model"), dict) else {}
        current_provider = current.get("provider") if isinstance(current, dict) else None
        current_model = current.get("default") if isinstance(current, dict) else None
        current_label = f"{current_provider}/{current_model}" if current_provider or current_model else None
        status = "unchanged" if current == target_model else "drift"
        message = "Already matches target model" if status == "unchanged" else "Model block differs from target"
    return ProfileWriteResult(
        profile=profile,
        config_path=str(config_path),
        status=status,
        current=current_label,
        target=target_label,
        message=message,
        warnings=resolved.warnings,
    )


def plan_model_set(model_set: ModelSet, *, profiles: list[str] | None = None, base: Path | None = None) -> list[ProfileWriteResult]:
    selected = profiles or installed_agency_profiles(base)
    return [profile_plan(profile, model_set, base=base) for profile in selected]


def apply_model_set(
    model_set: ModelSet,
    *,
    profiles: list[str] | None = None,
    base: Path | None = None,
    dry_run: bool = True,
    backup: bool = True,
    yes: bool = False,
) -> dict[str, Any]:
    if not dry_run and not yes:
        raise ValueError("Refusing non-dry-run apply without yes=True")
    root = base or hermes_profiles_dir()
    selected = profiles or installed_agency_profiles(root)
    if not selected:
        return {
            "ok": True,
            "dry_run": dry_run,
            "backup_id": None,
            "results": [],
            "message": "No installed agency-* profiles found. Run `hermes agency staff install` first.",
        }
    backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") if backup and not dry_run else None
    results: list[ProfileWriteResult] = []
    for profile in selected:
        planned = profile_plan(profile, model_set, base=root)
        config_path = Path(planned.config_path)
        if planned.status == "missing":
            results.append(planned)
            continue
        if dry_run or planned.status == "unchanged":
            results.append(planned)
            continue
        data = _load_config(config_path)
        backup_path = None
        if backup_id:
            backup_path = _backup_path(config_path, backup_id)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config_path, backup_path)
            meta = {
                "profile": profile,
                "config_path": str(config_path),
                "backup_path": str(backup_path),
                "model_set": model_set.name,
                "created_at": backup_id,
            }
            (backup_path.parent / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        resolved = resolve_profile_model(profile, model_set)
        data["model"] = render_target_model(resolved)
        agency = data.setdefault("agency", {})
        if not isinstance(agency, dict):
            agency = {}
            data["agency"] = agency
        models = agency.setdefault("models", {})
        if not isinstance(models, dict):
            models = {}
            agency["models"] = models
        models.update(
            {
                "active_set": model_set.name,
                "applied_family": resolved.family,
                "applied_at": datetime.now(timezone.utc).isoformat(),
                "managed_by": "hermes-agency",
            }
        )
        _atomic_yaml_write(config_path, data)
        results.append(
            ProfileWriteResult(
                profile=profile,
                config_path=str(config_path),
                status="updated",
                current=planned.current,
                target=planned.target,
                backup_path=str(backup_path) if backup_path else None,
                message="Updated model block only",
                warnings=planned.warnings,
            )
        )
    return {
        "ok": True,
        "dry_run": dry_run,
        "backup_id": backup_id,
        "results": [result.as_dict() for result in results],
    }


def restore_backup(backup_id: str, *, profiles: list[str] | None = None, base: Path | None = None, force: bool = False) -> dict[str, Any]:
    root = base or hermes_profiles_dir()
    selected = profiles or installed_agency_profiles(root)
    restored: list[dict[str, Any]] = []
    errors: list[str] = []
    for profile in selected:
        config_path = root / profile / "config.yaml"
        backup_path = _backup_path(config_path, backup_id)
        meta_path = backup_path.parent / "metadata.json"
        if not backup_path.exists():
            continue
        if meta_path.exists() and not force:
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("config_path") != str(config_path):
                    errors.append(f"{profile}: backup metadata path mismatch; use --force to override")
                    continue
            except Exception as exc:
                errors.append(f"{profile}: could not read backup metadata: {exc}")
                continue
        shutil.copy2(backup_path, config_path)
        restored.append({"profile": profile, "config_path": str(config_path), "backup_path": str(backup_path)})
    return {"ok": not errors, "restored": restored, "errors": errors, "backup_id": backup_id}
