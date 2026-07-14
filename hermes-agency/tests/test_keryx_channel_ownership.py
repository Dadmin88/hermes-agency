"""Keryx DaemonClient must not close caller-owned gRPC channels."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from keryx.client import DaemonClient  # noqa: E402


class _FakeChannel:
    def __init__(self) -> None:
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_close_does_not_close_injected_channels():
    daemon_ch = _FakeChannel()
    registry_ch = _FakeChannel()
    client = DaemonClient(
        daemon_endpoint="127.0.0.1:50051",
        channel=daemon_ch,
        registry_channel=registry_ch,
    )
    await client.close()
    await client.close()  # idempotent
    assert daemon_ch.closed == 0
    assert registry_ch.closed == 0


@pytest.mark.asyncio
async def test_close_closes_owned_channel_once():
    client = DaemonClient(daemon_endpoint="127.0.0.1:50051")
    owned = _FakeChannel()
    client._channel = owned
    client._owns_channel = True
    await client.close()
    await client.close()
    assert owned.closed == 1


@pytest.mark.asyncio
async def test_node_close_skips_caller_owned_channel():
    from keryx.card import AgentCard
    from keryx.node import KeryxNode

    channel = _FakeChannel()
    node = KeryxNode(
        card=AgentCard(name="t", description="t", skills=[]),
        channel=channel,
        daemon_endpoint="127.0.0.1:50051",
    )
    assert node._owns_channel is False
    await node.close()
    await node.close()
    assert channel.closed == 0
