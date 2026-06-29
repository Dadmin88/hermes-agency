"""Tests for MCP HTTP bridge security defaults.

Validates that:
- HTTP transport is blocked by default without --allow-http-bridge.
- HTTP server binds to localhost (127.0.0.1) by default.
- Explicit allow_http_bridge permits HTTP transport.
"""

from __future__ import annotations

import unittest.mock as mock

import pytest

import agentanycast.mcp_server as mcp_server


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
    """HTTP transport must be rejected unless --allow-http-bridge is set."""

    def test_http_transport_blocked_without_flag(self):
        """run_server(transport='http') raises SystemExit when allow_http_bridge is False."""
        mcp_server.configure()
        with pytest.raises(SystemExit, match="--allow-http-bridge"):
            mcp_server.run_server(transport="http", port=8080)

    def test_http_transport_allowed_with_flag(self):
        """run_server(transport='http') does not raise when allow_http_bridge is True."""
        mcp_server.configure(allow_http_bridge=True)
        with mock.patch.object(mcp_server.mcp, "run") as mock_run:
            mcp_server.run_server(transport="http", port=9090)
            mock_run.assert_called_once_with(transport="http")


class TestHTTPBindLocalhost:
    """HTTP server must default to 127.0.0.1 (not 0.0.0.0)."""

    def test_default_host_is_localhost(self):
        """When host is not overridden, mcp.settings.host is set to 127.0.0.1."""
        mcp_server.configure(allow_http_bridge=True)
        with mock.patch.object(mcp_server.mcp, "run"):
            mcp_server.run_server(transport="http", port=8080, host="127.0.0.1")
        assert mcp_server.mcp.settings.host == "127.0.0.1"
        assert mcp_server.mcp.settings.port == 8080

    def test_custom_host_applied(self):
        """An explicit host override is forwarded to mcp.settings."""
        mcp_server.configure(allow_http_bridge=True)
        with mock.patch.object(mcp_server.mcp, "run"):
            mcp_server.run_server(transport="http", port=9999, host="192.168.1.100")
        assert mcp_server.mcp.settings.host == "192.168.1.100"
        assert mcp_server.mcp.settings.port == 9999


class TestStdioTransportUnaffected:
    """stdio transport must still work without --allow-http-bridge."""

    def test_stdio_works_without_flag(self):
        """stdio mode should not require allow_http_bridge."""
        mcp_server.configure()
        with mock.patch.object(mcp_server.mcp, "run") as mock_run:
            mcp_server.run_server(transport="stdio")
            mock_run.assert_called_once_with(transport="stdio")
