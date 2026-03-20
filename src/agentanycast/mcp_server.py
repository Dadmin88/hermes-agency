"""MCP Server for AgentAnycast — expose P2P networking as MCP tools.

Enables any MCP-compatible AI tool (Claude Desktop, Cursor, VS Code,
Gemini CLI, etc.) to discover agents, send encrypted tasks, and query
the AgentAnycast P2P network.

Usage::

    agentanycast mcp                    # stdio mode (Claude Desktop, Cursor)
    agentanycast mcp --transport http   # HTTP mode (ChatGPT, remote)
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from agentanycast.card import AgentCard, Skill
from agentanycast.node import Node

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "agentanycast",
    instructions=(
        "AgentAnycast P2P network tools for discovering and communicating "
        "with AI agents over encrypted peer-to-peer connections."
    ),
)

# ── Node Singleton Management ────────────────────────────────────────

_node: Node | None = None
_node_lock = asyncio.Lock()
_configured = False

# Runtime configuration set by the CLI before starting the server.
_relay: str | None = None
_home: str | None = None


def configure(*, relay: str | None = None, home: str | None = None) -> None:
    """Set runtime options before the MCP server starts.

    Called by the CLI layer to pass ``--relay`` / ``--home`` flags
    through to the underlying :class:`Node`.

    Must be called **before** the first MCP tool invocation creates the
    singleton Node.  Calling after the Node is already running logs a
    warning and has no effect.
    """
    global _relay, _home, _configured  # noqa: PLW0603
    if _node is not None and _node.is_running:
        logger.warning(
            "configure() called after Node already started — new settings will not take effect"
        )
        return
    _relay = relay
    _home = home
    _configured = True


async def _get_node() -> Node:
    """Get or create the singleton Node instance."""
    global _node  # noqa: PLW0603
    async with _node_lock:
        if _node is None or not _node.is_running:
            card = AgentCard(
                name="MCP Bridge",
                description="MCP-to-P2P bridge for AI tool integration",
                skills=[
                    Skill(id="mcp_bridge", description="Bridge MCP requests to P2P network"),
                ],
            )
            _node = Node(card=card, relay=_relay, home=_home)
            await _node.start()
    return _node


async def _shutdown_node() -> None:
    """Gracefully stop the singleton Node (if running)."""
    global _node  # noqa: PLW0603
    if _node is not None and _node.is_running:
        await _node.stop()
        _node = None


def _card_to_dict(card: AgentCard) -> dict[str, Any]:
    """Serialize an AgentCard to a JSON-friendly dict."""
    card_dict: dict[str, Any] = {
        "name": card.name,
        "description": card.description,
        "version": card.version,
        "skills": [{"id": s.id, "description": s.description} for s in card.skills],
    }
    if card.peer_id:
        card_dict["peer_id"] = card.peer_id
    if card.did_key:
        card_dict["did_key"] = card.did_key
    return card_dict


# ── Tool Implementations ─────────────────────────────────────────────
# Match the Go daemon's 7 MCP tools exactly (names, descriptions, params).


@mcp.tool()
async def get_node_info() -> str:
    """Get this node's identity and network information."""
    try:
        node = await _get_node()
        did_key = ""
        if node.peer_id:
            try:
                from agentanycast.did import peer_id_to_did_key

                did_key = peer_id_to_did_key(node.peer_id)
            except Exception:
                pass
        peers = await node.list_peers()
        info = {
            "peer_id": node.peer_id,
            "did_key": did_key,
            "connected_peers": len(peers),
        }
        return json.dumps(info, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


@mcp.tool()
async def list_connected_peers() -> str:
    """List all peers currently connected to this node."""
    try:
        node = await _get_node()
        peers = await node.list_peers()
        return json.dumps({"count": len(peers), "peers": peers}, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


@mcp.tool()
async def discover_agents(skill: str) -> str:
    """Find agents on the P2P network offering a specific skill."""
    try:
        node = await _get_node()
        agents = await node.discover(skill)
        return json.dumps({"skill": skill, "agent_count": len(agents), "agents": agents}, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


@mcp.tool()
async def send_task(
    target: str,
    message: str,
    by_skill: bool = False,
    timeout: float = 30.0,
) -> str:
    """Send an encrypted A2A task to a remote AI agent."""
    try:
        node = await _get_node()
        kwargs: dict[str, Any] = {}

        if by_skill:
            kwargs["skill"] = target
            mode = "anycast"
        elif target.startswith(("http://", "https://")):
            kwargs["url"] = target
            mode = "http_bridge"
        else:
            kwargs["peer_id"] = target
            mode = "direct"

        handle = await node.send_task({"role": "user", "parts": [{"text": message}]}, **kwargs)
        task = await handle.wait(timeout=timeout)

        result: dict[str, Any] = {
            "task_id": task.task_id,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "target": target,
            "mode": mode,
        }

        if task.artifacts:
            artifacts_data = []
            for a in task.artifacts:
                parts_data = []
                for p in a.parts:
                    if p.text is not None:
                        parts_data.append({"text": p.text})
                    elif p.data is not None:
                        try:
                            parts_data.append({"data": json.loads(json.dumps(p.data))})
                        except (TypeError, ValueError):
                            parts_data.append({"data": str(p.data)})
                artifacts_data.append({"name": a.name, "parts": parts_data})
            result["artifacts"] = artifacts_data

        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


@mcp.tool()
async def send_task_by_skill(skill: str, message: str) -> str:
    """Send a task using anycast routing to the best agent for a skill."""
    return await send_task(target=skill, message=message, by_skill=True)


@mcp.tool()
async def get_task_status(task_id: str) -> str:
    """Get the current status and result of a previously sent task."""
    try:
        node = await _get_node()
        # Look up the in-memory task handle for the current session.
        handle = node._tasks.get(task_id)
        if handle is None:
            return json.dumps(
                {
                    "task_id": task_id,
                    "error": "Task not found in current session.",
                },
                indent=2,
            )
        status = handle.status
        result: dict[str, Any] = {
            "task_id": task_id,
            "status": status.value if hasattr(status, "value") else str(status),
        }
        if handle.artifacts:
            result["artifact_count"] = len(handle.artifacts)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


@mcp.tool()
async def get_agent_card(peer_id: str = "") -> str:
    """Get the A2A Agent Card for a connected peer or this node."""
    try:
        node = await _get_node()

        if not peer_id or peer_id == "self":
            return json.dumps(_card_to_dict(node.card), indent=2)

        remote_card = await node.get_card(peer_id)
        return json.dumps(_card_to_dict(remote_card), indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


# ── Entry Point ──────────────────────────────────────────────────────


def _sync_shutdown() -> None:
    """Best-effort synchronous cleanup for atexit."""
    if _node is not None and _node.is_running:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_shutdown_node())
            else:
                loop.run_until_complete(_shutdown_node())
        except Exception:
            pass


def run_server(transport: str = "stdio", port: int = 8080) -> None:
    """Start the MCP server with the given transport.

    Args:
        transport: ``"stdio"`` for local MCP clients (Claude Desktop,
            Cursor) or ``"http"`` for remote / web-based clients.
        port: Port number when *transport* is ``"http"``.
    """
    atexit.register(_sync_shutdown)
    if transport == "http":
        mcp.settings.port = port
    mcp.run(transport=transport)


def main() -> None:
    """Entry point for ``agentanycast-mcp`` script.

    Starts the MCP server in stdio mode (the most common use case
    for AI tool integrations like Claude Desktop and Cursor).
    """
    run_server(transport="stdio")
