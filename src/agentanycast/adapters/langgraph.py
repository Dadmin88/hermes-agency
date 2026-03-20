"""LangGraph adapter -- expose a LangGraph Graph as a P2P A2A agent.

Usage:
    from langgraph.graph import StateGraph
    from agentanycast import AgentCard, Skill
    from agentanycast.adapters.langgraph import serve_graph

    graph = StateGraph(...)
    compiled = graph.compile()
    card = AgentCard(
        name="QA Agent",
        skills=[Skill(id="qa", description="Answer questions")],
    )

    await serve_graph(compiled, card=card, relay="/ip4/.../p2p/12D3KooW...")
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from agentanycast.adapters._base import BaseAdapter
from agentanycast.card import AgentCard, Skill

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

try:
    import langgraph  # noqa: F401
except ImportError as _err:
    raise ImportError(
        "LangGraph adapter requires the 'langgraph' package. "
        "Install with: pip install agentanycast[langgraph]"
    ) from _err

logger = logging.getLogger(__name__)


class LangGraphAdapter(BaseAdapter):
    """Wraps a compiled LangGraph graph as an A2A agent."""

    def __init__(
        self, graph: CompiledStateGraph, *, input_key: str = "input", **kwargs: Any
    ) -> None:
        self._graph = graph
        self._input_key = input_key
        super().__init__(**kwargs)

    async def _invoke(
        self,
        input_text: str,
        input_data: dict[str, Any] | None,
    ) -> str | dict[str, Any]:
        """Run the graph with the given input.

        LangGraph's ``invoke()`` can be sync or async depending on the graph.
        We try async first, then fall back to sync in a thread executor.
        """
        state = input_data or {}
        if input_text and self._input_key not in state:
            state[self._input_key] = input_text

        # Try async invoke first (LangGraph compiled graphs support ainvoke).
        if hasattr(self._graph, "ainvoke"):
            result = await self._graph.ainvoke(state)
        else:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self._graph.invoke(state))

        # Extract output -- LangGraph returns a dict of final state.
        if isinstance(result, dict):
            # Common output patterns: "output", "response", "result", or last message
            for key in ("output", "response", "result", "answer"):
                if key in result:
                    val = result[key]
                    return str(val) if not isinstance(val, dict) else val
            # If we have messages, return the last one
            if "messages" in result and result["messages"]:
                last_msg = result["messages"][-1]
                if hasattr(last_msg, "content"):
                    return str(last_msg.content)
            return result
        return str(result)

    @classmethod
    def _build_default_card(cls, framework_obj: Any = None) -> AgentCard | None:
        """Build an AgentCard from LangGraph graph metadata."""
        if framework_obj is None:
            return None
        graph = framework_obj
        name = "LangGraph Agent"
        skills: list[Skill] = []
        # Extract node names as skills (excluding internal __start__/__end__).
        nodes = getattr(graph, "nodes", None) or {}
        for node_name in nodes:
            if not node_name.startswith("__"):
                skills.append(Skill(id=node_name, description=node_name))
        return AgentCard(name=name, skills=skills)


async def serve_graph(
    graph: CompiledStateGraph,
    *,
    card: AgentCard | None = None,
    input_key: str = "input",
    **node_kwargs: Any,
) -> None:
    """Serve a LangGraph graph as a P2P A2A agent.

    This is the main entry point for LangGraph integration. It starts a P2P node,
    registers the graph's capabilities, and processes incoming tasks by running
    the graph workflow.

    Args:
        graph: A compiled LangGraph graph (result of ``StateGraph.compile()``).
        card: AgentCard describing the agent and its skills. If ``None``,
            an AgentCard is auto-generated from graph node names.
        input_key: Key name for text input in the graph state dict.
        **node_kwargs: Additional keyword arguments forwarded to
            :class:`~agentanycast.node.Node` (e.g. ``relay``, ``key_path``,
            ``home``).
    """
    if card is None:
        card = LangGraphAdapter._build_default_card(graph)
    adapter = LangGraphAdapter(graph, card=card, input_key=input_key, **node_kwargs)
    await adapter.serve()
