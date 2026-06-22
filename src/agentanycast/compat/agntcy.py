"""AGNTCY Agent Directory integration.

Provides an HTTP client for querying the AGNTCY Agent Directory
(https://agntcy.org) as an external discovery source. AGNTCY uses
IPFS Kademlia DHT for its directory, but exposes an HTTP API for queries.

This module translates AGNTCY directory entries into AgentAnycast's
AgentCard format, enabling unified discovery across ecosystems.

Example::

    from agentanycast.compat.agntcy import AGNTCYDirectory

    directory = AGNTCYDirectory("https://directory.agntcy.org")
    agents = await directory.search("weather")
    for card in agents:
        print(f"{card.name}: {[s.id for s in card.skills]}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from agentanycast.card import AgentCard, Skill


@dataclass
class AGNTCYDirectoryConfig:
    """Configuration for AGNTCY directory client."""

    base_url: str
    timeout: float = 10.0
    headers: dict[str, str] = field(default_factory=dict)


class AGNTCYDirectory:
    """Client for querying the AGNTCY Agent Directory.

    The AGNTCY directory provides a decentralized catalog of AI agents,
    using IPFS DHT for storage and an HTTP API for queries.
    """

    def __init__(
        self,
        base_url: str = "https://directory.agntcy.org",
        *,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[AgentCard]:
        """Search the AGNTCY directory for agents matching a query.

        Args:
            query: Search query (skill name, description keyword, etc.).
            limit: Maximum number of results.

        Returns:
            List of AgentCards translated from AGNTCY directory entries.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/agents/search",
                params={"q": query, "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        return [self._translate_entry(entry) for entry in data.get("agents", [])]

    async def get_agent(self, agent_id: str) -> AgentCard | None:
        """Fetch a specific agent by its AGNTCY directory ID.

        Args:
            agent_id: The AGNTCY directory agent identifier.

        Returns:
            An AgentCard, or None if not found.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/api/v1/agents/{agent_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return self._translate_entry(resp.json())

    @staticmethod
    def _translate_entry(entry: dict[str, Any]) -> AgentCard:
        """Translate an AGNTCY directory entry to an AgentCard."""
        skills = []
        for capability in entry.get("capabilities", []):
            skills.append(
                Skill(
                    id=capability.get("name", ""),
                    description=capability.get("description", ""),
                )
            )

        return AgentCard(
            name=entry.get("name", ""),
            description=entry.get("description", ""),
            version=entry.get("version", "1.0.0"),
            skills=skills,
        )
