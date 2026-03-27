"""CLI entry point for AgentAnycast.

Usage:
    agentanycast demo                     # Start an echo agent
    agentanycast discover [--skill ...]   # Discover agents
    agentanycast send <peer_id> "msg"     # Send a task
    agentanycast status                   # Show local node status
    agentanycast info                     # Show version and config
    agentanycast mcp                      # Start MCP server (stdio)
"""

from __future__ import annotations

import asyncio
import sys
import time

import click

from agentanycast import __version__


@click.group()
@click.version_option(version=__version__, prog_name="agentanycast")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output (daemon logs).")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """AgentAnycast — P2P runtime for the A2A protocol."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


# Register sub-commands from separate modules.
from agentanycast.cli.mcp import mcp_cmd  # noqa: E402

cli.add_command(mcp_cmd)


@cli.command()
@click.option("--relay", default=None, help="Relay server multiaddr.")
@click.option("--home", default=None, help="Data directory.")
@click.pass_context
def demo(ctx: click.Context, relay: str | None, home: str | None) -> None:
    """Start a demo echo agent that responds to any incoming task."""
    verbose = ctx.obj.get("verbose", False)
    asyncio.run(_demo(relay, home, verbose=verbose))


def _cli_status(msg: str) -> None:
    """Print a status message with cyan styling."""
    click.echo(click.style(f"  {msg}", fg="cyan"))


def _setup_verbose() -> None:
    """Enable verbose logging to stdout."""
    import logging

    logging.basicConfig(level=logging.DEBUG, format="  [%(name)s] %(message)s")


