"""Relay API endpoint tests.

Tests the REST API exposed by the relay for agent discovery and stats.

Environment variables:
    RELAY_API      — API base URL (e.g., http://relay:8081)
    RELAY_REGISTRY — gRPC address of relay (used to register test agents)
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

grpc = pytest.importorskip("grpc")

from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    registry_service_pb2 as reg_pb2,
)

from .conftest import RELAY_API, unique_id  # noqa: E402


class TestRelayAPI:
    """Test the relay's REST API endpoints."""

    def test_list_agents(self, grpc_registry) -> None:
        """Register agents, then GET /api/v1/agents should list them."""
        agent_name = unique_id("api-agent")
        peer_id = unique_id("12D3KooW-api")
        skill_id = unique_id("api-skill")

        grpc_registry.RegisterSkills(reg_pb2.RegisterSkillsRequest(
            peer_id=peer_id,
            skills=[reg_pb2.SkillInfo(skill_id=skill_id, description="API test")],
            agent_name=agent_name,
        ))

        resp = httpx.get(f"{RELAY_API}/api/v1/agents", timeout=10)
        assert resp.status_code == 200

        data = resp.json()
        # Response should be a list or have an "agents" key.
        agents = data if isinstance(data, list) else data.get("agents", [])
        assert len(agents) >= 1

    def test_filter_by_skill(self, grpc_registry) -> None:
        """GET /api/v1/agents?skill=X should return only matching agents."""
        skill_id = unique_id("filter-skill")
        peer_match = unique_id("12D3KooW-match")
        peer_other = unique_id("12D3KooW-other")

        grpc_registry.RegisterSkills(reg_pb2.RegisterSkillsRequest(
            peer_id=peer_match,
            skills=[reg_pb2.SkillInfo(skill_id=skill_id)],
            agent_name="Match Agent",
        ))
        grpc_registry.RegisterSkills(reg_pb2.RegisterSkillsRequest(
            peer_id=peer_other,
            skills=[reg_pb2.SkillInfo(skill_id=unique_id("other-skill"))],
            agent_name="Other Agent",
        ))

        resp = httpx.get(
            f"{RELAY_API}/api/v1/agents",
            params={"skill": skill_id},
            timeout=10,
        )
        assert resp.status_code == 200

        data = resp.json()
        agents = data if isinstance(data, list) else data.get("agents", [])
        peer_ids = [a.get("peer_id", a.get("peerId", "")) for a in agents]
        assert peer_match in peer_ids
        assert peer_other not in peer_ids

    def test_stats_endpoint(self) -> None:
        """GET /api/v1/stats should return a JSON structure with stats."""
        resp = httpx.get(f"{RELAY_API}/api/v1/stats", timeout=10)
        assert resp.status_code == 200

        data = resp.json()
        # Should have some stats fields.
        assert isinstance(data, dict)
        assert len(data) > 0
