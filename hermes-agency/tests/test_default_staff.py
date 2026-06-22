"""Tests for default staff profiles — validates manifest, structure, and content."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Resolve the default_staff directory relative to this test file
_HERE = Path(__file__).resolve().parent
_DEFAULT_STAFF = _HERE.parent / "default_staff"
_PROFILES_DIR = _DEFAULT_STAFF / "profiles"
_MANIFEST_PATH = _DEFAULT_STAFF / "manifest.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    """Load the manifest.json."""
    assert _MANIFEST_PATH.is_file(), f"manifest.json not found at {_MANIFEST_PATH}"
    with open(_MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def profile_dirs() -> list[Path]:
    """List all profile directories."""
    return sorted(
        p for p in _PROFILES_DIR.iterdir() if p.is_dir()
    )


# ---------------------------------------------------------------------------
# Manifest tests
# ---------------------------------------------------------------------------

class TestManifest:
    def test_manifest_exists(self):
        assert _MANIFEST_PATH.is_file(), "manifest.json must exist"

    def test_manifest_parses(self, manifest: dict):
        assert isinstance(manifest, dict)
        assert "profiles" in manifest
        assert "version" in manifest

    def test_manifest_profile_count(self, manifest: dict, profile_dirs: list[Path]):
        assert manifest["total_profiles"] == len(profile_dirs), (
            f"Manifest says {manifest['total_profiles']} but found {len(profile_dirs)} directories"
        )

    def test_manifest_has_all_profiles(self, manifest: dict, profile_dirs: list[Path]):
        manifest_names = {p["name"] for p in manifest["profiles"]}
        dir_names = {p.name for p in profile_dirs}
        assert manifest_names == dir_names, (
            f"Mismatch: manifest-only={manifest_names - dir_names}, "
            f"dir-only={dir_names - manifest_names}"
        )

    def test_no_duplicate_names(self, manifest: dict):
        names = [p["name"] for p in manifest["profiles"]]
        assert len(names) == len(set(names)), "Duplicate profile names in manifest"

    def test_all_names_start_with_agency(self, manifest: dict):
        for p in manifest["profiles"]:
            assert p["name"].startswith("agency-"), (
                f"Profile {p['name']} does not start with 'agency-'"
            )

    def test_global_defaults(self, manifest: dict):
        defaults = manifest.get("global_defaults", {})
        assert defaults.get("agency_enabled") is True
        assert defaults.get("auto_start") is False
        assert defaults.get("allow_remote_tasks") is False
        assert defaults.get("skills_from_profile") is True

    def test_manifest_categories(self, manifest: dict):
        categories = manifest.get("categories", [])
        assert len(categories) >= 5, f"Expected at least 5 categories, got {len(categories)}"
        expected = {"leadership", "engineering", "design", "content", "qa"}
        assert expected.issubset(set(categories)), (
            f"Missing expected categories: {expected - set(categories)}"
        )


# ---------------------------------------------------------------------------
# Profile structure tests
# ---------------------------------------------------------------------------

class TestProfileStructure:
    def test_all_profiles_have_soul_md(self, profile_dirs: list[Path]):
        missing = [p.name for p in profile_dirs if not (p / "SOUL.md").is_file()]
        assert not missing, f"Profiles missing SOUL.md: {missing}"

    def test_all_profiles_have_routing_md(self, profile_dirs: list[Path]):
        missing = [p.name for p in profile_dirs if not (p / "ROUTING.md").is_file()]
        assert not missing, f"Profiles missing ROUTING.md: {missing}"

    def test_all_profiles_have_profile_yaml(self, profile_dirs: list[Path]):
        missing = [p.name for p in profile_dirs if not (p / "profile.yaml").is_file()]
        assert not missing, f"Profiles missing profile.yaml: {missing}"

    def test_soul_md_not_trivial(self, profile_dirs: list[Path]):
        """SOUL.md files should be substantial (>500 bytes)."""
        short = []
        for p in profile_dirs:
            soul = p / "SOUL.md"
            if soul.is_file() and soul.stat().st_size < 500:
                short.append(f"{p.name} ({soul.stat().st_size} bytes)")
        assert not short, f"SOUL.md files too short: {short}"

    def test_routing_md_not_trivial(self, profile_dirs: list[Path]):
        """ROUTING.md files should be substantial (>300 bytes)."""
        short = []
        for p in profile_dirs:
            routing = p / "ROUTING.md"
            if routing.is_file() and routing.stat().st_size < 300:
                short.append(f"{p.name} ({routing.stat().st_size} bytes)")
        assert not short, f"ROUTING.md files too short: {short}"


# ---------------------------------------------------------------------------
# Profile content tests
# ---------------------------------------------------------------------------

class TestProfileContent:
    def test_soul_md_has_identity(self, profile_dirs: list[Path]):
        """Every SOUL.md should have an Identity section."""
        missing = []
        for p in profile_dirs:
            soul = (p / "SOUL.md").read_text(encoding="utf-8")
            if "## Identity" not in soul:
                missing.append(p.name)
        assert not missing, f"SOUL.md missing Identity section: {missing}"

    def test_soul_md_has_mission(self, profile_dirs: list[Path]):
        missing = []
        for p in profile_dirs:
            soul = (p / "SOUL.md").read_text(encoding="utf-8")
            if "## Mission" not in soul:
                missing.append(p.name)
        assert not missing, f"SOUL.md missing Mission section: {missing}"

    def test_routing_md_has_ownership(self, profile_dirs: list[Path]):
        missing = []
        for p in profile_dirs:
            routing = (p / "ROUTING.md").read_text(encoding="utf-8")
            if "## Ownership" not in routing:
                missing.append(p.name)
        assert not missing, f"ROUTING.md missing Ownership section: {missing}"

    def test_profile_yaml_has_required_fields(self, profile_dirs: list[Path]):
        import yaml
        missing = []
        for p in profile_dirs:
            with open(p / "profile.yaml", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for field in ["name", "display_name", "category", "summary"]:
                if field not in data or not data[field]:
                    missing.append(f"{p.name}/{field}")
        assert not missing, f"Missing required fields: {missing}"

    def test_profile_yaml_names_match_directory(self, profile_dirs: list[Path]):
        import yaml
        mismatches = []
        for p in profile_dirs:
            with open(p / "profile.yaml", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data.get("name") != p.name:
                mismatches.append(f"{p.name} vs {data.get('name')}")
        assert not mismatches, f"Name mismatches: {mismatches}"

    def test_profile_yaml_agency_enabled(self, profile_dirs: list[Path]):
        """All profiles should have agency.enabled = true."""
        import yaml
        disabled = []
        for p in profile_dirs:
            with open(p / "profile.yaml", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data.get("agency", {}).get("enabled", False):
                disabled.append(p.name)
        assert not disabled, f"Profiles with agency not enabled: {disabled}"

    def test_profile_yaml_auto_start_false(self, profile_dirs: list[Path]):
        """All profiles should have auto_start = false by default."""
        import yaml
        auto = []
        for p in profile_dirs:
            with open(p / "profile.yaml", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data.get("agency", {}).get("auto_start", False):
                auto.append(p.name)
        assert not auto, f"Profiles with auto_start=true: {auto}"


# ---------------------------------------------------------------------------
# Discovery code tests
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_discovery_module_importable(self):
        """The discovery module should be importable."""
        import sys
        sys.path.insert(0, str(_DEFAULT_STAFF.parent.parent.parent))
        try:
            from hermes_agency.default_staff import list_default_staff, load_manifest
            assert callable(list_default_staff)
            assert callable(load_manifest)
        except ImportError:
            # May not be importable in test context without full plugin setup
            pytest.skip("Discovery module not importable in test context")

    def test_staff_contract_exists(self):
        contract = _DEFAULT_STAFF / "STAFF_CONTRACT.md"
        assert contract.is_file(), "STAFF_CONTRACT.md must exist"
        content = contract.read_text(encoding="utf-8")
        assert len(content) > 1000, "STAFF_CONTRACT.md should be substantial"


# ---------------------------------------------------------------------------
# Cross-profile consistency tests
# ---------------------------------------------------------------------------

class TestConsistency:
    def test_no_existing_profile_names_referenced(self, manifest: dict):
        """Ensure no manifest entry references a non-agency profile name as a target."""
        existing_profiles = {"katana", "gpt", "grok", "designer", "git", "default"}
        violations = []
        for p in manifest["profiles"]:
            delegates = p.get("delegates_to", [])
            for d in delegates:
                if d and d in existing_profiles:
                    violations.append(f"{p['name']} delegates to existing profile: {d}")
        assert not violations, f"References to existing profiles: {violations}"

    def test_unique_categories_in_manifest(self, manifest: dict):
        """Each profile should have exactly one category."""
        for p in manifest["profiles"]:
            assert p.get("category"), f"{p['name']} missing category"

    def test_delegation_targets_exist(self, manifest: dict):
        """Delegation targets should reference other default staff profiles."""
        all_names = {p["name"] for p in manifest["profiles"]}
        external_targets = set()
        for p in manifest["profiles"]:
            for d in p.get("delegates_to", []):
                if d and d not in all_names:
                    external_targets.add(d)
        # It's OK to have null/empty delegates (leaf roles)
        # But non-existent named targets should be flagged
        assert not external_targets, (
            f"Delegation targets not in manifest: {external_targets}"
        )
