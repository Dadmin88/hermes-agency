"""Install the Hermes Agency plugin symlink into Agency profile plugin dirs.

The pool manager wakes Hermes Agency-managed profiles as Agency nodes. For that
to work, those profiles need the user-plugin present at ``plugins/hermes-agency``.
These helpers are intentionally idempotent so roster refreshes and setup commands
can run them repeatedly without changing an already-correct install.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PLUGIN_NAME = "hermes-agency"


def plugin_source_dir() -> Path:
    """Return the canonical Hermes Agency plugin source directory."""

    override = os.environ.get("HERMES_AGENCY_PLUGIN_SOURCE", "").strip()
    source = Path(override).expanduser() if override else Path(__file__).resolve().parents[1]
    source = source.resolve()
    if not (source / "plugin.yaml").is_file() or not (source / "__init__.py").is_file():
        raise RuntimeError(f"Hermes Agency plugin source is not valid: {source}")
    return source


def hermes_root() -> Path:
    """Return the base ``~/.hermes`` directory even when running inside a profile."""

    try:
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home()).expanduser()
    except Exception:
        home = Path.home() / ".hermes"

    # Profiles have homes like ~/.hermes/profiles/gpt. The pool-wide profile
    # directory and default gateway plugin directory are both rooted at ~/.hermes.
    if home.parent.name == "profiles":
        return home.parent.parent
    return home


def profiles_dir(root: Path | None = None) -> Path:
    """Return the Hermes profiles directory."""

    return (root or hermes_root()) / "profiles"


def main_plugins_dir(root: Path | None = None) -> Path:
    """Return the default/gateway Hermes plugin directory requested by the pool."""

    return (root or hermes_root()) / "hermes-agent" / "plugins"


def _same_target(link: Path, source: Path) -> bool:
    """Return True when ``link`` resolves to ``source``.

    ``Path.resolve(strict=False)`` handles relative and broken symlink text without
    raising for missing final path components.
    """

    try:
        return link.resolve(strict=False) == source.resolve(strict=True)
    except OSError:
        return False


def ensure_plugin_symlink(profile_dir: Path, source: Path | None = None) -> dict[str, Any]:
    """Ensure one profile has ``plugins/hermes-agency`` symlinked to ``source``.

    Existing correct symlinks are left untouched. Incorrect symlinks are replaced.
    Existing non-symlink files/directories are reported as errors rather than
    removed, because deleting user plugin directories is destructive.
    """

    source = source or plugin_source_dir()
    plugins = profile_dir / "plugins"
    link = plugins / PLUGIN_NAME

    try:
        if link.is_symlink():
            if _same_target(link, source):
                return {"profile": profile_dir.name, "status": "already", "path": str(link)}
            link.unlink()
            plugins.mkdir(parents=True, exist_ok=True)
            link.symlink_to(source, target_is_directory=True)
            return {"profile": profile_dir.name, "status": "updated", "path": str(link)}

        if link.exists():
            return {
                "profile": profile_dir.name,
                "status": "error",
                "path": str(link),
                "error": "exists and is not a symlink; refusing to replace",
            }

        plugins.mkdir(parents=True, exist_ok=True)
        link.symlink_to(source, target_is_directory=True)
        return {"profile": profile_dir.name, "status": "updated", "path": str(link)}
    except OSError as exc:
        return {
            "profile": profile_dir.name,
            "status": "error",
            "path": str(link),
            "error": str(exc),
        }


def ensure_main_plugin_symlink(
    source: Path | None = None, root: Path | None = None
) -> dict[str, Any]:
    """Ensure the default/gateway plugin directory has the Hermes Agency symlink."""

    source = source or plugin_source_dir()
    pseudo_profile = main_plugins_dir(root).parent
    result = ensure_plugin_symlink(pseudo_profile, source=source)
    result["profile"] = "main"
    result["path"] = str(main_plugins_dir(root) / PLUGIN_NAME)
    return result


def setup_all_profile_plugins(
    *,
    include_main: bool = True,
    root: Path | None = None,
    source: Path | None = None,
) -> dict[str, Any]:
    """Symlink Hermes Agency into Agency-managed profile plugin directories.

    Returns a summary designed for both CLI rendering and compact roster metadata.
    """

    source = source or plugin_source_dir()
    root = root or hermes_root()
    base = profiles_dir(root)
    profile_results: list[dict[str, Any]] = []

    if base.is_dir():
        for profile_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            if not profile_dir.name.startswith("agency-"):
                continue
            profile_results.append(ensure_plugin_symlink(profile_dir, source=source))

    main_result = ensure_main_plugin_symlink(source=source, root=root) if include_main else None
    errors = [r for r in profile_results if r.get("status") == "error"]
    if main_result and main_result.get("status") == "error":
        errors.append(main_result)

    return {
        "ok": not errors,
        "source": str(source),
        "profiles_dir": str(base),
        "profiles_total": len(profile_results),
        "profiles_updated": sum(1 for r in profile_results if r.get("status") == "updated"),
        "profiles_already": sum(1 for r in profile_results if r.get("status") == "already"),
        "profiles_errors": sum(1 for r in profile_results if r.get("status") == "error"),
        "main_status": main_result.get("status") if main_result else "skipped",
        "main_path": main_result.get("path") if main_result else None,
        "results": profile_results,
        "errors": errors,
    }


def compact_setup_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Return path-free setup counts suitable for roster.json."""

    return {
        "ok": bool(summary.get("ok")),
        "profiles_total": int(summary.get("profiles_total", 0)),
        "profiles_updated": int(summary.get("profiles_updated", 0)),
        "profiles_already": int(summary.get("profiles_already", 0)),
        "profiles_errors": int(summary.get("profiles_errors", 0)),
        "main_status": summary.get("main_status") or "skipped",
    }
