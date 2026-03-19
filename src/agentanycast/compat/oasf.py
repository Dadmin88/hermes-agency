"""AGNTCY OASF compatibility -- convert AgentCard to/from OASF records.

The Open Agentic Schema Framework (OASF) is the standard metadata format
used by the AGNTCY ecosystem for agent discovery and interoperability.
This module provides bidirectional conversion between AgentAnycast's
internal AgentCard representation and OASF records, enabling agents to
be registered in the AGNTCY Agent Directory Service (ADS) and discovered
by the broader AGNTCY ecosystem (65+ member companies, Linux Foundation).

OASF records carry agent metadata (name, skills, domains), protocol
modules (A2A, MCP, etc.), and locators (URLs, DIDs, P2P addresses).
The A2A module embeds the full A2A Agent Card JSON so that any A2A-aware
consumer can reconstruct the card without loss.

No external AGNTCY packages are required -- all conversions are pure Python.

Example::

    from agentanycast.card import AgentCard, Skill
    from agentanycast.compat.oasf import card_to_oasf_record, card_from_oasf_record

    card = AgentCard(
        name="WeatherAgent",
        skills=[Skill(id="get_weather", description="Current weather")],
        peer_id="12D3KooWExample",
    )
    record = card_to_oasf_record(card, authors=["Me <me@example.com>"])
    restored = card_from_oasf_record(record)
    assert restored.name == card.name
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agentanycast.card import AgentCard, Skill
from agentanycast.compat.a2a_v1 import card_to_a2a_json

# OASF module ID for A2A protocol data.
_A2A_MODULE_ID = 3
_A2A_MODULE_NAME = "a2a"


# ---------------------------------------------------------------------------
# Skill conversion
# ---------------------------------------------------------------------------


def skill_to_oasf(skill: Skill) -> dict[str, str | int]:
    """Convert a :class:`Skill` to OASF skill format.

    OASF skills use a hierarchical taxonomy with slash-separated names
    (e.g. ``natural_language_processing/text_completion``).  When the
    skill ``id`` already contains a slash it is used verbatim; otherwise
    the id is placed as a single-level name.

    Returns:
        A dict with ``"name"`` (str).  An ``"id"`` key (int) is included
        only when the caller provides one via the original OASF data; this
        function does **not** invent numeric IDs.
    """
    return {"name": skill.id}


def skill_from_oasf(oasf_skill: dict[str, Any]) -> Skill:
    """Convert an OASF skill entry to an internal :class:`Skill`.

    The OASF ``name`` field (slash-separated taxonomy path) is mapped to
    :pyattr:`Skill.id`.  An optional ``description`` field is forwarded.
    """
    return Skill(
        id=str(oasf_skill.get("name", "")),
        description=str(oasf_skill.get("description", "")),
    )


# ---------------------------------------------------------------------------
# Card -> OASF record
# ---------------------------------------------------------------------------


def card_to_oasf_record(
    card: AgentCard,
    *,
    authors: list[str] | None = None,
    domains: list[dict[str, Any]] | None = None,
    version: str | None = None,
    schema_version: str = "1.0.0",
) -> dict[str, Any]:
    """Convert an :class:`AgentCard` to an OASF record.

    The record embeds the full A2A Agent Card inside the ``a2a`` module so
    that downstream consumers can reconstruct it losslessly.  A ``p2p://``
    locator is added when the card carries a ``peer_id``, and a ``did:``
    locator when ``did_key`` is present.

    Args:
        card: The agent card to convert.
        authors: Optional author list (e.g. ``["Name <email>"]``).
        domains: Optional OASF domain entries.
        version: Record version; defaults to ``card.version``.
        schema_version: OASF schema version (default ``"1.0.0"``).

    Returns:
        A JSON-serializable OASF record dict.
    """
    record: dict[str, Any] = {
        "name": card.name,
        "description": card.description,
        "version": version or card.version or "1.0.0",
        "schema_version": schema_version,
        "authors": authors or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "skills": [skill_to_oasf(s) for s in card.skills],
        "domains": domains or [],
        "modules": [
            {
                "name": _A2A_MODULE_NAME,
                "id": _A2A_MODULE_ID,
                "data": {
                    "card_data": card_to_a2a_json(card),
                    "card_schema_version": card.protocol_version or "a2a/0.3",
                },
            },
        ],
        "locators": [],
    }

    # P2P locator
    if card.peer_id:
        record["locators"].append({"type": "url", "urls": [f"p2p://{card.peer_id}"]})

    # DID locator
    if card.did_key:
        record["locators"].append({"type": "url", "urls": [f"did:{card.did_key}"]})

    return record


# ---------------------------------------------------------------------------
# OASF record -> Card
# ---------------------------------------------------------------------------


def card_from_oasf_record(record: dict[str, Any]) -> AgentCard:
    """Extract an :class:`AgentCard` from an OASF record.

    Reconstruction strategy:

    1. Look for an ``a2a`` module (``id == 3`` or ``name == "a2a"``).  If
       found, deserialize the embedded ``card_data`` via
       :meth:`AgentCard.from_dict`.
    2. If no A2A module is present, build a card from record-level fields
       (``name``, ``description``, ``skills``, locators).

    Locator ``p2p://`` URLs are mapped to :pyattr:`AgentCard.peer_id` and
    ``did:`` URLs to :pyattr:`AgentCard.did_key`.
    """
    # Try A2A module first.
    for module in record.get("modules", []):
        if module.get("name") == _A2A_MODULE_NAME or module.get("id") == _A2A_MODULE_ID:
            card_data = module.get("data", {}).get("card_data")
            if card_data and isinstance(card_data, dict):
                card = AgentCard.from_dict(card_data)
                # Supplement with locator info if the card_data lacked it.
                _apply_locators(card, record.get("locators", []))
                return card

    # Fallback: construct from record-level fields.
    skills = [skill_from_oasf(s) for s in record.get("skills", [])]
    card = AgentCard(
        name=record.get("name", ""),
        description=record.get("description", ""),
        version=record.get("version", "1.0.0"),
        skills=skills,
    )
    _apply_locators(card, record.get("locators", []))
    return card


def _apply_locators(card: AgentCard, locators: list[dict[str, Any]]) -> None:
    """Extract peer_id and did_key from OASF locator entries."""
    for locator in locators:
        for url in locator.get("urls", []):
            if isinstance(url, str):
                if url.startswith("p2p://") and not card.peer_id:
                    card.peer_id = url[len("p2p://") :]
                elif url.startswith("did:") and not card.did_key:
                    # Store the full DID value after "did:" prefix.
                    card.did_key = url[len("did:") :]
