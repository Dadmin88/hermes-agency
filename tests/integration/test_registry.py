"""Integration tests for skill registry via real relay process.

These tests verify that the registry gRPC service works end-to-end
when accessed through the relay binary.

Run:
    pytest tests/integration/ -m integration -v
"""

from __future__ import annotations

import pytest

grpc = pytest.importorskip("grpc")

from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    registry_service_pb2 as reg_pb2,
)
from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    registry_service_pb2_grpc as reg_grpc,
)


@pytest.mark.integration
class TestRegistryIntegration:
    """Integration tests for the Skill Registry gRPC service."""

    @pytest.fixture(autouse=True)
    def _setup(self, relay_process: dict[str, str]) -> None:
        self.channel = grpc.insecure_channel(relay_process["registry_addr"])
        self.client = reg_grpc.RegistryServiceStub(self.channel)

    def test_register_and_discover(self) -> None:
        """Register skills and discover them."""
        self.client.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id="12D3KooWTestA",
                skills=[reg_pb2.SkillInfo(skill_id="echo", description="Echo back")],
                agent_name="Echo Agent",
                agent_description="A test echo agent",
            )
        )

        resp = self.client.DiscoverBySkill(
            reg_pb2.DiscoverBySkillRequest(
                skill_id="echo",
            )
        )
        assert len(resp.agents) == 1
        assert resp.agents[0].peer_id == "12D3KooWTestA"
        assert resp.agents[0].agent_name == "Echo Agent"

    def test_discover_nonexistent_skill(self) -> None:
        """Discover should return empty for unknown skills."""
        resp = self.client.DiscoverBySkill(
            reg_pb2.DiscoverBySkillRequest(
                skill_id="nonexistent-skill-xyz",
            )
        )
        assert len(resp.agents) == 0

    def test_tag_filtering(self) -> None:
        """Register with tags and filter by tag."""
        self.client.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id="12D3KooWTagEN",
                skills=[
                    reg_pb2.SkillInfo(
                        skill_id="translate-tag-test",
                        tags={"lang": "en"},
                    )
                ],
                agent_name="EN Agent",
            )
        )
        self.client.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id="12D3KooWTagZH",
                skills=[
                    reg_pb2.SkillInfo(
                        skill_id="translate-tag-test",
                        tags={"lang": "zh"},
                    )
                ],
                agent_name="ZH Agent",
            )
        )

        # Filter by lang=zh.
        resp = self.client.DiscoverBySkill(
            reg_pb2.DiscoverBySkillRequest(
                skill_id="translate-tag-test",
                tags={"lang": "zh"},
            )
        )
        assert len(resp.agents) == 1
        assert resp.agents[0].peer_id == "12D3KooWTagZH"

    def test_heartbeat(self) -> None:
        """Heartbeat should renew a registration."""
        self.client.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id="12D3KooWHB",
                skills=[reg_pb2.SkillInfo(skill_id="hb-test")],
                agent_name="HB Agent",
            )
        )

        resp = self.client.Heartbeat(
            reg_pb2.HeartbeatRequest(
                peer_id="12D3KooWHB",
            )
        )
        assert resp.expires_at is not None

    def test_unregister_skills(self) -> None:
        """Unregister specific skills from a peer."""
        self.client.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id="12D3KooWUnreg",
                skills=[
                    reg_pb2.SkillInfo(skill_id="unreg-a"),
                    reg_pb2.SkillInfo(skill_id="unreg-b"),
                ],
                agent_name="Unreg Agent",
            )
        )

        self.client.UnregisterSkills(
            reg_pb2.UnregisterSkillsRequest(
                peer_id="12D3KooWUnreg",
                skill_ids=["unreg-a"],
            )
        )

        # unreg-a should be gone.
        resp = self.client.DiscoverBySkill(
            reg_pb2.DiscoverBySkillRequest(
                skill_id="unreg-a",
            )
        )
        assert len(resp.agents) == 0

        # unreg-b should still exist.
        resp = self.client.DiscoverBySkill(
            reg_pb2.DiscoverBySkillRequest(
                skill_id="unreg-b",
            )
        )
        assert len(resp.agents) == 1
