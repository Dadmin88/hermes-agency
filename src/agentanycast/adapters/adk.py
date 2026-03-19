"""Google ADK adapter — expose a Google ADK Agent as a P2P A2A agent.

Usage:
    from google.adk.agents import Agent
    from agentanycast import AgentCard, Skill
    from agentanycast.adapters.adk import serve_adk_agent

    agent = Agent(
        name="helper",
        model="gemini-2.0-flash",
        instruction="You are a helpful assistant.",
    )
    card = AgentCard(
        name="Helper Agent",
        skills=[Skill(id="help", description="Answer general questions")],
    )

    await serve_adk_agent(agent, card=card, relay="/ip4/.../p2p/12D3KooW...")
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

try:
    from google.adk.agents import Agent  # noqa: F401
    from google.adk.runners import InMemoryRunner
    from google.genai.types import Content, Part
except ImportError as _err:
    raise ImportError(
        "Google ADK adapter requires the 'google-adk' package. "
        "Install with: pip install agentanycast[adk]"
    ) from _err

from agentanycast.adapters._base import BaseAdapter
from agentanycast.card import AgentCard

logger = logging.getLogger(__name__)

_USER_ID = "agentanycast"


class ADKAdapter(BaseAdapter):
    """Wraps a Google ADK Agent as an A2A agent."""

    def __init__(self, agent: Any, *, app_name: str = "agentanycast", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agent = agent
        self._runner = InMemoryRunner(agent=agent, app_name=app_name)

    async def _invoke(self, input_text: str, input_data: dict[str, Any] | None) -> str:
        """Run the ADK agent with the given input.

        Creates a new session for each invocation and streams events from the
        runner, collecting the final response text.
        """
        # Build the input message. Prefer text; fall back to stringified data.
        text = input_text
        if not text and input_data:
            text = str(input_data)

        content = Content(role="user", parts=[Part.from_text(text)])
        session_id = str(uuid4())

        # Collect text from the final response event(s).
        response_parts: list[str] = []
        async for event in self._runner.run_async(
            user_id=_USER_ID,
            session_id=session_id,
            new_message=content,
        ):
            if (
                event.content
                and event.content.parts
                and hasattr(event, "actions")
                and event.actions
                and event.actions.is_final_response()
            ):
                for part in event.content.parts:
                    if part.text:
                        response_parts.append(part.text)

        if not response_parts:
            logger.debug("ADK agent produced no final response text")
            return ""
        return "\n".join(response_parts)


async def serve_adk_agent(
    agent: Any,
    *,
    card: AgentCard,
    relay: str | None = None,
    key_path: str | None = None,
    home: str | None = None,
    app_name: str = "agentanycast",
) -> None:
    """Serve a Google ADK Agent as a P2P A2A agent.

    This is the main entry point for Google ADK integration. It starts a P2P
    node, registers the agent's capabilities, and processes incoming tasks by
    running the ADK agent.

    Args:
        agent: A Google ADK ``Agent`` instance.
        card: AgentCard describing the agent and its skills.
        relay: Relay server multiaddr.
        key_path: Path to libp2p identity key.
        home: Data directory for daemon state.
        app_name: Application name passed to the ADK ``InMemoryRunner``.
    """
    adapter = ADKAdapter(
        agent, card=card, relay=relay, key_path=key_path, home=home, app_name=app_name
    )
    await adapter.serve()
