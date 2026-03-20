"""MCP server CLI commands."""

from __future__ import annotations

import click


@click.command("mcp")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"]),
    default="stdio",
    help="Transport mode: stdio (Claude Desktop, Cursor) or http (remote clients).",
)
@click.option(
    "--port",
    type=int,
    default=8080,
    help="HTTP port (only used with --transport http).",
)
@click.option(
    "--relay",
    default=None,
    help="Relay server multiaddr for cross-network communication.",
)
@click.option(
    "--home",
    default=None,
    help="Data directory for daemon state.",
)
def mcp_cmd(transport: str, port: int, relay: str | None, home: str | None) -> None:
    """Start the MCP server for AI tool integration.

    Exposes AgentAnycast P2P networking as MCP tools so that AI
    assistants (Claude Desktop, Cursor, VS Code, Gemini CLI, etc.)
    can discover agents, send encrypted tasks, and query the network.

    \b
    Examples:
        agentanycast mcp                    # stdio (default)
        agentanycast mcp --transport http   # HTTP on port 8080
        agentanycast mcp --relay /ip4/...   # connect via relay
    """
    from agentanycast.mcp_server import configure, run_server

    configure(relay=relay, home=home)
    run_server(transport=transport, port=port)
