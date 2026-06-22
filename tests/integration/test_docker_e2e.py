"""Docker Compose E2E tests.

These tests run inside the test-runner container and connect to the
relay and node services via environment variables set by docker-compose.

Environment variables:
    RELAY_REGISTRY  — gRPC address of the relay's registry (e.g., relay:50052)
    NODE_A_GRPC     — gRPC address of node A (e.g., node-a:50051)
    NODE_B_GRPC     — gRPC address of node B (e.g., node-b:50051)
"""

from __future__ import annotations

import os

import pytest

# These tests only run when the Docker env vars are set.
RELAY_REGISTRY = os.environ.get("RELAY_REGISTRY")
NODE_A_GRPC = os.environ.get("NODE_A_GRPC")
NODE_B_GRPC = os.environ.get("NODE_B_GRPC")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not RELAY_REGISTRY,
        reason="RELAY_REGISTRY not set (not running in Docker Compose)",
    ),
]

import queue  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

grpc = pytest.importorskip("grpc")

from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    a2a_models_pb2 as a2a_pb2,
)
from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    agent_card_pb2 as card_pb2,
)
from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    node_service_pb2 as ns_pb2,
)
from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    node_service_pb2_grpc as ns_grpc,
)
from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    registry_service_pb2 as reg_pb2,
)
from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    registry_service_pb2_grpc as reg_grpc,
)


