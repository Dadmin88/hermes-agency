"""OpenAI Agents SDK adapter — expose an OpenAI Agent as a P2P A2A agent.

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
from typing import Any

try:
    from agents import Agent, Runner  # noqa: F401
except ImportError as _err:
    raise ImportError(
        "OpenAI Agents adapter requires the 'openai-agents' package. "
        "Install with: pip install agentanycast[openai-agents]"
    ) from _err

from agentanycast.adapters._base import BaseAdapter
from agentanycast.card import AgentCard

logger = logging.getLogger(__name__)


class OpenAIAgentsAdapter(BaseAdapter):
    """Wraps an OpenAI Agents SDK Agent as an A2A agent."""

    def __init__(self, agent: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agent = agent

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


async def serve_openai_agent(
    agent: Any,
    *,
    card: AgentCard,
    relay: str | None = None,
    key_path: str | None = None,
    home: str | None = None,
) -> None:
    """Serve an OpenAI Agent as a P2P A2A agent.

    This is the main entry point for OpenAI Agents SDK integration. It starts
    a P2P node, registers the agent's capabilities, and processes incoming
    tasks by running the agent.

    Args:
        agent: An OpenAI Agents SDK ``Agent`` instance.
        card: AgentCard describing the agent and its skills.
        relay: Relay server multiaddr.
        key_path: Path to libp2p identity key.
        home: Data directory for daemon state.
    """
    adapter = OpenAIAgentsAdapter(agent, card=card, relay=relay, key_path=key_path, home=home)
    await adapter.serve()
