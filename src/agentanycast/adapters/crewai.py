"""CrewAI adapter -- expose a CrewAI Crew as a P2P A2A agent.

Usage:
    from crewai import Crew
    from agentanycast import AgentCard, Skill
    from agentanycast.adapters.crewai import serve_crew

    crew = Crew(agents=[...], tasks=[...])
    card = AgentCard(
        name="Research Crew",
        skills=[Skill(id="research", description="Research any topic")],
    )

    await serve_crew(crew, card=card, relay="/ip4/.../p2p/12D3KooW...")
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from agentanycast.adapters._base import BaseAdapter
from agentanycast.card import AgentCard, Skill

if TYPE_CHECKING:
    from crewai import Crew

try:
    from crewai import Crew as _Crew  # noqa: F401
except ImportError as _err:
    raise ImportError(
        "CrewAI adapter requires the 'crewai' package. "
        "Install with: pip install agentanycast[crewai]"
    ) from _err

logger = logging.getLogger(__name__)


class CrewAIAdapter(BaseAdapter):
    """Wraps a CrewAI Crew as an A2A agent."""

    def __init__(self, crew: Crew, **kwargs: Any) -> None:
        self._crew = crew
        super().__init__(**kwargs)

    async def _invoke(self, input_text: str, input_data: dict[str, Any] | None) -> str:
        """Run the Crew with the given input.

        CrewAI's ``kickoff()`` is synchronous, so we run it in a thread executor.
        """
        inputs = input_data or {}
        if input_text and "input" not in inputs:
            inputs["input"] = input_text

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: self._crew.kickoff(inputs=inputs))

        # CrewAI's CrewOutput has a .raw attribute for string output.
        if hasattr(result, "raw"):
            return str(result.raw)
        return str(result)

    @classmethod
    def _build_default_card(cls, framework_obj: Any = None) -> AgentCard | None:
        """Build an AgentCard from CrewAI Crew metadata."""
        if framework_obj is None:
            return None
        crew = framework_obj
        name = getattr(crew, "name", None) or "CrewAI Agent"
        skills: list[Skill] = []
        agents = getattr(crew, "agents", None) or []
        if agents:
            role = getattr(agents[0], "role", None)
            if role:
                skills.append(Skill(id=role.lower().replace(" ", "_"), description=role))
        return AgentCard(name=name, skills=skills)


async def serve_crew(
    crew: Crew,
    *,
    card: AgentCard | None = None,
    **node_kwargs: Any,
) -> None:
    """Serve a CrewAI Crew as a P2P A2A agent.

    This is the main entry point for CrewAI integration. It starts a P2P node,
    registers the crew's capabilities, and processes incoming tasks by running
    the crew's workflow.

    Args:
        crew: A CrewAI ``Crew`` instance.
        card: AgentCard describing the agent and its skills. If ``None``,
            an AgentCard is auto-generated from the crew metadata.
        **node_kwargs: Additional keyword arguments forwarded to
            :class:`~agentanycast.node.Node` (e.g. ``relay``, ``key_path``,
            ``home``).
    """
    if card is None:
        card = CrewAIAdapter._build_default_card(crew)
    adapter = CrewAIAdapter(crew, card=card, **node_kwargs)
    await adapter.serve()
