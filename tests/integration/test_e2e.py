"""End-to-end integration tests for the Python SDK.

These tests start real relay and daemon processes, then use the SDK
to verify agent-to-agent communication works.

Run:
    pytest tests/integration/ -m integration -v

Prerequisites:
    - Build relay: cd agentanycast-relay && go build -o bin/relay ./cmd/relay
    - Build node:  cd agentanycast-node && make build
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

import grpc
import pytest

from agentanycast._generated.agentanycast.v1 import (
    a2a_models_pb2 as a2a_pb2,
)
from agentanycast._generated.agentanycast.v1 import (
    agent_card_pb2 as card_pb2,
)
from agentanycast._generated.agentanycast.v1 import (
    node_service_pb2 as ns_pb2,
)
from agentanycast._generated.agentanycast.v1 import (
    node_service_pb2_grpc as ns_grpc,
)


@pytest.mark.integration
class TestEndToEnd:
    """End-to-end tests using real relay and daemon processes."""

    def test_daemon_starts_and_returns_peer_id(self, daemon_factory: Any) -> None:
        """A daemon should start and return a valid peer ID."""
        info = daemon_factory("echo-agent")
        assert info["peer_id"], "daemon should return a peer ID"
        assert info["peer_id"].startswith("12D3KooW") or len(info["peer_id"]) > 10

    def test_two_daemons_get_different_peer_ids(self, daemon_factory: Any) -> None:
        """Two daemons should have different identities."""
        a = daemon_factory("agent-a")
        b = daemon_factory("agent-b")
        assert a["peer_id"] != b["peer_id"]

    def test_p2p_task_lifecycle(self, daemon_factory: Any) -> None:
        """Send a task from daemon A to daemon B over Noise-encrypted P2P.

        This verifies the full A2A task lifecycle:
        connect → set cards → send task → receive → complete → verify.
        All communication is encrypted via Noise_XX (the only security transport).
        """
        info_a = daemon_factory("sender")
        info_b = daemon_factory("receiver")

        # Create gRPC stubs.
        chan_a = grpc.insecure_channel(f"127.0.0.1:{info_a['grpc_port']}")
        chan_b = grpc.insecure_channel(f"127.0.0.1:{info_b['grpc_port']}")
        client_a = ns_grpc.NodeServiceStub(chan_a)
        client_b = ns_grpc.NodeServiceStub(chan_b)

        # Get node info for both (to get listen addresses).
        resp_b = client_b.GetNodeInfo(ns_pb2.GetNodeInfoRequest())
        peer_id_b = resp_b.node_info.peer_id
        addrs_b = list(resp_b.node_info.listen_addresses)
        assert peer_id_b, "receiver should have a peer ID"

        # Connect sender to receiver.
        client_a.ConnectPeer(
            ns_pb2.ConnectPeerRequest(
                peer_id=peer_id_b,
                addresses=addrs_b,
            )
        )

        # Set agent cards.
        client_a.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(
                    name="Sender Agent",
                    skills=[card_pb2.Skill(id="send", description="Sends tasks")],
                ),
            )
        )
        client_b.SetAgentCard(
            ns_pb2.SetAgentCardRequest(
                card=card_pb2.AgentCard(
                    name="Receiver Agent",
                    skills=[card_pb2.Skill(id="echo", description="Echoes input")],
                ),
            )
        )

        # Subscribe to incoming tasks on receiver (background thread).
        incoming: queue.Queue[ns_pb2.SubscribeIncomingTasksResponse] = queue.Queue()

        def _subscribe() -> None:
            try:
                stream = client_b.SubscribeIncomingTasks(ns_pb2.SubscribeIncomingTasksRequest())
                for resp in stream:
                    incoming.put(resp)
            except grpc.RpcError:
                pass  # Stream cancelled on cleanup.

        sub_thread = threading.Thread(target=_subscribe, daemon=True)
        sub_thread.start()
        time.sleep(0.5)  # Let subscription establish.

        # Send task from A → B.
        send_resp = client_a.SendTask(
            ns_pb2.SendTaskRequest(
                peer_id=peer_id_b,
                message=a2a_pb2.Message(
                    role=a2a_pb2.MESSAGE_ROLE_USER,
                    parts=[
                        a2a_pb2.Part(
                            text_part=a2a_pb2.TextPart(text="hello via Noise"),
                        )
                    ],
                ),
            )
        )
        task_id = send_resp.task.task_id
        assert task_id, "SendTask should return a task ID"

        # Wait for task to arrive at receiver.
        try:
            received = incoming.get(timeout=10)
        except queue.Empty:
            pytest.fail("Task did not arrive at receiver within 10s")

        assert received.task.task_id, "incoming task should have an ID"

        # Transition to WORKING, then complete.
        client_b.UpdateTaskStatus(
            ns_pb2.UpdateTaskStatusRequest(
                task_id=received.task.task_id,
                status=a2a_pb2.TASK_STATUS_WORKING,
            )
        )
        client_b.CompleteTask(
            ns_pb2.CompleteTaskRequest(
                task_id=received.task.task_id,
                artifacts=[
                    a2a_pb2.Artifact(
                        artifact_id="art-1",
                        name="echo-result",
                        parts=[
                            a2a_pb2.Part(
                                text_part=a2a_pb2.TextPart(text="echo: hello via Noise"),
                            )
                        ],
                    )
                ],
            )
        )

        # Poll GetTask on sender until completed.
        for _ in range(30):
            resp = client_a.GetTask(ns_pb2.GetTaskRequest(task_id=task_id))
            if resp.task.status == a2a_pb2.TASK_STATUS_COMPLETED:
                break
            time.sleep(0.5)
        else:
            pytest.fail(f"Task did not complete within 15s. Final status: {resp.task.status}")

        assert resp.task.status == a2a_pb2.TASK_STATUS_COMPLETED
