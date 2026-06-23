#!/usr/bin/env python3
"""
Hermes Agency Pool CLI
hermes agency pool <command>
"""

import click
import requests
from manager import PoolManager

pm = PoolManager()
BASE = f"http://localhost:{pm.config['pool']['port']}"


@click.group()
def pool():
    """Hermes Agency Pool Manager"""
    pass


@pool.command()
def status():
    """Show pool status"""
    r = requests.get(f"{BASE}/pool/status")
    click.echo(r.json())


@pool.command()
def list():
    """List all agents"""
    r = requests.get(f"{BASE}/pool/agents")
    click.echo(r.json())


@pool.command()
@click.argument("agent")
def wake(agent):
    """Wake an agent"""
    r = requests.post(f"{BASE}/pool/agents/{agent}/wake")
    click.echo(r.json())


@pool.command()
@click.argument("agent")
def sleep(agent):
    """Sleep an agent"""
    r = requests.post(f"{BASE}/pool/agents/{agent}/sleep")
    click.echo(r.json())


@pool.command()
@click.argument("skill")
def find(skill):
    """Find agents by skill"""
    agents = pm.registry.get("agents", [])
    matches = [a for a in agents if skill.lower() in [s.lower() for s in a.get("skills", [])]]
    click.echo({"matches": matches})


if __name__ == "__main__":
    pool()
