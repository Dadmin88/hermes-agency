"""Relay health and metrics endpoint tests.

Tests the health and Prometheus metrics endpoints exposed by the relay.

Environment variables:
    RELAY_HEALTH  — Health endpoint URL (e.g., http://relay:9090)
    RELAY_REGISTRY — gRPC address of relay (used to skip if not in Docker)
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RELAY_REGISTRY"),
        reason="RELAY_REGISTRY not set (not running in Docker Compose)",
    ),
]

from .conftest import RELAY_HEALTH  # noqa: E402


class TestRelayHealth:
    """Test relay health and metrics endpoints."""

    def test_relay_health_endpoint(self) -> None:
        """GET /health returns JSON with status, peer_id, and uptime."""
        resp = httpx.get(f"{RELAY_HEALTH}/health", timeout=10)
        assert resp.status_code == 200

        data = resp.json()
        assert data.get("status") == "healthy"
        assert "peer_id" in data
        assert "uptime" in data or "uptime_seconds" in data

    def test_relay_metrics_endpoint(self) -> None:
        """GET /metrics returns Prometheus-format text."""
        resp = httpx.get(f"{RELAY_HEALTH}/metrics", timeout=10)
        assert resp.status_code == 200
        # Prometheus metrics are plain text with # HELP and # TYPE lines.
        content_type = resp.headers.get("content-type", "")
        assert "text" in content_type or "openmetrics" in content_type
        assert "# HELP" in resp.text or "# TYPE" in resp.text

    def test_relay_health_has_registry_stats(self) -> None:
        """Health JSON should include registry statistics."""
        resp = httpx.get(f"{RELAY_HEALTH}/health", timeout=10)
        assert resp.status_code == 200

        data = resp.json()
        # The health response should contain some form of registry info.
        # It might be under "registry", "skills", "agents", or similar.
        has_registry = any(
            key in data
            for key in ("registry", "skills", "agents", "registered_agents", "registry_stats")
        )
        assert has_registry, f"Health response missing registry stats. Keys: {list(data.keys())}"
