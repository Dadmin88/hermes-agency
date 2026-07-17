"""Safe, compact shared-skill-pool projections for the Pool HTTP service.

The pool is an *availability* layer.  A profile's local skills remain higher
precedence; shared skills are effective only when that profile explicitly
configures the shared directory as an external skill directory.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

import yaml

_PROFILE_RE = re.compile(r"^agency-[a-z0-9][a-z0-9-]{0,62}$")
_SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _canonical(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _read_profile_config(profile_dir: Path) -> dict[str, Any]:
    config = profile_dir / "config.yaml"
    info = config.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError("profile config must be a regular non-symlink file")
    loaded = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError("profile config must contain a mapping")
    return loaded


def _skill_name(skill_file: Path) -> str | None:
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if text.startswith("---"):
        try:
            frontmatter = yaml.safe_load(text.split("---", 2)[1]) or {}
        except yaml.YAMLError:
            frontmatter = {}
        if isinstance(frontmatter, dict) and isinstance(frontmatter.get("name"), str):
            name = frontmatter["name"].strip()
            if _SKILL_RE.fullmatch(name):
                return name
    name = skill_file.parent.name
    return name if _SKILL_RE.fullmatch(name) else None


def _skills_in(root: Path, source: str) -> dict[str, dict[str, str]]:
    if not root.is_dir() or root.is_symlink():
        return {}
    out: dict[str, dict[str, str]] = {}
    for skill_file in sorted(root.glob("**/SKILL.md")):
        try:
            info = skill_file.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            continue
        name = _skill_name(skill_file)
        if name and name not in out:
            out[name] = {"name": name, "source": source}
    return out


def list_shared_skills(shared_skills_path: Path) -> list[dict[str, str]]:
    return list(_skills_in(_canonical(shared_skills_path), "shared").values())


def effective_agent_skills(
    *,
    profiles_root: Path,
    shared_skills_path: Path,
    profile_name: str,
) -> dict[str, Any]:
    """Return the effective non-secret skill projection for one managed profile."""
    if not _PROFILE_RE.fullmatch(profile_name):
        raise ValueError("invalid agency profile name")
    root = _canonical(profiles_root)
    profile_dir = root / profile_name
    try:
        profile_info = profile_dir.lstat()
    except FileNotFoundError as exc:
        raise KeyError(profile_name) from exc
    if stat.S_ISLNK(profile_info.st_mode) or not stat.S_ISDIR(profile_info.st_mode):
        raise ValueError("profile directory must be a non-symlink directory")

    config = _read_profile_config(profile_dir)
    skills_config = config.get("skills") if isinstance(config.get("skills"), dict) else {}
    external_dirs = (
        skills_config.get("external_dirs")
        if isinstance(skills_config.get("external_dirs"), list)
        else []
    )
    shared = _canonical(shared_skills_path)
    shared_enabled = any(
        isinstance(item, str) and _canonical(item) == shared for item in external_dirs
    )

    # Local wins exactly as the Hermes resolver does; an unavailable shared pool
    # never makes a local skill appear missing.
    effective = _skills_in(profile_dir / "skills", "local")
    shared_entries = _skills_in(shared, "shared")
    if shared_enabled:
        for name, entry in shared_entries.items():
            effective.setdefault(name, entry)

    return {
        "agent": profile_name,
        "sharedPoolEnabled": shared_enabled,
        "sharedPoolSkillCount": len(shared_entries),
        "skills": [effective[name] for name in sorted(effective)],
    }


def set_shared_pool_enabled(
    *,
    profiles_root: Path,
    shared_skills_path: Path,
    profile_name: str,
    enabled: bool,
) -> dict[str, Any]:
    """Atomically enable/disable the shared external directory for a profile."""
    if not _PROFILE_RE.fullmatch(profile_name):
        raise ValueError("invalid agency profile name")
    profile_dir = _canonical(profiles_root) / profile_name
    config_path = profile_dir / "config.yaml"
    config_info = config_path.lstat()
    config = _read_profile_config(profile_dir)
    shared = _canonical(shared_skills_path)
    skills = config.get("skills") if isinstance(config.get("skills"), dict) else {}
    external = skills.get("external_dirs") if isinstance(skills.get("external_dirs"), list) else []
    retained = [
        item for item in external if not (isinstance(item, str) and _canonical(item) == shared)
    ]
    if enabled:
        retained.append(str(shared))
    skills["external_dirs"] = retained
    config["skills"] = skills

    fd, raw_path = tempfile.mkstemp(prefix=".config.yaml.", suffix=".tmp", dir=profile_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(raw_path, stat.S_IMODE(config_info.st_mode))
        os.replace(raw_path, config_path)
    finally:
        try:
            os.unlink(raw_path)
        except FileNotFoundError:
            pass
    return effective_agent_skills(
        profiles_root=profiles_root,
        shared_skills_path=shared_skills_path,
        profile_name=profile_name,
    )
