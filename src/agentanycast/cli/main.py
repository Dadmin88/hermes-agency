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

import click

from agentanycast import __version__


@click.group()
@click.version_option(version=__version__, prog_name="agentanycast")
def cli() -> None:
    """AgentAnycast — P2P runtime for the A2A protocol."""


# Register sub-commands from separate modules.
from agentanycast.cli.mcp import mcp_cmd  # noqa: E402

cli.add_command(mcp_cmd)


@cli.command()
@click.option("--relay", default=None, help="Relay server multiaddr.")
@click.option("--home", default=None, help="Data directory.")
def demo(relay: str | None, home: str | None) -> None:
    """Start a demo echo agent that responds to any incoming task."""
    asyncio.run(_demo(relay, home))


async def _demo(relay: str | None, home: str | None) -> None:
    from agentanycast import AgentCard, IncomingTask, Node, Part, Skill
    from agentanycast.task import Artifact

    card = AgentCard(
        name="Echo Agent",
        description="A demo agent that echoes back any message it receives.",
        skills=[Skill(id="echo", description="Echo back the input message.")],
    )

    async with Node(card=card, relay=relay, home=home) as node:
        click.echo(f"Echo agent started. PeerID: {node.peer_id}")
        click.echo("Waiting for incoming tasks... (Ctrl+C to stop)")

        @node.on_task
        async def handle(task: IncomingTask) -> None:
            input_text = ""
            for msg in task.messages:
                for part in msg.parts:
                    if part.text:
                        input_text += part.text

            click.echo(f"Received task {task.task_id}: {input_text!r}")
            await task.complete(
                artifacts=[Artifact(name="echo", parts=[Part(text=f"Echo: {input_text}")])]
            )

        try:
            await node.serve_forever()
        except KeyboardInterrupt:
            pass


@cli.command()
@click.argument("skill")
@click.option("--tag", "-t", multiple=True, help="Filter by tag (key=value). Can be repeated.")
@click.option("--relay", default=None, help="Relay server multiaddr.")
@click.option("--home", default=None, help="Data directory.")
def discover(skill: str, tag: tuple[str, ...], relay: str | None, home: str | None) -> None:
    """Discover agents offering a specific skill."""
    tags: dict[str, str] | None = None
    if tag:
        tags = {}
        for t in tag:
            if "=" not in t:
                click.echo(f"Invalid tag format: {t!r} (expected key=value)", err=True)
                raise SystemExit(1)
            k, v = t.split("=", 1)
            tags[k] = v
    asyncio.run(_discover(skill, tags, relay, home))


async def _discover(
    skill: str,
    tags: dict[str, str] | None,
    relay: str | None,
    home: str | None,
) -> None:
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
def send(
    target: str,
    message: str,
    skill: bool,
    url: bool,
    relay: str | None,
    home: str | None,
    timeout: int,
) -> None:
    """Send a task to a remote agent and print the response."""
    asyncio.run(_send(target, message, skill, url, relay, home, timeout))


async def _send(
    target: str,
    message: str,
    is_skill: bool,
    is_url: bool,
    relay: str | None,
    home: str | None,
    timeout: int,
) -> None:
    from agentanycast import AgentCard, Message, Node, Part

    card = AgentCard(name="CLI Client")
    async with Node(card=card, relay=relay, home=home) as node:
        msg = Message(role="user", parts=[Part(text=message)])

        peer_id_val: str | None = None
        skill_val: str | None = None
        url_val: str | None = None

        if is_skill:
            skill_val = target
            click.echo(f"Sending task via anycast (skill={target})...")
        elif is_url:
            url_val = target
            click.echo(f"Sending task via HTTP bridge ({target})...")
        else:
            peer_id_val = target
            click.echo(f"Sending task to {target}...")

        handle = await node.send_task(msg, peer_id=peer_id_val, skill=skill_val, url=url_val)
        result = await handle.wait(timeout=timeout)

        click.echo(f"Task {result.task_id} completed (status: {result.status.value})")
        for artifact in result.artifacts:
            click.echo(f"  Artifact: {artifact.name}")
            for part in artifact.parts:
                if part.text:
                    click.echo(f"    {part.text}")


@cli.command()
@click.option("--relay", default=None, help="Relay server multiaddr.")
@click.option("--home", default=None, help="Data directory.")
def status(relay: str | None, home: str | None) -> None:
    """Show local node status."""
    asyncio.run(_status(relay, home))


async def _status(relay: str | None, home: str | None) -> None:
    from agentanycast import AgentCard, Node

    card = AgentCard(name="CLI Status")
    async with Node(card=card, relay=relay, home=home) as node:
        click.echo(f"PeerID: {node.peer_id}")
        peers = await node.list_peers()
        click.echo(f"Connected peers: {len(peers)}")
        for p in peers:
            click.echo(f"  {p['peer_id']}")


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
