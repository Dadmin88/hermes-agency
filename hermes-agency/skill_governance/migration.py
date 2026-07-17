"""Dry-run-first migration for Agency profile skill gates and shared discovery."""

from __future__ import annotations

import hashlib
import json
import os
import re
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
    profile_device: int | None = None
    profile_inode: int | None = None
    config_device: int | None = None
    config_inode: int | None = None
    config_digest: str | None = None

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


@dataclass
class _PinnedConfig:
    profile: str
    directory_fd: int
    config_fd: int
    original: bytes
    mode: int

    def close(self) -> None:
        os.close(self.config_fd)
        os.close(self.directory_fd)


def _read_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _pin_config(root_fd: int, plan: MigrationPlan) -> _PinnedConfig:
    directory_fd = os.open(
        plan.profile, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
    )
    try:
        directory_info = os.fstat(directory_fd)
        if (directory_info.st_dev, directory_info.st_ino) != (
            plan.profile_device,
            plan.profile_inode,
        ):
            raise RuntimeError("profile directory changed after migration planning")
        config_fd = os.open("config.yaml", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        config_info = os.fstat(config_fd)
        if not stat.S_ISREG(config_info.st_mode) or config_info.st_nlink != 1:
            raise RuntimeError("profile config is not one regular file")
        original = _read_fd(config_fd)
        if (config_info.st_dev, config_info.st_ino) != (
            plan.config_device,
            plan.config_inode,
        ) or hashlib.sha256(original).hexdigest() != plan.config_digest:
            raise RuntimeError("profile config changed after migration planning")
        return _PinnedConfig(
            plan.profile,
            directory_fd,
            config_fd,
            original,
            config_info.st_mode & 0o777,
        )
    except Exception:
        os.close(directory_fd)
        raise


def _replace_pinned(pin: _PinnedConfig, data: bytes, suffix: str) -> None:
    name = f".config.yaml.{suffix}.{uuid.uuid4().hex}.tmp"
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        pin.mode,
        dir_fd=pin.directory_fd,
    )
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.fchmod(fd, pin.mode)
    finally:
        os.close(fd)
    try:
        os.rename(
            name,
            "config.yaml",
            src_dir_fd=pin.directory_fd,
            dst_dir_fd=pin.directory_fd,
        )
        os.fsync(pin.directory_fd)
    except Exception:
        try:
            os.unlink(name, dir_fd=pin.directory_fd)
        except FileNotFoundError:
            pass
        raise


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
            profile_info = path.parent.stat()
            config_info = path.stat()
            config_bytes = path.read_bytes()
            plans.append(
                MigrationPlan(
                    profile,
                    str(path),
                    status,
                    gate,
                    gate_target,
                    present,
                    shadows,
                    profile_device=profile_info.st_dev,
                    profile_inode=profile_info.st_ino,
                    config_device=config_info.st_dev,
                    config_inode=config_info.st_ino,
                    config_digest=hashlib.sha256(config_bytes).hexdigest(),
                )
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
    if dry_run:
        before = {
            plan.config_path: Path(plan.config_path).read_bytes()
            for plan in plans
            if plan.status != "error"
        }
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
    migration_id = f"sgm_{uuid.uuid4().hex}"
    results: list[dict[str, Any]] = []
    backup_base = backup_root / migration_id
    backup_base.mkdir(parents=True, mode=0o700)
    root_fd = os.open(profiles_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    pinned: list[tuple[MigrationPlan, _PinnedConfig, bytes, Path]] = []
    try:
        # Pin and render every target before the first mutation. A profile swap at
        # the plan/apply boundary is rejected by inode and digest comparison.
        for plan in plans:
            pin = _pin_config(root_fd, plan)
            try:
                loaded = yaml.safe_load(pin.original.decode("utf-8"))
                data = {} if loaded is None else loaded
                if not isinstance(data, dict):
                    raise ValueError("config.yaml must contain a mapping")
                if plan.status == "unchanged":
                    pinned.append((plan, pin, pin.original, Path()))
                    continue
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
                backup = backup_base / plan.profile / "config.yaml"
                backup.parent.mkdir(parents=True)
                backup.write_bytes(pin.original)
                backup.chmod(0o600)
                metadata = {
                    "profile": plan.profile,
                    "config_path": plan.config_path,
                    "backup_path": str(backup),
                    "before_sha256": hashlib.sha256(pin.original).hexdigest(),
                    "after_sha256": hashlib.sha256(rendered).hexdigest(),
                }
                (backup.parent / "metadata.json").write_text(
                    json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
                )
                pinned.append((plan, pin, rendered, backup))
            except Exception:
                pin.close()
                raise
        changed: list[tuple[_PinnedConfig, bytes]] = []
        try:
            for plan, pin, rendered, backup in pinned:
                if plan.status == "unchanged":
                    results.append(plan.as_dict())
                    continue
                _replace_pinned(pin, rendered, migration_id)
                changed.append((pin, pin.original))
                results.append(
                    {
                        **plan.as_dict(),
                        "status": "updated",
                        "backup_path": str(backup),
                        "before_sha256": hashlib.sha256(pin.original).hexdigest(),
                        "after_sha256": hashlib.sha256(rendered).hexdigest(),
                    }
                )
        except Exception as exc:
            rollback_errors: list[str] = []
            for pin, original in reversed(changed):
                try:
                    _replace_pinned(pin, original, f"{migration_id}.rollback")
                except Exception as rollback_exc:
                    rollback_errors.append(
                        f"{pin.profile}: {type(rollback_exc).__name__}: {rollback_exc}"
                    )
            results.append({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
            results = [
                {**item, "status": "rolled_back"} if item.get("status") == "updated" else item
                for item in results
            ]
            if rollback_errors:
                raise RuntimeError(f"migration rollback failed: {rollback_errors}") from exc
    except Exception as exc:
        return {
            "ok": False,
            "dry_run": False,
            "migration_id": migration_id,
            "results": [*results, {"status": "error", "error": f"{type(exc).__name__}: {exc}"}],
            "rolled_back": any(item.get("status") == "rolled_back" for item in results),
        }
    finally:
        for _plan, pin, _rendered, _backup in pinned:
            try:
                pin.close()
            except OSError:
                pass
        os.close(root_fd)
    return {
        "ok": not any(item.get("status") == "error" for item in results),
        "dry_run": False,
        "migration_id": migration_id,
        "results": results,
        "rolled_back": any(item.get("status") == "rolled_back" for item in results),
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
    root = backup_root / migration_id
    if root.is_symlink() or not root.is_dir():
        return {
            "ok": False,
            "migration_id": migration_id,
            "restored": [],
            "errors": ["backup root is missing or unsafe"],
        }
    root_fd = os.open(profiles_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    prepared: list[tuple[str, _PinnedConfig, bytes]] = []
    errors: list[str] = []
    try:
        # Validate and pin every live target and every backup before replacing one.
        for profile_dir in sorted(root.iterdir()):
            if not profile_dir.name.startswith("agency-"):
                continue
            try:
                profile = _profile_name(profile_dir.name)
                if profile_dir.is_symlink() or not profile_dir.is_dir():
                    raise ValueError("backup profile directory is unsafe")
                backup = profile_dir / "config.yaml"
                metadata_path = profile_dir / "metadata.json"
                for source in (backup, metadata_path):
                    info = source.lstat()
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or stat.S_ISLNK(info.st_mode)
                        or info.st_nlink != 1
                    ):
                        raise ValueError("migration backup contains an unsafe entry")
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                backup_bytes = backup.read_bytes()
                if hashlib.sha256(backup_bytes).hexdigest() != metadata["before_sha256"]:
                    raise ValueError("migration backup digest is invalid")
                target = _config_path(profiles_root, profile)
                target_info = target.stat()
                current = target.read_bytes()
                if hashlib.sha256(current).hexdigest() != metadata["after_sha256"]:
                    raise ValueError("current config differs from migration output")
                plan = MigrationPlan(
                    profile,
                    str(target),
                    "change",
                    None,
                    False,
                    False,
                    (),
                    profile_device=target.parent.stat().st_dev,
                    profile_inode=target.parent.stat().st_ino,
                    config_device=target_info.st_dev,
                    config_inode=target_info.st_ino,
                    config_digest=hashlib.sha256(current).hexdigest(),
                )
                prepared.append((profile, _pin_config(root_fd, plan), backup_bytes))
            except Exception as exc:
                errors.append(f"{profile_dir.name}: {type(exc).__name__}: {exc}")
        if errors:
            return {"ok": False, "migration_id": migration_id, "restored": [], "errors": errors}
        restored: list[str] = []
        changed: list[tuple[_PinnedConfig, bytes]] = []
        try:
            for profile, pin, backup_bytes in prepared:
                _replace_pinned(pin, backup_bytes, f"{migration_id}.restore")
                changed.append((pin, pin.original))
                restored.append(profile)
        except Exception as exc:
            errors.append(f"{profile}: {type(exc).__name__}: {exc}")
            rollback_errors = []
            for pin, original in reversed(changed):
                try:
                    _replace_pinned(pin, original, f"{migration_id}.rollback")
                except Exception as rollback_exc:
                    rollback_errors.append(
                        f"{pin.profile}: {type(rollback_exc).__name__}: {rollback_exc}"
                    )
            errors.extend(rollback_errors)
            restored.clear()
        return {
            "ok": not errors,
            "migration_id": migration_id,
            "restored": restored,
            "errors": errors,
        }
    finally:
        for _profile, pin, _backup in prepared:
            try:
                pin.close()
            except OSError:
                pass
        os.close(root_fd)
