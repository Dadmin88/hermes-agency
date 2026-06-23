"""Tests for SDK daemon gRPC client transport warnings."""

from __future__ import annotations

import logging

import pytest

from agentanycast import _grpc_client as grpc_client_module
from agentanycast._grpc_client import GrpcClient


@pytest.mark.asyncio
async def test_tcp_daemon_address_warns_that_channel_is_insecure(monkeypatch, caplog):
    created_targets: list[str] = []

    class FakeChannel:
        async def close(self):
            pass

    class FakeStub:
        def __init__(self, channel):
            self.channel = channel

        async def GetNodeInfo(self, request, timeout=None):  # noqa: N802
            return object()

    def fake_insecure_channel(target):
        created_targets.append(target)
        return FakeChannel()

    monkeypatch.setattr(
        grpc_client_module.grpc.aio,
        "insecure_channel",
        fake_insecure_channel,
    )
    monkeypatch.setattr(
        grpc_client_module.node_service_pb2_grpc,
        "NodeServiceStub",
        FakeStub,
    )

    client = GrpcClient("tcp://127.0.0.1:50051")
    with caplog.at_level(logging.WARNING):
        await client.connect()

    assert created_targets == ["127.0.0.1:50051"]
    assert "unencrypted daemon gRPC connection" in caplog.text
