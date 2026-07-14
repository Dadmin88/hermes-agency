"""Discover and load packaged default staff profiles for Hermes Agency.

This module locates the default_staff directory that ships with the
hermes-agency plugin, reads its manifest, and provides helpers to
list, read, and install default staff profiles into a Hermes profile.

The packaged data lives inside the hermes-agency plugin directory at
``hermes-agency/default_staff/``.  The discovery logic works for both
editable installs (symlinked plugin) and standalone copies.

Safety guarantees:
- Never modifies existing non-agency profiles.
- Never overwrites an existing same-named profile without --force.
- All default staff names use the ``agency-`` namespace.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _plugin_root() -> Path:
    """Return the hermes-agency plugin directory.

    This module lives in hermes-agency/default_staff/__init__.py, so the
    plugin root is the parent of the default_staff package directory.
    """
    return Path(__file__).resolve().parent.parent


def default_staff_dir() -> Path | None:
    """Return the default_staff directory if it exists, else None."""
    candidate = _plugin_root() / "default_staff"
    return candidate if candidate.is_dir() else None


def manifest_path() -> Path | None:
    """Return the manifest.json path if it exists."""
    staff_dir = default_staff_dir()
    if staff_dir is None:
        return None
    candidate = staff_dir / "manifest.json"
    return candidate if candidate.is_file() else None


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_manifest() -> dict[str, Any] | None:
    """Load and return the default staff manifest, or None if unavailable."""
    path = manifest_path()
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def list_default_staff() -> list[dict[str, Any]]:
    """Return the profile list from the manifest, or empty list."""
    manifest = load_manifest()
    if manifest is None:
        return []
    return manifest.get("profiles", [])


def get_profile_info(name: str) -> dict[str, Any] | None:
    """Return manifest entry for a specific profile by name."""
    for entry in list_default_staff():
        if entry.get("name") == name:
            return entry
    return None


def read_profile_soul(name: str) -> str | None:
    """Read the SOUL.md content for a packaged default staff profile."""
    staff_dir = default_staff_dir()
    if staff_dir is None:
        return None
    soul_path = staff_dir / "profiles" / name / "SOUL.md"
    if not soul_path.is_file():
        return None
    try:
        return soul_path.read_text(encoding="utf-8")
    except OSError:
        return None


def read_profile_routing(name: str) -> str | None:
    """Read the ROUTING.md content for a packaged default staff profile."""
    staff_dir = default_staff_dir()
    if staff_dir is None:
        return None
    routing_path = staff_dir / "profiles" / name / "ROUTING.md"
    if not routing_path.is_file():
        return None
    try:
        return routing_path.read_text(encoding="utf-8")
    except OSError:
        return None


def read_profile_metadata(name: str) -> dict[str, Any] | None:
    """Read the profile.yaml metadata for a packaged default staff profile."""
    staff_dir = default_staff_dir()
    if staff_dir is None:
        return None
    yaml_path = staff_dir / "profiles" / name / "profile.yaml"
    if not yaml_path.is_file():
        return None
    if yaml is None:
        return None
    try:
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Installation helpers
# ---------------------------------------------------------------------------

# First-run workforce: enough roles for a real operator loop without installing all 83.
STARTER_STAFF: tuple[str, ...] = (
    "agency-orchestrator",
    "agency-chief-of-staff",
    "agency-product-manager",
    "agency-backend-engineer",
    "agency-frontend-engineer",
    "agency-code-reviewer",
    "agency-qa-tester",
    "agency-docs-writer",
    "agency-git-steward",
    "agency-devops-engineer",
    "agency-security-engineer",
    "agency-design-reviewer",
)


def starter_staff_names() -> list[str]:
    """Return the starter pack names that exist in the packaged manifest."""

    available = {entry.get("name") for entry in list_default_staff()}
    return [name for name in STARTER_STAFF if name in available]


def installed_agency_profile_names(base: Path | None = None) -> list[str]:
    """Return installed ``agency-*`` profile directory names under Hermes profiles."""

    root = base if base is not None else _hermes_profiles_dir()
    if not root.is_dir():
        return []
    return sorted(
        path.name for path in root.iterdir() if path.is_dir() and path.name.startswith("agency-")
    )


def starter_staff_status(base: Path | None = None) -> dict[str, Any]:
    """Report which starter-pack profiles are installed."""

    expected = starter_staff_names()
    installed = set(installed_agency_profile_names(base))
    present = [name for name in expected if name in installed]
    missing = [name for name in expected if name not in installed]
    return {
        "expected": expected,
        "present": present,
        "missing": missing,
        "complete": not missing and bool(expected),
        "installed_agency_count": len(installed),
    }


def _hermes_profiles_dir() -> Path:
    """Resolve the Hermes profiles directory."""
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home()).expanduser()
    if home.parent.name == "profiles":
        return home.parent
    return home / "profiles"


def install_default_staff(
    names: list[str] | None = None,
    *,
    force: bool = False,
    dry_run: bool = False,
    starter: bool = False,
) -> dict[str, Any]:
    """Install default staff profiles into the local Hermes profiles directory.

    Args:
        names: Specific profile names to install. None = install all (unless starter).
        force: If True, overwrite existing same-named profiles.
        dry_run: If True, report what would happen without doing it.
        starter: If True and names is empty, install the first-run starter pack only.

    Returns:
        Dict with installed, skipped, errors lists.
    """
    staff_dir = default_staff_dir()
    if staff_dir is None:
        return {"ok": False, "error": "default_staff directory not found"}

    profiles_source = staff_dir / "profiles"
    if not profiles_source.is_dir():
        return {"ok": False, "error": "profiles directory not found"}

    target_base = _hermes_profiles_dir()
    manifest = load_manifest()
    available = {e["name"] for e in (manifest.get("profiles", []) if manifest else [])}

    if names:
        to_install = list(names)
    elif starter:
        to_install = starter_staff_names()
        if not to_install:
            return {"ok": False, "error": "starter staff pack is empty or missing from manifest"}
    else:
        to_install = sorted(available)
    installed: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for name in to_install:
        if name not in available:
            errors.append(f"{name}: not in default staff manifest")
            continue

        source = profiles_source / name
        target = target_base / name

        if not source.is_dir():
            errors.append(f"{name}: source directory missing")
            continue

        if target.exists() and not force:
            skipped.append(f"{name}: already exists (use --force to overwrite)")
            continue

        if dry_run:
            installed.append(f"{name}: would install to {target}")
            continue

        try:
            if target.exists() and force:
                shutil.rmtree(target)
            shutil.copytree(source, target)
            installed.append(name)
        except OSError as exc:
            errors.append(f"{name}: {exc}")

    return {
        "ok": not errors,
        "installed": installed,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
    }


def staff_contract_path() -> Path | None:
    """Return the path to STAFF_CONTRACT.md if it exists."""
    staff_dir = default_staff_dir()
    if staff_dir is None:
        return None
    candidate = staff_dir / "STAFF_CONTRACT.md"
    return candidate if candidate.is_file() else None
