#!/usr/bin/env python3
"""
Hermes Agency Pool CLI
hermes agency pool <command>
"""

from __future__ import annotations

import os
import sys

import click
import httpx

try:
    from manager import PoolManager
except ImportError:  # package-relative fallback
    from .manager import PoolManager

pm = PoolManager()
BASE = f"http://{os.environ.get('HERMES_POOL_BIND', '127.0.0.1')}:{pm.config['pool']['port']}"
DEFAULT_TIMEOUT = float(os.environ.get("HERMES_POOL_HTTP_TIMEOUT", "10"))


def _headers() -> dict[str, str]:
    token = str(os.environ.get("HERMES_POOL_TOKEN") or "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, path: str) -> dict:
    url = f"{BASE}{path}"
    try:
        response = httpx.request(
            method,
            url,
            headers=_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        click.echo({"error": f"pool request failed: {type(exc).__name__}: {exc}"}, err=True)
        sys.exit(1)
    if response.status_code == 401:
        click.echo({"error": "unauthorized — set HERMES_POOL_TOKEN if required"}, err=True)
        sys.exit(1)
    try:
        payload = response.json()
    except ValueError:
        payload = {"status_code": response.status_code, "text": response.text}
    if response.status_code >= 400:
        click.echo(payload, err=True)
        sys.exit(1)
    return payload


@click.group()
def pool():
    """Hermes Agency Pool Manager"""
    pass


@pool.command()
def status():
    """Show pool status"""
    click.echo(_request("GET", "/pool/status"))


@pool.command(name="list")
def list_agents():
    """List all agents"""
    click.echo(_request("GET", "/pool/agents"))


@pool.command()
@click.argument("agent")
def wake(agent):
    """Wake an agent"""
    click.echo(_request("POST", f"/pool/agents/{agent}/wake"))


@pool.command()
@click.argument("agent")
def sleep(agent):
    """Sleep an agent"""
    click.echo(_request("POST", f"/pool/agents/{agent}/sleep"))


@pool.command()
@click.argument("skill")
def find(skill):
    """Find agents by skill"""
    agents = pm.registry.get("agents", [])
    matches = [a for a in agents if skill.lower() in [s.lower() for s in a.get("skills", [])]]
    click.echo({"matches": matches})


if __name__ == "__main__":
    pool()
