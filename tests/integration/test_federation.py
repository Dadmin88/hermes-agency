"""Federation tests across multiple relays.

Tests cross-relay skill discovery when two relays are federated.
Requires the docker-compose.federation.yml overlay.

Environment variables:
    RELAY_REGISTRY    — gRPC address of relay-a's registry
    RELAY_B_REGISTRY  — gRPC address of relay-b's registry
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.federation,
    pytest.mark.skipif(
        not os.environ.get("RELAY_B_REGISTRY"),
        reason="RELAY_B_REGISTRY not set (federation overlay not active)",
    ),
]

grpc = pytest.importorskip("grpc")

from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    registry_service_pb2 as reg_pb2,
)

from .conftest import unique_id, wait_for  # noqa: E402


class TestFederation:
    """Test cross-relay federation."""

    def test_cross_relay_discovery(self, grpc_registry, grpc_registry_b) -> None:
        """Register a skill at relay-a, discover it via relay-b."""
        skill_id = unique_id("fed-skill")
        peer_id = unique_id("12D3KooW-fed")

        # Register at relay-a (the primary relay).
        grpc_registry.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id=peer_id,
                skills=[
                    reg_pb2.SkillInfo(
                        skill_id=skill_id,
                        description="Federation test skill",
                    )
                ],
                agent_name=f"Fed Agent ({skill_id})",
            )
        )

        # Discover via relay-b (the federated relay).
        # May need a short delay for federation sync.
        def _discover():
            resp = grpc_registry_b.DiscoverBySkill(
                reg_pb2.DiscoverBySkillRequest(
                    skill_id=skill_id,
                )
            )
            peer_ids = [a.peer_id for a in resp.agents]
            return peer_id in peer_ids

        wait_for(
            _discover,
            timeout=15,
            interval=1.0,
            msg=f"Skill {skill_id} not discovered via relay-b after federation sync",
        )

    def test_cross_relay_bidirectional(self, grpc_registry, grpc_registry_b) -> None:
        """Register skills at both relays, discover each from the other."""
        skill_a = unique_id("fed-bidi-a")
        skill_b = unique_id("fed-bidi-b")
        peer_a = unique_id("12D3KooW-fed-a")
        peer_b = unique_id("12D3KooW-fed-b")

        # Register at relay-a.
        grpc_registry.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id=peer_a,
                skills=[reg_pb2.SkillInfo(skill_id=skill_a)],
                agent_name="Fed-A",
            )
        )

        # Register at relay-b.
        grpc_registry_b.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id=peer_b,
                skills=[reg_pb2.SkillInfo(skill_id=skill_b)],
                agent_name="Fed-B",
            )
        )

        # Discover skill_a via relay-b.
        def _discover_a():
            resp = grpc_registry_b.DiscoverBySkill(
                reg_pb2.DiscoverBySkillRequest(
                    skill_id=skill_a,
                )
            )
            return peer_a in [a.peer_id for a in resp.agents]

        wait_for(_discover_a, timeout=15, interval=1.0, msg="skill_a not visible on relay-b")

        # Discover skill_b via relay-a.
        def _discover_b():
            resp = grpc_registry.DiscoverBySkill(
                reg_pb2.DiscoverBySkillRequest(
                    skill_id=skill_b,
                )
            )
            return peer_b in [a.peer_id for a in resp.agents]

        wait_for(_discover_b, timeout=15, interval=1.0, msg="skill_b not visible on relay-a")
