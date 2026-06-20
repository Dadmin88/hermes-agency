"""AgentAnycast Hermes plugin.

Registers the ``agentanycast`` toolset and lifecycle hooks for a per-profile
AgentAnycast node. The node auto-starts only when both the plugin is enabled
and ``agentanycast.auto_start`` is true in the active profile config.
"""

from __future__ import annotations

from .config import get_config
from .node_manager import manager
from .tools import TOOLSET, TOOLS, check_agentanycast_available


def _auto_start_hook(**_: object) -> None:
    """Start the AgentAnycast node when profile config opts in."""

    manager.auto_start_if_configured()


def _shutdown_hook(**_: object) -> None:
    """Stop the AgentAnycast node during session shutdown/reset."""

    manager.stop_background()


def register(ctx) -> None:
    """Register AgentAnycast tools and lifecycle hooks with Hermes."""

    for name, schema, handler, emoji in TOOLS:
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handler,
            check_fn=check_agentanycast_available,
            emoji=emoji,
        )

    ctx.register_hook("on_session_start", _auto_start_hook)
    ctx.register_hook("on_session_end", _shutdown_hook)
    ctx.register_hook("on_session_finalize", _shutdown_hook)
    ctx.register_hook("on_session_reset", _shutdown_hook)

    # Discovery/load happens before hooks fire in many Hermes entry points. If
    # the operator explicitly enabled auto_start, kick it once at registration
    # too so gateway/desktop launches can bring the node up without waiting for
    # a specific session-start event. This remains non-blocking.
    cfg = get_config()
    if cfg.enabled and cfg.auto_start:
        manager.start_background()
