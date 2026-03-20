"""Claude Agent SDK adapter -- expose a Claude Agent as a P2P A2A agent.

Usage:
    from claude_agent_sdk import ClaudeAgentOptions
    from agentanycast import AgentCard, Skill
    from agentanycast.adapters.claude_agent import serve_claude_agent

    options = ClaudeAgentOptions(allowed_tools=["computer"])
    card = AgentCard(
        name="Claude Helper",
        skills=[Skill(id="help", description="Answer general questions")],
    )

    await serve_claude_agent(
        prompt_template="You are a helpful assistant.",
        options=options,
        card=card,
        relay="/ip4/.../p2p/12D3KooW...",
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agentanycast.adapters._base import BaseAdapter
from agentanycast.card import AgentCard

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeAgentOptions

try:
    from claude_agent_sdk import ClaudeAgentOptions as _ClaudeAgentOptions  # noqa: F401
    from claude_agent_sdk import query
except ImportError as _err:
    raise ImportError(
        "Claude Agent SDK adapter requires the 'claude-agent-sdk' package. "
        "Install with: pip install agentanycast[claude]"
    ) from _err

logger = logging.getLogger(__name__)


class ClaudeAgentAdapter(BaseAdapter):
    """Wraps Claude Agent SDK's query API as an A2A agent."""

    def __init__(
        self,
        *,
        prompt_template: str = "",
        options: ClaudeAgentOptions | None = None,
        **kwargs: Any,
    ) -> None:
        self._prompt_template = prompt_template
        self._options = options
        super().__init__(**kwargs)

    async def _invoke(self, input_text: str, input_data: dict[str, Any] | None) -> str:
        """Run Claude Agent SDK query with the given input.

        ``query()`` is an async generator, so we iterate to collect the
        final result.
        """
        # Prefer text input; fall back to stringified data.
        text = input_text
        if not text and input_data:
            text = str(input_data)

        if self._prompt_template:
            text = f"{self._prompt_template}\n\n{text}"

        result_text = ""
        async for message in query(prompt=text, options=self._options):
            if hasattr(message, "result") and message.result is not None:
                result_text = str(message.result)

        if not result_text:
            logger.debug("Claude Agent SDK query produced no result text")
        return result_text

    @classmethod
    def _build_default_card(cls, framework_obj: Any = None) -> AgentCard | None:
        """Return ``None`` — Claude Agent SDK has no persistent agent object.

        Unlike other adapters, Claude Agent SDK works with prompt templates
        rather than agent objects, so there is no metadata to auto-extract.
        Callers must pass an explicit ``card=`` to ``serve_claude_agent()``.
        """
        return None


async def serve_claude_agent(
    *,
    prompt_template: str = "",
    options: ClaudeAgentOptions | None = None,
    card: AgentCard | None = None,
    **node_kwargs: Any,
) -> None:
    """Serve a Claude Agent as a P2P A2A agent.

    This is the main entry point for Claude Agent SDK integration. It starts
    a P2P node, registers the agent's capabilities, and processes incoming
    tasks by running the Claude Agent SDK query function.

    Args:
        prompt_template: A prompt template string prepended to each incoming
            task's input text before calling ``query()``.
        options: A ``ClaudeAgentOptions`` instance controlling the agent's
            behavior (e.g. ``allowed_tools``).
        card: AgentCard describing the agent and its skills. Required —
            Claude Agent SDK has no persistent agent object to auto-extract
            metadata from.
        **node_kwargs: Additional keyword arguments forwarded to
            :class:`~agentanycast.node.Node` (e.g. ``relay``, ``key_path``,
            ``home``).
    """
    if card is None:
        card = ClaudeAgentAdapter._build_default_card()
    adapter = ClaudeAgentAdapter(
        prompt_template=prompt_template,
        options=options,
        card=card,
        **node_kwargs,
    )
    await adapter.serve()
