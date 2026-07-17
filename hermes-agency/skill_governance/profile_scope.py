"""Authenticated active-profile confinement for local hub acquisition."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from hermes_constants import get_hermes_home

_PROFILE_RE = re.compile(r"^agency-[a-z0-9][a-z0-9-]{0,62}$")


@dataclass(frozen=True)
class ProfileScope:
    name: str
    home: Path
    device: int
    inode: int
    uid: int


def managed_profile_names() -> set[str]:
    registry = Path(__file__).parents[1] / "pool" / "registry_definition.json"
    data = json.loads(registry.read_text(encoding="utf-8"))
    return {
        str(item["name"])
        for item in data.get("agents", [])
        if isinstance(item, dict) and _PROFILE_RE.fullmatch(str(item.get("name") or ""))
    }


def resolve_authenticated_profile(*, context_profile: str | None = None) -> ProfileScope:
    home = Path(get_hermes_home()).expanduser().resolve(strict=True)
    if home.parent.name != "profiles" or not _PROFILE_RE.fullmatch(home.name):
        raise PermissionError("active Hermes home is not a canonical managed Agency profile")
    if home.name == "agency-orchestrator" or home.name not in managed_profile_names():
        raise PermissionError("profile is not eligible for local skill acquisition")
    env_profile = os.getenv("HERMES_PROFILE", "").strip()
    if env_profile and env_profile != home.name:
        raise PermissionError("HERMES_PROFILE does not match authenticated Hermes home")
    if context_profile and context_profile != home.name:
        raise PermissionError("runtime profile does not match authenticated Hermes home")
    info = home.lstat()
    config = home / "config.yaml"
    config_info = config.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise PermissionError("profile home must be a non-symlink directory")
    if stat.S_ISLNK(config_info.st_mode) or not stat.S_ISREG(config_info.st_mode):
        raise PermissionError("profile config must be a non-symlink regular file")
    if info.st_uid != os.geteuid() or config_info.st_uid != os.geteuid():
        raise PermissionError("active profile home and config must be owned by the worker UID")
    return ProfileScope(home.name, home, info.st_dev, info.st_ino, info.st_uid)
