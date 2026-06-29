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
    "--host",
    default="127.0.0.1",
    help="HTTP bind address (only used with --transport http). Defaults to localhost.",
)
@click.option(
    "--allow-http-bridge",
    is_flag=True,
    default=False,
    help="Explicitly enable HTTP transport. Required for --transport http.",
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
def mcp_cmd(
    transport: str,
    port: int,
    host: str,
    allow_http_bridge: bool,
    relay: str | None,
    home: str | None,
) -> None:
    """Start the MCP server for AI tool integration.

    Exposes AgentAnycast P2P networking as MCP tools so that AI
    assistants (Claude Desktop, Cursor, VS Code, Gemini CLI, etc.)
    can discover agents, send encrypted tasks, and query the network.

    \b
    Examples:
        agentanycast mcp                    # stdio (default)
        agentanycast mcp --transport http --allow-http-bridge   # HTTP on port 8080
        agentanycast mcp --relay /ip4/...   # connect via relay
    """
    from agentanycast.mcp_server import configure, run_server

    configure(relay=relay, home=home, allow_http_bridge=allow_http_bridge)
    run_server(transport=transport, port=port, host=host)
