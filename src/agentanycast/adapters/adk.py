"""Google ADK adapter -- expose a Google ADK Agent as a P2P A2A agent.

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
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from agentanycast.adapters._base import BaseAdapter
from agentanycast.card import AgentCard, Skill

if TYPE_CHECKING:
    from google.adk.agents import Agent

try:
    from google.adk.agents import Agent as _Agent  # noqa: F401
    from google.adk.runners import InMemoryRunner
    from google.genai.types import Content, Part
except ImportError as _err:
    raise ImportError(
        "Google ADK adapter requires the 'google-adk' package. "
        "Install with: pip install agentanycast[adk]"
    ) from _err

logger = logging.getLogger(__name__)

_USER_ID = "agentanycast"


class ADKAdapter(BaseAdapter):
    """Wraps a Google ADK Agent as an A2A agent."""

    def __init__(self, agent: Agent, *, app_name: str = "agentanycast", **kwargs: Any) -> None:
        self._agent = agent
        self._runner = InMemoryRunner(agent=agent, app_name=app_name)
        # TODO: Add session reuse for multi-turn conversations.
        # Map context_id -> session_id to maintain conversation state across
        # invocations. Requires plumbing context_id through _invoke() or
        # accessing it from task metadata in _handle_task().
        self._sessions: dict[str, str] = {}
        super().__init__(**kwargs)

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

    @classmethod
    def _build_default_card(cls, framework_obj: Any = None) -> AgentCard | None:
        """Build an AgentCard from Google ADK Agent metadata."""
        if framework_obj is None:
            return None
        agent = framework_obj
        name = getattr(agent, "name", None) or "ADK Agent"
        description = getattr(agent, "description", None) or ""
        skills: list[Skill] = []
        if name:
            skills.append(Skill(id=name.lower().replace(" ", "_"), description=description or name))
        return AgentCard(name=name, description=description, skills=skills)


async def serve_adk_agent(
    agent: Agent,
    *,
    card: AgentCard | None = None,
    app_name: str = "agentanycast",
    **node_kwargs: Any,
) -> None:
    """Serve a Google ADK Agent as a P2P A2A agent.

    This is the main entry point for Google ADK integration. It starts a P2P
    node, registers the agent's capabilities, and processes incoming tasks by
    running the ADK agent.

    Args:
        agent: A Google ADK ``Agent`` instance.
        card: AgentCard describing the agent and its skills. If ``None``,
            an AgentCard is auto-generated from agent metadata.
        app_name: Application name passed to the ADK ``InMemoryRunner``.
        **node_kwargs: Additional keyword arguments forwarded to
            :class:`~agentanycast.node.Node` (e.g. ``relay``, ``key_path``,
            ``home``).
    """
    if card is None:
        card = ADKAdapter._build_default_card(agent)
    adapter = ADKAdapter(agent, card=card, app_name=app_name, **node_kwargs)
    await adapter.serve()
