"""Security regression tests for the standalone MCP server."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class _Settings:
    host: str | None = None
    port: int | None = None


class _FastMCP:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.settings = _Settings()
        self.run_calls: list[dict[str, Any]] = []

    def tool(self):
        def decorator(func):
            return func

        return decorator

    def run(self, **kwargs: Any) -> None:
        self.run_calls.append(kwargs)


@pytest.fixture()
def mcp_server(monkeypatch: pytest.MonkeyPatch):
    """Import mcp_server with a local FastMCP stub for optional MCP dependency."""
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = _FastMCP
    server_module = types.ModuleType("mcp.server")
    mcp_module = types.ModuleType("mcp")
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)
    sys.modules.pop("agentanycast.mcp_server", None)
    module = importlib.import_module("agentanycast.mcp_server")
    yield module
    sys.modules.pop("agentanycast.mcp_server", None)


def test_send_task_rejects_http_bridge_targets_by_default(mcp_server, monkeypatch):
    calls: list[Any] = []

    class FakeNode:
        async def send_task(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))
            raise AssertionError("HTTP bridge target should be rejected before node.send_task")

    async def fake_get_node() -> FakeNode:
        return FakeNode()

    monkeypatch.setattr(mcp_server, "_get_node", fake_get_node)
    mcp_server.configure(allow_http_bridge=False)

    response = json.loads(
        asyncio.run(mcp_server.send_task("http://169.254.169.254/latest", "probe"))
    )

    assert "HTTP bridge targets are disabled for MCP" in response["error"]
    assert calls == []


def test_send_task_allows_http_bridge_targets_when_explicitly_enabled(mcp_server, monkeypatch):
    captured: list[dict[str, Any]] = []

    class FakeStatus:
        value = "completed"

    @dataclass
    class FakeTask:
        task_id: str = "task-1"
        status: FakeStatus = field(default_factory=FakeStatus)
        artifacts: list[Any] = field(default_factory=list)

    class FakeHandle:
        async def wait(self, timeout: float) -> FakeTask:
            return FakeTask()

    class FakeNode:
        async def send_task(self, _message: dict[str, Any], **kwargs: Any) -> FakeHandle:
            captured.append(kwargs)
            return FakeHandle()

    async def fake_get_node() -> FakeNode:
        return FakeNode()

    monkeypatch.setattr(mcp_server, "_get_node", fake_get_node)
    mcp_server.configure(allow_http_bridge=True)

    response = json.loads(asyncio.run(mcp_server.send_task("https://example.test/a2a", "hello")))

    assert response["mode"] == "http_bridge"
    assert captured == [{"url": "https://example.test/a2a"}]


def test_http_transport_binds_localhost_by_default(mcp_server):
    mcp_server.run_server(transport="http", port=9099)

    assert mcp_server.mcp.settings.host == "127.0.0.1"
    assert mcp_server.mcp.settings.port == 9099
    assert mcp_server.mcp.run_calls == [{"transport": "http"}]
