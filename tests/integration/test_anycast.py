"""Anycast skill routing tests.

Tests skill-based anycast routing through the relay registry,
verifying that agents can register skills and be discovered.

Environment variables:
    RELAY_REGISTRY  — gRPC address of the relay's registry (e.g., relay:50052)
    NODE_A_GRPC     — gRPC address of node A
    NODE_B_GRPC     — gRPC address of node B
"""

from __future__ import annotations

import os

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
    node_service_pb2 as ns_pb2,
    registry_service_pb2 as reg_pb2,
)

from .conftest import unique_id, wait_for  # noqa: E402


class TestAnycastSkillRouting:
    """Test anycast routing via skill registration and discovery."""

    def test_anycast_skill_routing(self, grpc_registry, grpc_node_a, grpc_node_b) -> None:
        """Register a skill at node-b via the relay, then discover it."""
        skill_id = unique_id("anycast-skill")

        # Get node B's peer ID.
        resp_b = grpc_node_b.GetNodeInfo(ns_pb2.GetNodeInfoRequest())
        peer_id_b = resp_b.node_info.peer_id

        # Register the skill at the relay for node B.
        grpc_registry.RegisterSkills(reg_pb2.RegisterSkillsRequest(
            peer_id=peer_id_b,
            skills=[reg_pb2.SkillInfo(
                skill_id=skill_id,
                description=f"Test skill {skill_id}",
            )],
            agent_name=f"Anycast Agent ({skill_id})",
        ))

        # Discover via the registry.
        resp = grpc_registry.DiscoverBySkill(reg_pb2.DiscoverBySkillRequest(
            skill_id=skill_id,
        ))
        assert len(resp.agents) >= 1
        peer_ids = [a.peer_id for a in resp.agents]
        assert peer_id_b in peer_ids

        # Also test discovery through the node's Discover RPC.
        disc_resp = grpc_node_a.Discover(ns_pb2.DiscoverRequest(skill_id=skill_id))
        discovered_peers = [a.peer_id for a in disc_resp.agents]
        assert peer_id_b in discovered_peers

    def test_anycast_tag_filtering(self, grpc_registry) -> None:
        """Register the same skill with different tags, verify filter works."""
        skill_id = unique_id("tag-filter")

        peer_en = unique_id("12D3KooW-en")
        peer_zh = unique_id("12D3KooW-zh")
        peer_ja = unique_id("12D3KooW-ja")

        # Register three agents with same skill but different tags.
        for peer_id, lang in [(peer_en, "en"), (peer_zh, "zh"), (peer_ja, "ja")]:
            grpc_registry.RegisterSkills(reg_pb2.RegisterSkillsRequest(
                peer_id=peer_id,
                skills=[reg_pb2.SkillInfo(
                    skill_id=skill_id,
                    tags={"lang": lang},
                )],
                agent_name=f"Agent-{lang}",
            ))

        # Filter by lang=zh.
        resp = grpc_registry.DiscoverBySkill(reg_pb2.DiscoverBySkillRequest(
            skill_id=skill_id,
            tags={"lang": "zh"},
        ))
        peer_ids = [a.peer_id for a in resp.agents]
        assert peer_zh in peer_ids
        assert peer_en not in peer_ids
        assert peer_ja not in peer_ids
