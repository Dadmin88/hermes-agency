"""NATS transport tests.

Tests that a node configured with NATS as its transport layer
can respond to gRPC requests.

Requires the docker-compose.nats.yml overlay.

Environment variables:
    NODE_C_GRPC  — gRPC address of node-c (NATS transport)
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.nats_transport,
    pytest.mark.skipif(
        not os.environ.get("NODE_C_GRPC"),
        reason="NODE_C_GRPC not set (NATS overlay not active)",
    ),
]

grpc = pytest.importorskip("grpc")

from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    node_service_pb2 as ns_pb2,
)


class TestNATSTransport:
    """Test NATS-based node connectivity."""

    def test_nats_node_responds(self, grpc_node_c) -> None:
        """Node-c (NATS transport) should respond to GetNodeInfo."""
        resp = grpc_node_c.GetNodeInfo(ns_pb2.GetNodeInfoRequest())
        info = resp.node_info
        assert info.peer_id, "Node C should return a peer ID"
        assert info.peer_id.startswith("12D3KooW")
