"""Hermes Agency department mapping and Kanban board conventions."""

from __future__ import annotations

from typing import Final

DEPARTMENT_AGENTS: Final[dict[str, tuple[str, ...]]] = {
    "Engineering": (
        "backend",
        "frontend",
        "fullstack",
        "devops",
        "infrastructure",
        "platform",
        "integration",
        "tools",
        "performance",
        "automation",
        "data",
        "database",
        "ai",
        "godot",
        "code-reviewer",
        "security-engineer",
        "security-reviewer",
    ),
    "Design": (
        "ui-ux",
        "product-designer",
        "brand-designer",
        "art-director",
        "design-reviewer",
        "design-systems",
        "motion-designer",
        "technical-artist",
        "asset-artist",
        "environment-artist",
        "accessibility-reviewer",
        "audio-designer",
        "creative-director",
        "game-designer",
        "level-designer",
        "user-researcher",
    ),
    "Content": (
        "copywriter",
        "content-writer",
        "docs-writer",
        "technical-writer",
        "editor-in-chief",
        "scriptwriter",
        "dialogue-writer",
        "lore-writer",
        "release-notes-writer",
        "worldbuilder",
    ),
    "Marketing": (
        "marketing-strategist",
        "growth-marketer",
        "seo-specialist",
        "email-marketer",
        "social-media-manager",
        "public-relations",
        "community-manager",
    ),
    "Product": (
        "product-manager",
        "product-strategist",
        "project-manager",
        "business-analyst",
        "requirements-analyst",
        "launch-manager",
        "partnerships-manager",
        "competitive-analyst",
        "market-researcher",
        "analytics-specialist",
    ),
    "QA": (
        "qa-lead",
        "qa-tester",
        "red-team",
        "compliance-reviewer",
    ),
    "Operations": (
        "operations-manager",
        "finance-ops",
        "legal-ops",
        "procurement-specialist",
        "support-specialist",
        "customer-success",
        "onboarding-specialist",
        "training-specialist",
    ),
    "Leadership": (
        "orchestrator",
        "chief-of-staff",
        "technical-lead",
        "scrum-master",
        "traffic-manager",
        "release-manager",
        "knowledge-manager",
        "product-strategist",
    ),
}

DEPARTMENT_BOARD_SLUGS: Final[dict[str, str]] = {
    "Engineering": "agency-engineering",
    "Design": "agency-design",
    "Content": "agency-content",
    "Marketing": "agency-marketing",
    "Product": "agency-product",
    "QA": "agency-qa",
    "Operations": "agency-operations",
    "Leadership": "agency-leadership",
}

DEPARTMENT_BOARD_NAMES: Final[dict[str, str]] = {
    department: f"Agency {department}" for department in DEPARTMENT_BOARD_SLUGS
}


def _build_agent_to_department() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for department, agents in DEPARTMENT_AGENTS.items():
        for agent in agents:
            mapping.setdefault(agent, department)
    return mapping


_AGENT_TO_DEPARTMENT: Final[dict[str, str]] = _build_agent_to_department()


def canonical_agent_name(agent_name: str | None) -> str:
    """Return a roster key without the optional ``agency-`` prefix/suffix."""

    value = str(agent_name or "").strip().lower().replace("_", "-")
    if value.startswith("agency-"):
        value = value.removeprefix("agency-")
    if value.endswith("-engineer") and value.removesuffix("-engineer") in _AGENT_TO_DEPARTMENT:
        value = value.removesuffix("-engineer")
    if value.endswith("-designer") and value.removesuffix("-designer") in _AGENT_TO_DEPARTMENT:
        value = value.removesuffix("-designer")
    return value


def get_department(agent_name: str | None) -> str | None:
    """Return the department for an agent/profile name, if known."""

    return _AGENT_TO_DEPARTMENT.get(canonical_agent_name(agent_name))


def get_department_board_slug(agent_name: str | None) -> str | None:
    """Return the Kanban board slug for an agent/profile name's department."""

    department = get_department(agent_name)
    return DEPARTMENT_BOARD_SLUGS.get(department or "")


def get_department_board_name(agent_name: str | None) -> str | None:
    """Return the display board name for an agent/profile name's department."""

    department = get_department(agent_name)
    return DEPARTMENT_BOARD_NAMES.get(department or "")