async def _demo(relay: str | None, home: str | None, *, verbose: bool = False) -> None:
    if verbose:
        _setup_verbose()

    from agentanycast import AgentCard, IncomingTask, Node, Part, Skill
    from agentanycast.task import Artifact

    card = AgentCard(
        name="Echo Agent",
        description="A demo agent that echoes back any message it receives.",
        skills=[Skill(id="echo", description="Echo back the input message.")],
    )

    click.echo()
    async with Node(card=card, relay=relay, home=home, status_callback=_cli_status) as node:
        peer_id = node.peer_id

        click.echo()
        click.echo(click.style("  Echo Agent is running!", fg="green", bold=True))
        click.echo()
        click.echo(f"  Peer ID:  {click.style(peer_id, bold=True)}")
        click.echo("  Skill:    echo")
        if relay:
            click.echo(f"  Relay:    {relay}")
        click.echo()
        click.echo(
            click.style("  Try it", fg="yellow", bold=True) + " -- open another terminal and run:"
        )
        click.echo()
        # Use a different home to avoid "dial to self" (same daemon, same key).
        send_home = "~/.agentanycast-client"
        click.echo(
            click.style(
                f'    agentanycast send --home {send_home} {peer_id} "Hello, world!"', bold=True
            )
        )
        click.echo()
        click.echo("  Waiting for incoming tasks... (Ctrl+C to stop)")
        click.echo()

        @node.on_task
        async def handle(task: IncomingTask) -> None:
            t0 = time.monotonic()
            input_text = ""
            for msg in task.messages:
                for part in msg.parts:
                    if part.text:
                        input_text += part.text

            await task.complete(
                artifacts=[Artifact(name="echo", parts=[Part(text=f"Echo: {input_text}")])]
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            task_short = task.task_id[:8]
            click.echo(
                click.style("  Task received ", fg="cyan")
                + f"[{task_short}...] "
                + click.style(f"{elapsed_ms:.0f}ms", fg="green")
            )
            click.echo(f"    Input:  {input_text!r}")
            click.echo(click.style(f"    Reply:  Echo: {input_text}", fg="green"))
            click.echo()

        try:
            await node.serve_forever()
        except KeyboardInterrupt:
            pass


@cli.command()
@click.argument("skill")
@click.option("--tag", "-t", multiple=True, help="Filter by tag (key=value). Can be repeated.")
@click.option("--relay", default=None, help="Relay server multiaddr.")
@click.option("--home", default=None, help="Data directory.")
@click.pass_context
def discover(
    ctx: click.Context, skill: str, tag: tuple[str, ...], relay: str | None, home: str | None
) -> None:
    """Discover agents offering a specific skill."""
    verbose = ctx.obj.get("verbose", False)
    tags: dict[str, str] | None = None
    if tag:
        tags = {}
        for t in tag:
            if "=" not in t:
                click.echo(f"Invalid tag format: {t!r} (expected key=value)", err=True)
                raise SystemExit(1)
            k, v = t.split("=", 1)
            tags[k] = v
    asyncio.run(_discover(skill, tags, relay, home, verbose=verbose))


async def _discover(
    skill: str,
    tags: dict[str, str] | None,
    relay: str | None,
    home: str | None,
    *,
    verbose: bool = False,
) -> None:
    if verbose:
        _setup_verbose()
    from agentanycast import AgentCard, Node

    card = AgentCard(name="CLI Discovery Client")
    async with Node(card=card, relay=relay, home=home) as node:
        agents = await node.discover(skill, tags=tags)
        if not agents:
            click.echo(f"No agents found for skill '{skill}'.")
            return

        click.echo(f"Found {len(agents)} agent(s) with skill '{skill}':")
        for agent in agents:
            click.echo(f"  PeerID: {agent['peer_id']}")
            click.echo(f"    Name: {agent['agent_name']}")
            click.echo(f"    Desc: {agent['agent_description']}")
            click.echo()


@cli.command()
@click.argument("target")
@click.argument("message")
@click.option("--skill", is_flag=True, help="Treat target as a skill ID instead of PeerID.")
@click.option("--url", is_flag=True, help="Treat target as an HTTP A2A URL.")
@click.option("--relay", default=None, help="Relay server multiaddr.")
@click.option("--home", default=None, help="Data directory.")
@click.option("--timeout", default=30, help="Wait timeout in seconds.")
@click.pass_context
def send(
    ctx: click.Context,
    target: str,
    message: str,
    skill: bool,
    url: bool,
    relay: str | None,
    home: str | None,
    timeout: int,
) -> None:
    """Send a task to a remote agent and print the response."""
    verbose = ctx.obj.get("verbose", False)
    asyncio.run(_send(target, message, skill, url, relay, home, timeout, verbose=verbose))


async def _send(
    target: str,
    message: str,
    is_skill: bool,
    is_url: bool,
    relay: str | None,
    home: str | None,
    timeout: int,
    *,
    verbose: bool = False,
) -> None:
    if verbose:
        _setup_verbose()
    from agentanycast import AgentCard, Message, Node, Part

    click.echo()
    card = AgentCard(name="CLI Client")
    async with Node(card=card, relay=relay, home=home, status_callback=_cli_status) as node:
        msg = Message(role="user", parts=[Part(text=message)])

        peer_id_val: str | None = None
        skill_val: str | None = None
        url_val: str | None = None

        if is_skill:
            skill_val = target
            click.echo(click.style(f"  Sending via anycast (skill={target})...", fg="cyan"))
        elif is_url:
            url_val = target
            click.echo(click.style(f"  Sending via HTTP bridge ({target})...", fg="cyan"))
        else:
            peer_id_val = target
            click.echo(click.style(f"  Sending to {target[:20]}...", fg="cyan"))

        t0 = time.monotonic()
        handle = await node.send_task(msg, peer_id=peer_id_val, skill=skill_val, url=url_val)
        result = await handle.wait(timeout=timeout)
        elapsed = time.monotonic() - t0

        click.echo()
        click.echo(
            click.style("  Task completed ", fg="green", bold=True)
            + click.style(f"({elapsed:.1f}s)", fg="cyan")
        )
        click.echo(f"  Status: {result.status.value}")
        for artifact in result.artifacts:
            for part in artifact.parts:
                if part.text:
                    click.echo(f"  Response: {click.style(part.text, bold=True)}")
        click.echo()


@cli.command()
@click.option("--relay", default=None, help="Relay server multiaddr.")
@click.option("--home", default=None, help="Data directory.")
@click.pass_context
def status(ctx: click.Context, relay: str | None, home: str | None) -> None:
    """Show local node status."""
    verbose = ctx.obj.get("verbose", False)
    asyncio.run(_status(relay, home, verbose=verbose))


async def _status(relay: str | None, home: str | None, *, verbose: bool = False) -> None:
    if verbose:
        _setup_verbose()

    from agentanycast import AgentCard, Node

    click.echo()
    card = AgentCard(name="CLI Status")
    async with Node(card=card, relay=relay, home=home, status_callback=_cli_status) as node:
        click.echo()
        click.echo(click.style("  Node Status", fg="cyan", bold=True))
        click.echo(f"  Peer ID:    {click.style(node.peer_id, bold=True)}")

        peers = await node.list_peers()
        click.echo(f"  Peers:      {len(peers)} connected")
        if relay:
            click.echo(f"  Relay:      {relay}")
        else:
            click.echo(click.style("  Relay:      none (LAN only)", fg="yellow"))

        if peers:
            click.echo()
            for p in peers:
                click.echo(f"    {p['peer_id']}")

        click.echo()
        click.echo("  Next steps:")
        click.echo("    agentanycast demo                          # Start echo agent")
        click.echo('    agentanycast send <PEER_ID> "Hello!"       # Send a task')
        click.echo()


@cli.command()
def info() -> None:
    """Show version and configuration info."""
    from pathlib import Path

    click.echo(f"AgentAnycast SDK v{__version__}")
    click.echo(f"Python: {sys.version}")

    default_home = Path.home() / ".agentanycast"
    click.echo(f"Default home: {default_home}")
    click.echo(f"  Key exists: {(default_home / 'key').exists()}")
    click.echo(f"  Socket exists: {(default_home / 'daemon.sock').exists()}")


def main() -> None:
    """CLI main entry point."""
    cli()


if __name__ == "__main__":
    main()
