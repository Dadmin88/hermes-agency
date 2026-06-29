"""Tests for MCP HTTP bridge security defaults.

Validates that:
- HTTP transport is blocked by default without --allow-http-bridge.
- HTTP server binds to localhost (127.0.0.1) by default.
- Explicit allow_http_bridge permits HTTP transport.
"""

from __future__ import annotations

import sys
import types

import pytest

# Stub the optional `mcp` dependency before importing the server module.
_mcp_stub = types.ModuleType("mcp")
_mcp_server = types.ModuleType("mcp.server")
_mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")


class _FakeSettings:
    host: str | None = None
    port: int | None = None


class _FakeFastMCP:
    def __init__(self, *a, **kw):
        self.settings = _FakeSettings()

    def tool(self):
        def decorator(fn):
            return fn

        return decorator

    def run(self, **kw):
        pass


_mcp_fastmcp.FastMCP = _FakeFastMCP  # type: ignore[attr-defined]
sys.modules.setdefault("mcp", _mcp_stub)
sys.modules.setdefault("mcp.server", _mcp_server)
sys.modules.setdefault("mcp.server.fastmcp", _mcp_fastmcp)

import agentanycast.mcp_server as mcp_server  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset module-level configuration between tests."""
    mcp_server._allow_http_bridge = False
    mcp_server._relay = None
    mcp_server._home = None
    mcp_server._node = None
    yield
    mcp_server._allow_http_bridge = False
    mcp_server._node = None


class TestHTTPBridgeDisabledByDefault:
    def test_send_task_rejects_http_url_by_default(self):
        """HTTP bridge targets must be rejected unless explicitly allowed."""
        mcp_server._allow_http_bridge = False

        import asyncio

        result = asyncio.run(mcp_server.send_task("http://example.com/a2a", "hello"))
        assert "disabled" in result.lower() or "error" in result.lower()

    def test_send_task_rejects_https_url_by_default(self):
        """HTTPS bridge targets must also be rejected by default."""
        mcp_server._allow_http_bridge = False

        import asyncio

        result = asyncio.run(mcp_server.send_task("https://example.com/a2a", "hello"))
        assert "disabled" in result.lower() or "error" in result.lower()

    def test_run_server_http_raises_when_bridge_disabled(self):
        """run_server with transport=http must raise SystemExit when bridge is disabled."""
        mcp_server._allow_http_bridge = False
        with pytest.raises(SystemExit, match="disabled"):
            mcp_server.run_server(transport="http", port=9999)


class TestHTTPLocalhostBinding:
    def test_http_transport_binds_localhost_by_default(self):
        """HTTP transport must bind to 127.0.0.1, not 0.0.0.0."""
        mcp_server._allow_http_bridge = True
        mcp_server.run_server(transport="http", port=9999)
        assert mcp_server.mcp.settings.host == "127.0.0.1"

    def test_stdio_transport_does_not_set_host(self):
        """stdio transport should not touch host/port settings."""
        settings_before = (mcp_server.mcp.settings.host, mcp_server.mcp.settings.port)
        mcp_server.run_server(transport="stdio")
        # settings should remain unchanged for stdio
        assert mcp_server.mcp.settings.host == settings_before[0]


class TestHTTPBridgeExplicitAllow:
    def test_send_task_allows_http_when_explicitly_enabled(self):
        """When allow_http_bridge is True, HTTP targets should be accepted."""
        mcp_server._allow_http_bridge = True
        # We can't fully test send_task without a running node, but we can
        # verify the guard passes by checking it doesn't return an error string
        # immediately. The actual send will fail (no node), but not due to the
        # bridge check.
        import asyncio

        result = asyncio.run(mcp_server.send_task("http://example.com/a2a", "hello"))
        # Should NOT contain the "disabled" error
        assert "HTTP bridge targets are disabled" not in result
