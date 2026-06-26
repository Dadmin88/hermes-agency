from __future__ import annotations

import importlib.util
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
