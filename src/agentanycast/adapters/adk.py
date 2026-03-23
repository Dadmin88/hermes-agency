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
from agentanycast.task import Artifact, IncomingTask, Part

if TYPE_CHECKING:
    from google.adk.agents import Agent

try:
    from google.adk.agents import Agent as _Agent  # noqa: F401
    from google.adk.runners import InMemoryRunner
    from google.genai.types import Content, Part as GenaiPart
except ImportError as _err:
    raise ImportError(
        "Google ADK adapter requires the 'google-adk' package. "
        "Install with: pip install agentanycast[adk]"
    ) from _err

logger = logging.getLogger(__name__)

_USER_ID = "agentanycast"


class ADKAdapter(BaseAdapter):
    """Wraps a Google ADK Agent as an A2A agent.

    Supports multi-turn conversations by reusing ADK sessions across tasks
    that share the same ``context_id``. When a task has a non-empty
    ``context_id``, the adapter looks up or creates a session for that
    context, enabling the ADK agent to recall prior conversation turns.
    """

    def __init__(self, agent: Agent, *, app_name: str = "agentanycast", **kwargs: Any) -> None:
        self._agent = agent
        self._runner = InMemoryRunner(agent=agent, app_name=app_name)
        # Map context_id -> session_id for multi-turn conversation state.
        self._sessions: dict[str, str] = {}
        super().__init__(**kwargs)

    async def _invoke(self, input_text: str, input_data: dict[str, Any] | None) -> str:
        """Run the ADK agent with a new session (single-turn fallback)."""
        return await self._invoke_with_context(input_text, input_data, context_id="")

    async def _invoke_with_context(
        self,
        input_text: str,
        input_data: dict[str, Any] | None,
        context_id: str = "",
    ) -> str:
        """Run the ADK agent, reusing sessions for the same context_id.

        Args:
            input_text: Text extracted from the incoming A2A message.
            input_data: Structured data (if any).
            context_id: A2A context identifier. Tasks sharing the same
                context_id will share an ADK session, enabling multi-turn
                conversation state.

        Returns:
            The final response text from the ADK agent.
        """
        text = input_text
        if not text and input_data:
            text = str(input_data)

        content = Content(role="user", parts=[GenaiPart.from_text(text)])

        # Reuse session for the same context, or create a new one.
        if context_id and context_id in self._sessions:
            session_id = self._sessions[context_id]
            logger.debug("reusing ADK session %s for context %s", session_id, context_id)
        else:
            session_id = str(uuid4())
            if context_id:
                self._sessions[context_id] = session_id
                logger.debug(
                    "created ADK session %s for context %s", session_id, context_id
                )

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

    async def _handle_task(self, task: IncomingTask) -> None:
        """Override base handler to pass context_id for session reuse."""
        await task.update_status("working")

        try:
            text_parts: list[str] = []
            input_data: dict[str, Any] | None = None
            for msg in task.messages:
                for part in msg.parts:
                    if part.text:
                        text_parts.append(part.text)
                    if part.data:
                        input_data = part.data
            input_text = "\n".join(text_parts)

            # Pass context_id from the task for session reuse.
            context_id = getattr(task._task, "context_id", "") or ""
            result = await self._invoke_with_context(input_text, input_data, context_id)

            artifact = Artifact(
                name="output",
                parts=[Part(text=result)],
            )
            await task.complete(artifacts=[artifact])

        except Exception as e:
            logger.exception("ADK agent invocation failed")
            await task.fail(str(e))

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
