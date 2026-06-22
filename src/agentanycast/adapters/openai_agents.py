"""OpenAI Agents SDK adapter -- expose an OpenAI Agent as a P2P A2A agent.

Usage:
    from agents import Agent
    from agentanycast import AgentCard, Skill
    from agentanycast.adapters.openai_agents import serve_openai_agent

    agent = Agent(
        name="helper",
        instructions="You are a helpful assistant.",
        model="gpt-4o",
    )
    card = AgentCard(
        name="Helper Agent",
        skills=[Skill(id="help", description="Answer general questions")],
    )

    await serve_openai_agent(agent, card=card, relay="/ip4/.../p2p/12D3KooW...")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agentanycast.adapters._base import BaseAdapter
from agentanycast.card import AgentCard, Skill

if TYPE_CHECKING:
    from agents import Agent

try:
    from agents import Agent as _Agent  # noqa: F401
    from agents import Runner
except ImportError as _err:
    raise ImportError(
        "OpenAI Agents adapter requires the 'openai-agents' package. "
        "Install with: pip install agentanycast[openai-agents]"
    ) from _err

logger = logging.getLogger(__name__)


class OpenAIAgentsAdapter(BaseAdapter):
    """Wraps an OpenAI Agents SDK Agent as an A2A agent."""

    def __init__(self, agent: Agent, **kwargs: Any) -> None:
        self._agent = agent
        super().__init__(**kwargs)

    async def _invoke(self, input_text: str, input_data: dict[str, Any] | None) -> str:
        """Run the OpenAI Agent with the given input.

        ``Runner.run()`` is natively async, so no executor is needed.
        """
        # Prefer text input; fall back to stringified data.
        text = input_text
        if not text and input_data:
            text = str(input_data)

        result = await Runner.run(self._agent, text)
        if result.final_output is None:
            return ""
        return str(result.final_output)

    @classmethod
    def _build_default_card(cls, framework_obj: Any = None) -> AgentCard | None:
        """Build an AgentCard from OpenAI Agent metadata."""
        if framework_obj is None:
            return None
        agent = framework_obj
        name = getattr(agent, "name", None) or "OpenAI Agent"
        instructions = getattr(agent, "instructions", None) or ""
        # Use first sentence of instructions as skill description.
        description = instructions.split(".")[0].strip() if instructions else name
        skills = [Skill(id=name.lower().replace(" ", "_"), description=description)]
        return AgentCard(name=name, skills=skills)


async def serve_openai_agent(
    agent: Agent,
    *,
    card: AgentCard | None = None,
    **node_kwargs: Any,
) -> None:
    """Serve an OpenAI Agent as a P2P A2A agent.

    This is the main entry point for OpenAI Agents SDK integration. It starts
    a P2P node, registers the agent's capabilities, and processes incoming
    tasks by running the agent.

    Args:
        agent: An OpenAI Agents SDK ``Agent`` instance.
        card: AgentCard describing the agent and its skills. If ``None``,
            an AgentCard is auto-generated from agent metadata.
        **node_kwargs: Additional keyword arguments forwarded to
            :class:`~agentanycast.node.Node` (e.g. ``relay``, ``key_path``,
            ``home``).
    """
    if card is None:
        card = OpenAIAgentsAdapter._build_default_card(agent)
    adapter = OpenAIAgentsAdapter(agent, card=card, **node_kwargs)
    await adapter.serve()
