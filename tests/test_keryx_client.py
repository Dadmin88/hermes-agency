from __future__ import annotations

from typing import Any

import pytest

from keryx.client import DaemonClient


class _RecordingChannel:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1

    def unary_unary(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_daemon_client_does_not_close_injected_channels() -> None:
    daemon = _RecordingChannel()
    registry = _RecordingChannel()
    client = DaemonClient(
        daemon_endpoint="127.0.0.1:50051",
        registry_endpoint="127.0.0.1:51053",
        channel=daemon,  # type: ignore[arg-type]
        registry_channel=registry,  # type: ignore[arg-type]
    )

    await client.connect()
    await client.close()

    assert daemon.close_calls == 0
    assert registry.close_calls == 0


@pytest.mark.asyncio
async def test_daemon_client_closes_channels_it_creates(monkeypatch: pytest.MonkeyPatch) -> None:
    channels: list[_RecordingChannel] = []

    def create_channel(_target: str) -> _RecordingChannel:
        channel = _RecordingChannel()
        channels.append(channel)
        return channel

    monkeypatch.setattr("keryx.client.grpc.aio.insecure_channel", create_channel)
    client = DaemonClient(
        daemon_endpoint="127.0.0.1:50051",
        registry_endpoint="127.0.0.1:51053",
    )

    await client.connect()
    await client.close()

    assert len(channels) == 2
    assert [channel.close_calls for channel in channels] == [1, 1]


@pytest.mark.asyncio
async def test_daemon_client_owns_replacement_channels_after_injected_channels_are_detached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    injected_daemon = _RecordingChannel()
    injected_registry = _RecordingChannel()
    replacements: list[_RecordingChannel] = []

    def create_channel(_target: str) -> _RecordingChannel:
        channel = _RecordingChannel()
        replacements.append(channel)
        return channel

    monkeypatch.setattr("keryx.client.grpc.aio.insecure_channel", create_channel)
    client = DaemonClient(
        daemon_endpoint="127.0.0.1:50051",
        registry_endpoint="127.0.0.1:51053",
        channel=injected_daemon,  # type: ignore[arg-type]
        registry_channel=injected_registry,  # type: ignore[arg-type]
    )

    await client.connect()
    await client.close()
    await client.connect()
    await client.close()

    assert injected_daemon.close_calls == 0
    assert injected_registry.close_calls == 0
    assert len(replacements) == 2
    assert [channel.close_calls for channel in replacements] == [1, 1]
