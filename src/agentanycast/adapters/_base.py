"""Base adapter class for framework integrations."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from agentanycast.card import AgentCard
from agentanycast.node import Node
from agentanycast.task import Artifact, IncomingTask, Part

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """Base class for framework adapters.

    Subclasses implement ``_invoke()`` to translate between A2A messages
    and the framework's native input/output format.
    """

    def __init__(
        self,
        *,
        card: AgentCard | None = None,
        **node_kwargs: Any,
    ) -> None:
        if card is None:
            card = self._build_default_card()
        if card is None:
            raise ValueError(
                "An AgentCard is required. Pass card= explicitly or override "
                "_build_default_card() in your adapter subclass."
            )
        self._card = card
        self._node = Node(card=card, **node_kwargs)

    @abstractmethod
    async def _invoke(
        self,
        input_text: str,
        input_data: dict[str, Any] | None,
    ) -> str | dict[str, Any]:
        """Invoke the wrapped framework.

        Args:
            input_text: Text extracted from the incoming A2A message.
            input_data: Structured data extracted from the message (if any).

        Returns:
            String output or dict output from the framework.
        """
        ...

    async def _invoke_stream(
        self,
        input_text: str,
        input_data: dict[str, Any] | None,
    ) -> AsyncIterator[str]:
        """Override for streaming responses. Default yields full result."""
        result = await self._invoke(input_text, input_data)
        yield str(result) if not isinstance(result, str) else result

    @classmethod
    def _build_default_card(cls, framework_obj: Any = None) -> AgentCard | None:
        """Build an AgentCard from framework metadata.

        Subclasses may override this to auto-generate a card from the
        wrapped framework object. Returns ``None`` if not implemented.
        """
        return None

    async def _handle_task(self, task: IncomingTask) -> None:
        """Default task handler that translates A2A -> framework -> A2A."""
        await task.update_status("working")

        try:
            # Extract text and data from the incoming message.
            text_parts: list[str] = []
            input_data: dict[str, Any] | None = None
            for msg in task.messages:
                for part in msg.parts:
                    if part.text:
                        text_parts.append(part.text)
                    if part.data:
                        input_data = part.data
            input_text = "\n".join(text_parts)

            # Invoke the framework.
            result = await self._invoke(input_text, input_data)

            # Translate output back to A2A artifacts.
            if isinstance(result, str):
                artifact = Artifact(
                    name="output",
                    parts=[Part(text=result)],
                )
            elif isinstance(result, dict):
                artifact = Artifact(
                    name="output",
                    parts=[Part(data=result)],
                )
            else:
                artifact = Artifact(
                    name="output",
                    parts=[Part(text=str(result))],
                )

            await task.complete(artifacts=[artifact])

        except Exception as e:
            logger.exception("Framework invocation failed")
            await task.fail(str(e))

    async def serve(self) -> None:
        """Start serving as a P2P A2A agent."""
        async with self._node as node:
            node.on_task(self._handle_task)
            await node.serve_forever()
