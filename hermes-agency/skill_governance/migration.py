"""Dry-run-first migration for Agency profile skill gates and shared discovery."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .authority import PrincipalAuthenticator, PromoterAuthority

_PROFILE_RE = re.compile(r"^agency-[a-z0-9][a-z0-9-]{0,62}$")


def _profile_name(value: str) -> str:
    if not _PROFILE_RE.fullmatch(value):
        raise ValueError(f"invalid managed profile name: {value!r}")
    return value


@dataclass(frozen=True)
class MigrationPlan:
    profile: str
    config_path: str
    status: str
    current_write_approval: bool | None
    target_write_approval: bool
    external_dir_present: bool
    shadows: tuple[str, ...]
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["shadows"] = list(self.shadows)
        return data


def _read_mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("config.yaml must contain a mapping")
    return loaded


def _canonical(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _config_path(profiles_root: Path, profile: str) -> Path:
    root = profiles_root.absolute()
    profile_dir = root / profile
    info = profile_dir.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("profile root is not a non-symlink directory")
    path = profile_dir / "config.yaml"
    config_info = path.lstat()
    if not stat.S_ISREG(config_info.st_mode) or stat.S_ISLNK(config_info.st_mode):
        raise ValueError("config.yaml is missing or not a regular file")
    if path.parent.resolve(strict=True) != profile_dir:
        raise ValueError("profile config escapes profiles_root")
    return path


def plan_migration(
    profiles_root: Path, shared_dir: Path, profiles: list[str] | None = None
) -> list[MigrationPlan]:
    if profiles is not None:
        selected = profiles
    elif profiles_root.is_dir():
        selected = sorted(
            path.name
            for path in profiles_root.iterdir()
            if path.is_dir() and not path.is_symlink() and path.name.startswith("agency-")
        )
    else:
        selected = []
    target = _canonical(shared_dir)
    plans: list[MigrationPlan] = []
    for raw_profile in selected:
        try:
            profile = _profile_name(raw_profile)
        except ValueError as exc:
            plans.append(MigrationPlan(raw_profile, "", "error", None, True, False, (), str(exc)))
            continue
        path = profiles_root / profile / "config.yaml"
        gate_target = profile != "agency-orchestrator"
        try:
            path = _config_path(profiles_root, profile)
            data = _read_mapping(path)
            skills = data.get("skills") if isinstance(data.get("skills"), dict) else {}
            gate = (
                skills.get("write_approval")
                if isinstance(skills.get("write_approval"), bool)
                else None
            )
            external = skills.get("external_dirs")
            if external is None:
                external_dirs: list[str] = []
            elif isinstance(external, list) and all(isinstance(item, str) for item in external):
                external_dirs = external
            else:
                raise ValueError("skills.external_dirs must be a list of strings")
            present = any(_canonical(item) == target for item in external_dirs)
            local_root = profiles_root / profile / "skills"
            shadows = (
                tuple(sorted({p.parent.name for p in local_root.glob("**/SKILL.md")}))
                if local_root.is_dir()
                else ()
            )
            status = "unchanged" if gate == gate_target and present else "change"
            plans.append(
                MigrationPlan(profile, str(path), status, gate, gate_target, present, shadows)
            )
        except (OSError, ValueError, yaml.YAMLError) as exc:
            plans.append(
                MigrationPlan(profile, str(path), "error", None, gate_target, False, (), str(exc))
            )
    return plans


def apply_migration(
    profiles_root: Path,
    shared_dir: Path,
    backup_root: Path,
    *,
    profiles: list[str] | None = None,
    dry_run: bool = True,
    yes: bool = False,
    authority: PromoterAuthority | None = None,
    authenticator: PrincipalAuthenticator | None = None,
) -> dict[str, Any]:
    if not dry_run and not yes:
        raise ValueError("refusing migration apply without yes=True")
    plans = plan_migration(profiles_root, shared_dir, profiles)
    if not dry_run and (
        authority is None or authenticator is None or not authenticator.verify_promoter(authority)
    ):
        raise PermissionError("migration apply requires authenticated promoter authority")
    migration_id = f"sgm_{uuid.uuid4().hex}"
    before = {
        plan.config_path: Path(plan.config_path).read_bytes()
        for plan in plans
        if plan.status != "error"
    }
    if dry_run:
        return {
            "ok": not any(plan.status == "error" for plan in plans),
            "dry_run": True,
            "migration_id": None,
            "results": [plan.as_dict() for plan in plans],
            "bytes_unchanged": all(
                Path(path).read_bytes() == content for path, content in before.items()
            ),
        }
    if any(plan.status == "error" for plan in plans):
        return {
            "ok": False,
            "dry_run": False,
            "migration_id": None,
            "results": [plan.as_dict() for plan in plans],
            "rolled_back": False,
        }
    results: list[dict[str, Any]] = []
    backup_base = backup_root / migration_id
    backup_base.mkdir(parents=True, mode=0o700)
    changed: list[tuple[Path, bytes]] = []
    for plan in plans:
        if plan.status in {"error", "unchanged"}:
            results.append(plan.as_dict())
            continue
        path = Path(plan.config_path)
        try:
            original = path.read_bytes()
            backup = backup_base / plan.profile / "config.yaml"
            backup.parent.mkdir(parents=True)
            shutil.copy2(path, backup)
            data = _read_mapping(path)
            skills = data.setdefault("skills", {})
            if not isinstance(skills, dict):
                raise ValueError("skills must be a mapping")
            skills["write_approval"] = plan.target_write_approval
            external = skills.setdefault("external_dirs", [])
            if not isinstance(external, list) or not all(
                isinstance(item, str) for item in external
            ):
                raise ValueError("skills.external_dirs must be a list of strings")
            if not any(_canonical(item) == _canonical(shared_dir) for item in external):
                external.append(str(_canonical(shared_dir)))
            rendered = yaml.safe_dump(data, sort_keys=False).encode()
            temp = path.with_name(f".{path.name}.{migration_id}.tmp")
            temp.write_bytes(rendered)
            os.chmod(temp, path.stat().st_mode & 0o777)
            os.replace(temp, path)
            changed.append((path, original))
            metadata = {
                "profile": plan.profile,
                "config_path": str(path),
                "backup_path": str(backup),
                "before_sha256": hashlib.sha256(original).hexdigest(),
                "after_sha256": hashlib.sha256(rendered).hexdigest(),
            }
            (backup.parent / "metadata.json").write_text(
                json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
            )
            results.append({**plan.as_dict(), "status": "updated", **metadata})
        except Exception as exc:
            results.append(
                {**plan.as_dict(), "status": "error", "error": f"{type(exc).__name__}: {exc}"}
            )
            for changed_path, original_bytes in reversed(changed):
                restore_temp = changed_path.with_name(
                    f".{changed_path.name}.{migration_id}.rollback"
                )
                restore_temp.write_bytes(original_bytes)
                os.replace(restore_temp, changed_path)
            results = [
                {**item, "status": "rolled_back"} if item.get("status") == "updated" else item
                for item in results
            ]
            break
    return {
        "ok": not any(item["status"] == "error" for item in results),
        "dry_run": False,
        "migration_id": migration_id,
        "results": results,
        "rolled_back": any(item["status"] == "rolled_back" for item in results),
    }


def restore_migration(
    profiles_root: Path,
    backup_root: Path,
    migration_id: str,
    *,
    yes: bool = False,
    authority: PromoterAuthority | None = None,
    authenticator: PrincipalAuthenticator | None = None,
) -> dict[str, Any]:
    if not yes:
        raise ValueError("refusing migration restore without yes=True")
    if authority is None or authenticator is None or not authenticator.verify_promoter(authority):
        raise PermissionError("migration restore requires authenticated promoter authority")
    restored: list[str] = []
    errors: list[str] = []
    root = backup_root / migration_id
    prepared: list[tuple[str, Path, Path, bytes]] = []
    for profile_dir in sorted(root.glob("agency-*")):
        backup = profile_dir / "config.yaml"
        metadata_path = profile_dir / "metadata.json"
        try:
            profile = _profile_name(profile_dir.name)
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            target = _config_path(profiles_root, profile)
            backup_bytes = backup.read_bytes()
            if hashlib.sha256(backup_bytes).hexdigest() != metadata["before_sha256"]:
                raise ValueError("migration backup digest is invalid")
            current = target.read_bytes()
            if hashlib.sha256(current).hexdigest() != metadata["after_sha256"]:
                raise ValueError("current config differs from migration output")
            prepared.append((profile, target, backup, current))
        except Exception as exc:
            errors.append(f"{profile_dir.name}: {type(exc).__name__}: {exc}")
    if errors:
        return {"ok": False, "migration_id": migration_id, "restored": [], "errors": errors}
    changed: list[tuple[Path, bytes]] = []
    for profile, target, backup, current in prepared:
        try:
            temp = target.with_name(f".{target.name}.{migration_id}.restore")
            shutil.copy2(backup, temp)
            os.replace(temp, target)
            changed.append((target, current))
            restored.append(profile)
        except Exception as exc:
            errors.append(f"{profile}: {type(exc).__name__}: {exc}")
            for changed_path, original in reversed(changed):
                temp = changed_path.with_name(f".{changed_path.name}.{migration_id}.rollback")
                temp.write_bytes(original)
                os.replace(temp, changed_path)
            restored.clear()
            break
    return {"ok": not errors, "migration_id": migration_id, "restored": restored, "errors": errors}
