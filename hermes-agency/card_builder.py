"""Build Hermes Agency AgentCards from Hermes profile state.

Phase 2 maps a Hermes profile into an A2A-compatible AgentCard by reading:

- ``SOUL.md`` for the profile identity/description
- installed Hermes skills under ``skills/**/SKILL.md``
- ``config.yaml`` for model/toolset metadata

The Hermes Agency SDK's current ``AgentCard`` dataclass does not yet expose a
first-class metadata field, so ``build_card()`` returns the SDK dataclass and
attaches a dynamic ``metadata`` attribute for local/plugin consumers. Use
``card_to_dict()`` when a serialized card with metadata is needed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

DEFAULT_DESCRIPTION = "Hermes profile exposed over Hermes Agency."
CARD_VERSION = "1.0.0"


try:  # Hermes already depends on PyYAML, but keep this plugin defensive.
    import yaml
except Exception:  # pragma: no cover - only used in stripped environments
    yaml = None  # type: ignore[assignment]


def resolve_profile_home(profile: str | Path | None = None) -> Path:
    """Resolve a profile name/path to its Hermes profile home.

    ``None`` means the active profile. A bare name like ``"katana"`` resolves
    next to the active profile when running under ``~/.hermes/profiles/<name>``.
    Absolute paths and path-like strings are used directly.
    """

    active_home = Path(get_hermes_home()).expanduser()
    if profile is None:
        return active_home

    candidate = Path(profile).expanduser()
    if candidate.is_absolute() or len(candidate.parts) > 1:
        return candidate

    if active_home.parent.name == "profiles":
        profiles_dir = active_home.parent
    else:
        profiles_dir = active_home / "profiles"
    return profiles_dir / str(profile)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_yaml_file(path: Path) -> dict[str, Any]:
    text = _read_text(path)
    if not text.strip() or yaml is None:
        return {}
    try:
        loaded = yaml.safe_load(text)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _cfg_get(config: dict[str, Any], *path: str, default: Any = None) -> Any:
    value: Any = config
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _extract_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---") or yaml is None:
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        loaded = yaml.safe_load(parts[1])
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _fallback_frontmatter_value(text: str, key: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*:\s*[\"']?(.+?)[\"']?\s*$", text)
    return match.group(1).strip() if match else ""


def _normalise_skill_id(raw: str) -> str:
    slug = raw.strip().lower().replace("/", ".")
    slug = re.sub(r"[^a-z0-9_.-]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-._")
    return slug or "hermes-skill"


def _soul_profile_name(soul_text: str) -> str:
    """Extract an explicit SOUL name when one exists.

    This is used as the AgentCard display name when ``agency.card_name``
    is not configured. The profile directory name remains available in
    metadata for stable routing/debug identity.
    """

    for pattern in (
        r"(?im)^\s*Name\s*:\s*`?([^`\n]+)`?\s*$",
        r"(?im)^\s*#\s*SOUL\.md\s*[—-]\s*([^\n]+)\s*$",
    ):
        match = re.search(pattern, soul_text)
        if match:
            return match.group(1).strip()
    return ""


def _paragraphs_from_markdown(text: str) -> list[str]:
    paragraphs: list[str] = []
    in_code_block = False

    for raw_paragraph in re.split(r"\n\s*\n", text):
        lines: list[str] = []
        for line in raw_paragraph.splitlines():
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block or not stripped:
                continue
            if stripped.startswith("#") or stripped.startswith("---"):
                continue
            # Skip tables/lists so capability lists do not become descriptions.
            if stripped.startswith(("|", "* ", "- ", "1. ", ">")):
                continue
            lines.append(stripped)
        clean = " ".join(lines).strip()
        if clean:
            paragraphs.append(clean)
    return paragraphs


def _is_metadata_paragraph(paragraph: str) -> bool:
    # A profile preamble like "Name: ... Alias: ... Role: ..." is useful
    # metadata, but not a good human-readable AgentCard description.
    fields = re.findall(r"\b[A-Z][A-Za-z ]{1,24}:\s*", paragraph)
    return bool(fields) and paragraph.count(":") >= 2 and not paragraph.startswith("You ")


def read_profile_description(profile_home: str | Path | None = None) -> str:
    """Return the first descriptive paragraph from ``SOUL.md``."""

    soul_text = _read_text(resolve_profile_home(profile_home) / "SOUL.md")
    if not soul_text:
        return DEFAULT_DESCRIPTION

    paragraphs = _paragraphs_from_markdown(soul_text)
    for paragraph in paragraphs:
        if not _is_metadata_paragraph(paragraph):
            return paragraph[:500]
    return (paragraphs[0][:500] if paragraphs else DEFAULT_DESCRIPTION)


def read_profile_skills(profile_home: str | Path | None = None) -> list[dict[str, str]]:
    """Read installed Hermes skills and return A2A-ready skill descriptors."""

    profile_dir = resolve_profile_home(profile_home)
    skills_dir = profile_dir / "skills"
    if not skills_dir.exists():
        return []

    raw_skills: list[dict[str, str]] = []
    for skill_file in sorted(skills_dir.glob("**/SKILL.md")):
        rel_parent = skill_file.parent.relative_to(skills_dir).as_posix()
        text = _read_text(skill_file)
        frontmatter = _extract_frontmatter(text)

        raw_name = str(frontmatter.get("name") or "").strip()
        if not raw_name:
            raw_name = _fallback_frontmatter_value(text, "name")
        if not raw_name:
            raw_name = skill_file.parent.name

        description = str(frontmatter.get("description") or "").strip()
        if not description:
            description = _fallback_frontmatter_value(text, "description")
        if not description:
            description = f"Hermes skill from {rel_parent}."

        raw_skills.append(
            {
                "id": _normalise_skill_id(raw_name),
                "description": description[:500],
                "path_id": _normalise_skill_id(rel_parent),
            }
        )

    seen: set[str] = set()
    skills: list[dict[str, str]] = []
    for skill in raw_skills:
        skill_id = skill["id"]
        if skill_id in seen:
            skill_id = skill["path_id"]
        suffix = 2
        unique_id = skill_id
        while unique_id in seen:
            suffix += 1
            unique_id = f"{skill_id}-{suffix}"
        seen.add(unique_id)
        skills.append({"id": unique_id, "description": skill["description"]})

    return sorted(skills, key=lambda item: item["id"])


def read_profile_metadata(profile_home: str | Path | None = None) -> dict[str, Any]:
    """Read non-secret Hermes model/toolset metadata from profile config."""

    profile_dir = resolve_profile_home(profile_home)
    config = _read_yaml_file(profile_dir / "config.yaml")
    soul_text = _read_text(profile_dir / "SOUL.md")

    model = {
        "provider": _cfg_get(config, "model", "provider", default="") or "",
        "default": _cfg_get(config, "model", "default", default="") or "",
        "base_url_configured": bool(_cfg_get(config, "model", "base_url", default="")),
    }

    toolsets = _cfg_get(config, "toolsets", default=[])
    if not isinstance(toolsets, list):
        toolsets = []
    disabled_toolsets = _cfg_get(config, "agent", "disabled_toolsets", default=[])
    if not isinstance(disabled_toolsets, list):
        disabled_toolsets = []
    configured_card_name = str(
        _cfg_get(config, "agency", "card_name", default="") or ""
    ).strip()
    soul_name = _soul_profile_name(soul_text)
    card_name = configured_card_name or soul_name or profile_dir.name

    return {
        "hermes": {
            "profile": profile_dir.name,
            "soul_name": soul_name,
            "card_name": card_name,
            "model": model,
            "toolsets": toolsets,
            "disabled_toolsets": disabled_toolsets,
            "skills_from_profile": bool(
                _cfg_get(config, "agency", "skills_from_profile", default=True)
            ),
        },
        "agency": {
            "team": {
                "tenant": _cfg_get(config, "agency", "team", "tenant", default="default") or "default",
            }
        },
    }


def build_card(profile_home: str | Path | None = None) -> Any:
    """Return an ``agency.AgentCard`` for a Hermes profile.

    The import is lazy so Hermes can load the plugin even when the SDK is not
    installed; tool check functions remain responsible for availability.
    """

    from agentanycast import AgentCard, Skill

    profile_dir = resolve_profile_home(profile_home)
    metadata = read_profile_metadata(profile_dir)
    card_name = metadata.get("hermes", {}).get("card_name") or profile_dir.name
    include_skills = metadata.get("hermes", {}).get("skills_from_profile", True)
    skill_dicts = read_profile_skills(profile_dir) if include_skills else []
    # Always expose the generic Hermes chat capability so agents can discover
    # Hermes profiles even when their installed skill sets do not overlap.
    if not any(item.get("id") == "hermes-chat" for item in skill_dicts):
        skill_dicts.append(
            {
                "id": "hermes-chat",
                "description": "Receive a natural-language task for this Hermes profile.",
            }
        )

    card = AgentCard(
        name=str(card_name),
        description=read_profile_description(profile_dir),
        version=CARD_VERSION,
        skills=[Skill(id=item["id"], description=item["description"]) for item in skill_dicts],
    )
    # The current SDK dataclass has no metadata field; attach it for local use.
    setattr(card, "metadata", metadata)
    return card


def card_to_dict(card: Any) -> dict[str, Any]:
    """Serialize an AgentCard and include dynamic Hermes metadata if present."""

    if hasattr(card, "to_dict"):
        data = card.to_dict()
    else:
        data = dict(card)
    metadata = getattr(card, "metadata", None)
    if metadata:
        data["metadata"] = metadata
    return data
