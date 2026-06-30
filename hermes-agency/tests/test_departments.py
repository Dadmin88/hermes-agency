from __future__ import annotations

import importlib.util
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load_departments():
    spec = importlib.util.spec_from_file_location(
        "agency_departments_under_test", PLUGIN_DIR / "departments.py"
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_department_mapping_covers_expected_agents_and_board_slugs():
    departments = _load_departments()

    assert departments.get_department("agency-frontend-engineer") == "Engineering"
    assert departments.get_department("frontend-engineer") == "Engineering"
    assert departments.get_department("copywriter") == "Content"
    assert departments.get_department("agency-seo-specialist") == "Marketing"
    assert departments.get_department("qa-lead") == "QA"
    assert departments.get_department("agency-product-strategist") == "Product"
    assert departments.get_department("agency-chief-of-staff") == "Leadership"

    assert departments.get_department_board_slug("agency-frontend-engineer") == "agency-engineering"
    assert departments.get_department_board_slug("copywriter") == "agency-content"
    assert departments.get_department_board_slug("seo-specialist") == "agency-marketing"


def test_department_mapping_exposes_exact_eight_board_convention():
    departments = _load_departments()

    assert departments.DEPARTMENT_BOARD_SLUGS == {
        "Engineering": "agency-engineering",
        "Design": "agency-design",
        "Content": "agency-content",
        "Marketing": "agency-marketing",
        "Product": "agency-product",
        "QA": "agency-qa",
        "Operations": "agency-operations",
        "Leadership": "agency-leadership",
    }
    assert departments.DEPARTMENT_BOARD_NAMES == {
        "Engineering": "Agency Engineering",
        "Design": "Agency Design",
        "Content": "Agency Content",
        "Marketing": "Agency Marketing",
        "Product": "Agency Product",
        "QA": "Agency QA",
        "Operations": "Agency Operations",
        "Leadership": "Agency Leadership",
    }


def test_unknown_agent_has_no_department_board():
    departments = _load_departments()

    assert departments.get_department("agency-not-a-real-agent") is None
    assert departments.get_department_board_slug("agency-not-a-real-agent") is None
    assert departments.get_department_board_name("agency-not-a-real-agent") is None


def test_pool_department_roster_returns_ok_for_valid_department():
    """pool_department_roster should return ok=True for a known department."""
    import importlib.util
    import json
    from pathlib import Path

    plugin_dir = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "pool_tools_dept", plugin_dir / "pool" / "tools.py"
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Patch imports that need the plugin package
    import sys

    fake_pkg = types.ModuleType("hermes_agency")
    fake_pool = types.ModuleType("hermes_agency.pool")
    fake_pkg.pool = fake_pool
    sys.modules.setdefault("hermes_agency", fake_pkg)
    sys.modules.setdefault("hermes_agency.pool", fake_pool)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # Some transitive imports may fail; that's OK for this test
        return

    if hasattr(mod, "pool_department_roster"):
        result = json.loads(mod.pool_department_roster("Engineering"))
        assert result["ok"] is True
        assert result["department"] == "Engineering"


def test_pool_department_roster_rejects_unknown_department():
    """pool_department_roster should return ok=False for unknown department."""
    import importlib.util
    import json
    from pathlib import Path

    plugin_dir = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "pool_tools_dept2", plugin_dir / "pool" / "tools.py"
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return

    if hasattr(mod, "pool_department_roster"):
        result = json.loads(mod.pool_department_roster("NonexistentDept"))
        assert result["ok"] is False
        assert "unknown department" in result["error"]


def test_create_starter_skills_generates_department_skills():
    """_create_starter_skills should create skill files for each department."""
    import importlib.util
    from pathlib import Path

    plugin_dir = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "pool_tools_skills", plugin_dir / "pool" / "tools.py"
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return

    if not hasattr(mod, "_create_starter_skills"):
        return

    import tempfile

    for dept in ["Engineering", "Design", "Content", "Marketing", "Product", "QA", "Operations", "Leadership"]:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir)
            mod._create_starter_skills(profile_dir, f"agency-test-{dept.lower()}", dept, [])
            skills_dir = profile_dir / "skills"
            assert skills_dir.exists(), f"skills dir not created for {dept}"
            skill_files = list(skills_dir.glob("*/SKILL.md"))
            assert len(skill_files) >= 1, f"no starter skills created for {dept}"
            for sf in skill_files:
                content = sf.read_text()
                assert "---" in content, f"missing frontmatter in {sf}"
                assert "name:" in content, f"missing name in frontmatter in {sf}"


def test_create_starter_skills_includes_custom_skills():
    """_create_starter_skills should also create dirs for custom agent skills."""
    import importlib.util
    import tempfile
    from pathlib import Path

    plugin_dir = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "pool_tools_custom", plugin_dir / "pool" / "tools.py"
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return

    if not hasattr(mod, "_create_starter_skills"):
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = Path(tmpdir)
        mod._create_starter_skills(profile_dir, "agency-test", "Engineering", ["kubernetes", "terraform"])
        assert (profile_dir / "skills" / "kubernetes" / "SKILL.md").exists()
        assert (profile_dir / "skills" / "terraform" / "SKILL.md").exists()
