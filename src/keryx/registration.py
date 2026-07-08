"""Agent registration helpers (AgentAnycast-compatible signatures)."""

from __future__ import annotations

from typing import Any

from keryx.card import AgentCard


async def register_agent(
    node: Any,
    card: AgentCard,
    *,
    capacity: int | None = None,
    current_load: int = 0,
) -> dict[str, Any]:
    if not hasattr(node, "register_skills"):
        raise TypeError("node must provide register_skills()")
    return await node.register_skills(card, capacity=capacity, current_load=current_load)


async def deregister_agent(node: Any, *, card: AgentCard | None = None) -> dict[str, Any]:
    if not hasattr(node, "deregister_skills"):
        raise TypeError("node must provide deregister_skills()")
    return await node.deregister_skills(card)