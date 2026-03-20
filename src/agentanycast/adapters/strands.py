"""AWS Strands Agents adapter -- expose a Strands Agent as a P2P A2A agent.

Usage:
    from strands import Agent
    from agentanycast import AgentCard, Skill
    from agentanycast.adapters.strands import serve_strands_agent

    agent = Agent(model="us.amazon.nova-pro-v1:0")
    card = AgentCard(
        name="Strands Agent",
        skills=[Skill(id="help", description="Answer general questions")],
    )

    await serve_strands_agent(agent, card=card, relay="/ip4/.../p2p/12D3KooW...")
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from agentanycast.adapters._base import BaseAdapter
from agentanycast.card import AgentCard, Skill

if TYPE_CHECKING:
    from strands import Agent

try:
    from strands import Agent as _Agent  # noqa: F401
except ImportError as _err:
    raise ImportError(
        "Strands Agents adapter requires the 'strands-agents' package. "
        "Install with: pip install agentanycast[strands]"
    ) from _err

logger = logging.getLogger(__name__)


class StrandsAdapter(BaseAdapter):
    """Wraps an AWS Strands Agent as an A2A agent."""

    def __init__(self, agent: Agent, **kwargs: Any) -> None:
        self._agent = agent
        super().__init__(**kwargs)

    async def _invoke(self, input_text: str, input_data: dict[str, Any] | None) -> str:
        """Run the Strands Agent with the given input.

        ``Agent.__call__`` is synchronous, so we run it in a thread executor
        via ``asyncio.to_thread()`` to avoid blocking the event loop.
        """
        # Prefer text input; fall back to stringified data.
        text = input_text
        if not text and input_data:
            text = str(input_data)

        result = await asyncio.to_thread(self._agent, text)
        if result is None:
            return ""
        return str(result)

    @classmethod
    def _build_default_card(cls, framework_obj: Any = None) -> AgentCard | None:
        """Build an AgentCard from Strands Agent metadata."""
        if framework_obj is None:
            return None
        agent = framework_obj
        name = getattr(agent, "name", None) or "Strands Agent"
        description = getattr(agent, "system_prompt", None) or ""
        # Use first sentence of system_prompt as skill description.
        if description:
            description = description.split(".")[0].strip()
        skills = [Skill(id=name.lower().replace(" ", "_"), description=description or name)]
        return AgentCard(name=name, skills=skills)


async def serve_strands_agent(
    agent: Agent,
    *,
    card: AgentCard | None = None,
    **node_kwargs: Any,
) -> None:
    """Serve an AWS Strands Agent as a P2P A2A agent.

    This is the main entry point for AWS Strands Agents integration. It starts
    a P2P node, registers the agent's capabilities, and processes incoming
    tasks by running the Strands agent.

    Args:
        agent: A Strands ``Agent`` instance.
        card: AgentCard describing the agent and its skills. If ``None``,
            an AgentCard is auto-generated from agent metadata.
        **node_kwargs: Additional keyword arguments forwarded to
            :class:`~agentanycast.node.Node` (e.g. ``relay``, ``key_path``,
            ``home``).
    """
    if card is None:
        card = StrandsAdapter._build_default_card(agent)
    adapter = StrandsAdapter(agent, card=card, **node_kwargs)
    await adapter.serve()
