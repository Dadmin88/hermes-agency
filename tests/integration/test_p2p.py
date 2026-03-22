"""P2P communication tests.

Tests the core peer-to-peer functionality between two daemon nodes
running in Docker containers over Noise_XX encrypted connections.

Environment variables:
    NODE_A_GRPC  — gRPC address of node A (e.g., node-a:50051)
    NODE_B_GRPC  — gRPC address of node B (e.g., node-b:50061)
"""

from __future__ import annotations

import os

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
    a2a_models_pb2 as a2a_pb2,
)
from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    agent_card_pb2 as card_pb2,
)
from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    node_service_pb2 as ns_pb2,
)

from .conftest import (  # noqa: E402
    complete_task,
    connect_nodes,
    fail_task,
    send_task_to_peer,
    subscribe_and_collect,
    unique_id,
    wait_task_status,
)


class TestCardExchange:
    """Test agent card exchange between peers."""

    def test_card_exchange(self, grpc_node_a, grpc_node_b) -> None:
        """Both nodes set cards, node-a retrieves node-b's card via GetPeerCard."""
        card_id_a = unique_id("card-a")
        card_id_b = unique_id("card-b")

        # Set cards on both nodes.
        grpc_node_a.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(
                    name=f"Agent A ({card_id_a})",
                    skills=[card_pb2.Skill(id="send", description="Sends tasks")],
                ),
            )
        )
        grpc_node_b.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(
                    name=f"Agent B ({card_id_b})",
                    skills=[card_pb2.Skill(id="echo", description="Echoes input")],
                ),
            )
        )

        # Connect the nodes.
        _peer_id_a, peer_id_b = connect_nodes(grpc_node_a, grpc_node_b)

        # Retrieve node-b's card from node-a.
        resp = grpc_node_a.GetPeerCard(ns_pb2.GetPeerCardRequest(peer_id=peer_id_b))
        assert resp.card is not None
        assert card_id_b in resp.card.name
        assert len(resp.card.skills) >= 1


class TestTaskFailureFlow:
    """Test the task failure lifecycle."""

    def test_task_failure_flow(self, grpc_node_a, grpc_node_b) -> None:
        """Send task from A -> B, B fails it, A sees FAILED status."""
        _peer_id_a, peer_id_b = connect_nodes(grpc_node_a, grpc_node_b)

        # Set cards.
        grpc_node_a.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(name=unique_id("fail-sender")),
            )
        )
        grpc_node_b.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(name=unique_id("fail-handler")),
            )
        )

        # Subscribe on node B.
        incoming = subscribe_and_collect(grpc_node_b)

        # Send task.
        task_text = unique_id("fail-task")
        task_id = send_task_to_peer(grpc_node_a, peer_id_b, text=task_text)

        # Wait for arrival at B.
        received = incoming.get(timeout=10)
        assert received.task.task_id

        # Fail the task on B.
        error_msg = unique_id("error")
        fail_task(grpc_node_b, received.task.task_id, error_message=error_msg)

        # Poll on A until FAILED.
        wait_task_status(grpc_node_a, task_id, a2a_pb2.TASK_STATUS_FAILED, timeout=15)

        resp = grpc_node_a.GetTask(ns_pb2.GetTaskRequest(task_id=task_id))
        assert resp.task.status == a2a_pb2.TASK_STATUS_FAILED


class TestBidirectionalTasks:
    """Test simultaneous task sending in both directions."""

    def test_bidirectional_tasks(self, grpc_node_a, grpc_node_b) -> None:
        """Both nodes send tasks to each other simultaneously."""
        peer_id_a, peer_id_b = connect_nodes(grpc_node_a, grpc_node_b)

        # Set cards.
        grpc_node_a.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(name=unique_id("bidir-a")),
            )
        )
        grpc_node_b.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(name=unique_id("bidir-b")),
            )
        )

        # Subscribe on both nodes.
        incoming_a = subscribe_and_collect(grpc_node_a)
        incoming_b = subscribe_and_collect(grpc_node_b)

        # Send tasks in both directions.
        text_a_to_b = unique_id("a-to-b")
        text_b_to_a = unique_id("b-to-a")
        task_id_ab = send_task_to_peer(grpc_node_a, peer_id_b, text=text_a_to_b)
        task_id_ba = send_task_to_peer(grpc_node_b, peer_id_a, text=text_b_to_a)

        # Wait for tasks to arrive.
        received_at_b = incoming_b.get(timeout=10)
        received_at_a = incoming_a.get(timeout=10)

        # Complete both tasks.
        complete_task(grpc_node_b, received_at_b.task.task_id, result_text="done-ab")
        complete_task(grpc_node_a, received_at_a.task.task_id, result_text="done-ba")

        # Verify both completed.
        wait_task_status(grpc_node_a, task_id_ab, a2a_pb2.TASK_STATUS_COMPLETED)
        wait_task_status(grpc_node_b, task_id_ba, a2a_pb2.TASK_STATUS_COMPLETED)