class TestDockerRegistry:
    """Test the registry service running in the relay container."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        assert RELAY_REGISTRY
        self.channel = grpc.insecure_channel(RELAY_REGISTRY)
        self.client = reg_grpc.RegistryServiceStub(self.channel)

    def test_register_and_discover(self) -> None:
        """Register a skill and discover it through the relay."""
        self.client.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id="12D3KooWDockerTestA",
                skills=[
                    reg_pb2.SkillInfo(
                        skill_id="docker-echo",
                        description="Echo from Docker",
                    )
                ],
                agent_name="Docker Echo Agent",
                agent_description="A test agent in Docker",
            )
        )

        resp = self.client.DiscoverBySkill(
            reg_pb2.DiscoverBySkillRequest(
                skill_id="docker-echo",
            )
        )
        assert len(resp.agents) >= 1

        found = False
        for agent in resp.agents:
            if agent.peer_id == "12D3KooWDockerTestA":
                assert agent.agent_name == "Docker Echo Agent"
                found = True
        assert found, "registered agent not found in discovery results"

    def test_heartbeat_known_peer(self) -> None:
        """Heartbeat for a registered peer should return an expiry time."""
        self.client.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id="12D3KooWDockerHB",
                skills=[reg_pb2.SkillInfo(skill_id="docker-hb")],
                agent_name="HB Agent",
            )
        )

        resp = self.client.Heartbeat(
            reg_pb2.HeartbeatRequest(
                peer_id="12D3KooWDockerHB",
            )
        )
        assert resp.expires_at is not None

    def test_heartbeat_unknown_peer_fails(self) -> None:
        """Heartbeat for an unknown peer should return NOT_FOUND."""
        with pytest.raises(grpc.RpcError) as exc_info:
            self.client.Heartbeat(
                reg_pb2.HeartbeatRequest(
                    peer_id="12D3KooWNonExistent",
                )
            )
        assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND

    def test_unregister_skills(self) -> None:
        """Unregistering a skill should remove it from discovery."""
        self.client.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id="12D3KooWDockerUnreg",
                skills=[
                    reg_pb2.SkillInfo(skill_id="docker-unreg-a"),
                    reg_pb2.SkillInfo(skill_id="docker-unreg-b"),
                ],
                agent_name="Unreg Agent",
            )
        )

        self.client.UnregisterSkills(
            reg_pb2.UnregisterSkillsRequest(
                peer_id="12D3KooWDockerUnreg",
                skill_ids=["docker-unreg-a"],
            )
        )

        resp = self.client.DiscoverBySkill(
            reg_pb2.DiscoverBySkillRequest(
                skill_id="docker-unreg-a",
            )
        )
        for agent in resp.agents:
            assert agent.peer_id != "12D3KooWDockerUnreg"

    def test_tag_filtering(self) -> None:
        """Tag-based filtering should work in Docker."""
        self.client.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id="12D3KooWDockerTagEN",
                skills=[
                    reg_pb2.SkillInfo(
                        skill_id="docker-translate",
                        tags={"lang": "en"},
                    )
                ],
                agent_name="EN Translator",
            )
        )
        self.client.RegisterSkills(
            reg_pb2.RegisterSkillsRequest(
                peer_id="12D3KooWDockerTagZH",
                skills=[
                    reg_pb2.SkillInfo(
                        skill_id="docker-translate",
                        tags={"lang": "zh"},
                    )
                ],
                agent_name="ZH Translator",
            )
        )

        resp = self.client.DiscoverBySkill(
            reg_pb2.DiscoverBySkillRequest(
                skill_id="docker-translate",
                tags={"lang": "zh"},
            )
        )
        peer_ids = [a.peer_id for a in resp.agents]
        assert "12D3KooWDockerTagZH" in peer_ids
        assert "12D3KooWDockerTagEN" not in peer_ids


class TestDockerNodes:
    """Test the daemon nodes running in Docker containers."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        assert NODE_A_GRPC
        assert NODE_B_GRPC
        self.channel_a = grpc.insecure_channel(NODE_A_GRPC)
        self.channel_b = grpc.insecure_channel(NODE_B_GRPC)
        self.client_a = ns_grpc.NodeServiceStub(self.channel_a)
        self.client_b = ns_grpc.NodeServiceStub(self.channel_b)

    def test_node_a_responds(self) -> None:
        """Node A should respond to GetNodeInfo."""
        resp = self.client_a.GetNodeInfo(ns_pb2.GetNodeInfoRequest())
        info = resp.node_info
        assert info.peer_id, "Node A should return a peer ID"
        assert info.peer_id.startswith("12D3KooW")

    def test_node_b_responds(self) -> None:
        """Node B should respond to GetNodeInfo."""
        resp = self.client_b.GetNodeInfo(ns_pb2.GetNodeInfoRequest())
        assert resp.node_info.peer_id, "Node B should return a peer ID"

    def test_nodes_have_different_ids(self) -> None:
        """Two nodes should have unique identities."""
        resp_a = self.client_a.GetNodeInfo(ns_pb2.GetNodeInfoRequest())
        resp_b = self.client_b.GetNodeInfo(ns_pb2.GetNodeInfoRequest())
        assert resp_a.node_info.peer_id != resp_b.node_info.peer_id

    def test_p2p_task_send_and_complete(self) -> None:
        """Send a task from node A → node B over Noise-encrypted P2P.

        Verifies the full A2A task lifecycle in Docker:
        connect → set cards → send → receive → complete → verify.
        All communication is encrypted via Noise_XX.
        """
        # Step 1: Get node info (peer IDs and listen addresses).
        self.client_a.GetNodeInfo(ns_pb2.GetNodeInfoRequest())
        resp_b = self.client_b.GetNodeInfo(ns_pb2.GetNodeInfoRequest())
        peer_id_b = resp_b.node_info.peer_id
        addrs_b = list(resp_b.node_info.listen_addresses)

        # Step 2: Connect node A to node B using container-internal addresses.
        self.client_a.ConnectPeer(
            ns_pb2.ConnectPeerRequest(
                peer_id=peer_id_b,
                addresses=addrs_b,
            )
        )

        # Step 3: Set agent cards on both nodes.
        self.client_a.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(
                    name="Docker Agent A",
                    skills=[card_pb2.Skill(id="send", description="Sends tasks")],
                ),
            )
        )
        self.client_b.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(
                    name="Docker Agent B",
                    skills=[card_pb2.Skill(id="echo", description="Echoes input")],
                ),
            )
        )

        # Step 4: Subscribe to incoming tasks on node B.
        incoming: queue.Queue[ns_pb2.SubscribeIncomingTasksResponse] = queue.Queue()

        def _subscribe() -> None:
            try:
                stream = self.client_b.SubscribeIncomingTasks(
                    ns_pb2.SubscribeIncomingTasksRequest()
                )
                for resp in stream:
                    incoming.put(resp)
            except grpc.RpcError:
                pass

        sub_thread = threading.Thread(target=_subscribe, daemon=True)
        sub_thread.start()
        time.sleep(0.5)

        # Step 5: Send task from A → B.
        send_resp = self.client_a.SendTask(
            ns_pb2.SendTaskRequest(
                peer_id=peer_id_b,
                message=a2a_pb2.Message(
                    role=a2a_pb2.MESSAGE_ROLE_USER,
                    parts=[
                        a2a_pb2.Part(
                            text_part=a2a_pb2.TextPart(text="hello from docker e2e"),
                        )
                    ],
                ),
            )
        )
        task_id = send_resp.task.task_id
        assert task_id, "SendTask should return a task ID"

        # Step 6: Wait for task to arrive at node B.
        try:
            received = incoming.get(timeout=10)
        except queue.Empty:
            pytest.fail("Task did not arrive at node B within 10s")

        assert received.task.task_id, "incoming task should have a task ID"

        # Step 7: Transition to WORKING, then complete.
        self.client_b.UpdateTaskStatus(
            ns_pb2.UpdateTaskStatusRequest(
                task_id=received.task.task_id,
                status=a2a_pb2.TASK_STATUS_WORKING,
            )
        )
        self.client_b.CompleteTask(
            ns_pb2.CompleteTaskRequest(
                task_id=received.task.task_id,
                artifacts=[
                    a2a_pb2.Artifact(
                        artifact_id="docker-art-1",
                        name="docker-echo",
                        parts=[
                            a2a_pb2.Part(
                                text_part=a2a_pb2.TextPart(
                                    text="echo: hello from docker e2e",
                                ),
                            )
                        ],
                    )
                ],
            )
        )

        # Step 8: Poll GetTask on node A until completed.
        for _ in range(30):
            resp = self.client_a.GetTask(ns_pb2.GetTaskRequest(task_id=task_id))
            if resp.task.status == a2a_pb2.TASK_STATUS_COMPLETED:
                break
            time.sleep(0.5)
        else:
            pytest.fail(f"Task did not complete within 15s. Final status: {resp.task.status}")

        # Step 9: Assert completion.
        assert resp.task.status == a2a_pb2.TASK_STATUS_COMPLETED
