"""HTTP bridge endpoint tests.

Tests the A2A HTTP bridge running on node-a, verifying that the
well-known agent card endpoint and the A2A inbound endpoint work.

Environment variables:
    NODE_A_BRIDGE  — HTTP base URL for node-a's bridge (e.g., http://node-a:8080)
    NODE_A_GRPC    — gRPC address of node A
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("NODE_A_GRPC"),
        reason="NODE_A_GRPC not set (not running in Docker Compose)",
    ),
]

grpc = pytest.importorskip("grpc")

from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    agent_card_pb2 as card_pb2,
)
from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    node_service_pb2 as ns_pb2,
)

from .conftest import NODE_A_BRIDGE, unique_id  # noqa: E402


class TestBridgeEndpoints:
    """Test HTTP bridge endpoints on node-a."""

    def test_bridge_card_endpoint(self, grpc_node_a) -> None:
        """GET /.well-known/agent.json returns a valid AgentCard JSON."""
        # First set a card on node-a so the endpoint has something to return.
        card_name = unique_id("bridge-agent")
        grpc_node_a.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(
                    name=card_name,
                    skills=[card_pb2.Skill(id="bridge-test", description="Bridge test skill")],
                ),
            )
        )

        resp = httpx.get(f"{NODE_A_BRIDGE}/.well-known/agent.json", timeout=10)
        assert resp.status_code == 200

        data = resp.json()
        assert "name" in data
        assert "skills" in data

    def test_bridge_inbound_endpoint(self, grpc_node_a) -> None:
        """POST /a2a endpoint should accept requests (or return a structured error)."""
        # Ensure there's a card set.
        grpc_node_a.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(
                    name=unique_id("bridge-inbound"),
                    skills=[card_pb2.Skill(id="inbound-test", description="Inbound test")],
                ),
            )
        )

        # Send a minimal A2A JSON-RPC request.
        payload = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": unique_id("req"),
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "hello via bridge"}],
                },
            },
        }

        resp = httpx.post(
            f"{NODE_A_BRIDGE}/a2a",
            json=payload,
            timeout=10,
        )
        # The endpoint should respond (200 or 4xx with JSON body).
        # We don't require 200 since there may be no handler attached,
        # but it should not be a connection error or 5xx.
        assert resp.status_code < 500, f"Bridge returned {resp.status_code}: {resp.text}"
