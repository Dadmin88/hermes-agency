"""Fixtures for integration tests.

These tests start real relay and daemon processes. They are skipped unless
the required binaries are available and the ``integration`` marker is active.

Run integration tests:

    pytest tests/integration/ -m integration -v

Skip in normal test runs:

    pytest tests/ -m "not integration"
"""

from __future__ import annotations

import os
import queue
import shutil
import signal
import socket
import subprocess
import threading
import time
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest

# ── Environment variables (set by Docker Compose) ────────────────────

RELAY_REGISTRY = os.environ.get("RELAY_REGISTRY")
NODE_A_GRPC = os.environ.get("NODE_A_GRPC")
NODE_B_GRPC = os.environ.get("NODE_B_GRPC")
NODE_C_GRPC = os.environ.get("NODE_C_GRPC")
RELAY_HEALTH = os.environ.get("RELAY_HEALTH", "http://relay:9090")
RELAY_API = os.environ.get("RELAY_API", "http://relay:8081")
NODE_A_BRIDGE = os.environ.get("NODE_A_BRIDGE", "http://node-a:8080")
RELAY_B_REGISTRY = os.environ.get("RELAY_B_REGISTRY")
RELAY_B_HEALTH = os.environ.get("RELAY_B_HEALTH")

# ── Marker registration ──────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "federation: federation tests")
    config.addinivalue_line("markers", "nats_transport: NATS transport tests")


# ── gRPC imports (skip if unavailable) ───────────────────────────────

grpc = pytest.importorskip("grpc")

from agentanycast._generated.agentanycast.v1 import (  # noqa: E402
    a2a_models_pb2 as a2a_pb2,
    agent_card_pb2 as card_pb2,
    node_service_pb2 as ns_pb2,
    node_service_pb2_grpc as ns_grpc,
    registry_service_pb2 as reg_pb2,
    registry_service_pb2_grpc as reg_grpc,
)


# ── Docker Compose gRPC fixtures ────────────────────────────────────


@pytest.fixture(scope="session")
def grpc_node_a():
    """gRPC stub for node-a (Docker Compose)."""
    if not NODE_A_GRPC:
        pytest.skip("NODE_A_GRPC not set")
    channel = grpc.insecure_channel(NODE_A_GRPC)
    return ns_grpc.NodeServiceStub(channel)


@pytest.fixture(scope="session")
def grpc_node_b():
    """gRPC stub for node-b (Docker Compose)."""
    if not NODE_B_GRPC:
        pytest.skip("NODE_B_GRPC not set")
    channel = grpc.insecure_channel(NODE_B_GRPC)
    return ns_grpc.NodeServiceStub(channel)


@pytest.fixture(scope="session")
def grpc_node_c():
    """gRPC stub for node-c (NATS transport, Docker Compose)."""
    if not NODE_C_GRPC:
        pytest.skip("NODE_C_GRPC not set")
    channel = grpc.insecure_channel(NODE_C_GRPC)
    return ns_grpc.NodeServiceStub(channel)


@pytest.fixture(scope="session")
def grpc_registry():
    """gRPC stub for the relay registry (Docker Compose)."""
    if not RELAY_REGISTRY:
        pytest.skip("RELAY_REGISTRY not set")
    channel = grpc.insecure_channel(RELAY_REGISTRY)
    return reg_grpc.RegistryServiceStub(channel)


@pytest.fixture(scope="session")
def grpc_registry_b():
    """gRPC stub for relay-b registry (federation tests)."""
    if not RELAY_B_REGISTRY:
        pytest.skip("RELAY_B_REGISTRY not set")
    channel = grpc.insecure_channel(RELAY_B_REGISTRY)
    return reg_grpc.RegistryServiceStub(channel)


# ── Helpers ──────────────────────────────────────────────────────────


def unique_id(prefix: str = "test") -> str:
    """Generate a unique ID with the given prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def wait_for(predicate, timeout: float = 10, interval: float = 0.5, msg: str = "condition not met"):
    """Poll until predicate returns truthy or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    pytest.fail(f"Timeout after {timeout}s: {msg}")


def subscribe_and_collect(client, timeout: float = 10):
    """Subscribe to incoming tasks and return a queue of received tasks."""
    q: queue.Queue = queue.Queue()

    def _sub():
        try:
            stream = client.SubscribeIncomingTasks(ns_pb2.SubscribeIncomingTasksRequest())
            for resp in stream:
                q.put(resp)
        except grpc.RpcError:
            pass

    t = threading.Thread(target=_sub, daemon=True)
    t.start()
    time.sleep(0.3)  # Let subscription establish
    return q


def send_task_to_peer(sender_client, peer_id: str, text: str = "hello") -> str:
    """Send a text task from sender to peer, return task_id."""
    resp = sender_client.SendTask(ns_pb2.SendTaskRequest(
        peer_id=peer_id,
        message=a2a_pb2.Message(
            role=a2a_pb2.MESSAGE_ROLE_USER,
            parts=[a2a_pb2.Part(text_part=a2a_pb2.TextPart(text=text))],
        ),
    ))
    return resp.task.task_id


def complete_task(client, task_id: str, result_text: str = "done") -> None:
    """Transition task to WORKING then COMPLETED."""
    client.UpdateTaskStatus(ns_pb2.UpdateTaskStatusRequest(
        task_id=task_id, status=a2a_pb2.TASK_STATUS_WORKING,
    ))
    client.CompleteTask(ns_pb2.CompleteTaskRequest(
        task_id=task_id,
        artifacts=[a2a_pb2.Artifact(
            artifact_id=unique_id("art"),
            name="result",
            parts=[a2a_pb2.Part(text_part=a2a_pb2.TextPart(text=result_text))],
        )],
    ))


def fail_task(client, task_id: str, error_message: str = "test error") -> None:
    """Transition task to WORKING then FAILED."""
    client.UpdateTaskStatus(ns_pb2.UpdateTaskStatusRequest(
        task_id=task_id, status=a2a_pb2.TASK_STATUS_WORKING,
    ))
    client.FailTask(ns_pb2.FailTaskRequest(
        task_id=task_id, error_message=error_message,
    ))


def wait_task_status(client, task_id: str, status, timeout: float = 15):
    """Poll until task reaches the given status."""
    def _check():
        resp = client.GetTask(ns_pb2.GetTaskRequest(task_id=task_id))
        return resp.task.status == status

    wait_for(_check, timeout=timeout, msg=f"task {task_id} did not reach status {status}")


def wait_task_completed(client, task_id: str, timeout: float = 15):
    """Poll until task reaches COMPLETED status."""
    wait_task_status(client, task_id, a2a_pb2.TASK_STATUS_COMPLETED, timeout=timeout)


def connect_nodes(client_a, client_b):
    """Connect node-a to node-b and return (peer_id_a, peer_id_b)."""
    resp_a = client_a.GetNodeInfo(ns_pb2.GetNodeInfoRequest())
    resp_b = client_b.GetNodeInfo(ns_pb2.GetNodeInfoRequest())
    peer_id_a = resp_a.node_info.peer_id
    peer_id_b = resp_b.node_info.peer_id
    addrs_b = list(resp_b.node_info.listen_addresses)

    client_a.ConnectPeer(ns_pb2.ConnectPeerRequest(
        peer_id=peer_id_b,
        addresses=addrs_b,
    ))
    return peer_id_a, peer_id_b


# ── Local binary discovery (for non-Docker tests) ───────────────────

RELAY_BINARY_CANDIDATES = [
    os.environ.get("RELAY_BINARY", ""),
    str(Path(__file__).parents[3] / "agentanycast-relay" / "bin" / "relay"),
    str(Path(__file__).parents[3] / "agentanycast-relay" / "agentanycast-relay"),
    shutil.which("agentanycast-relay") or "",
]

NODE_BINARY_CANDIDATES = [
    os.environ.get("NODE_BINARY", ""),
    str(Path(__file__).parents[3] / "agentanycast-node" / "bin" / "agentanycastd"),
    str(Path(__file__).parents[3] / "agentanycast-node" / "agentanycastd"),
    shutil.which("agentanycastd") or "",
]


def _find_binary(candidates: list[str]) -> str | None:
    for p in candidates:
        if p and Path(p).is_file() and os.access(p, os.X_OK):
            return p
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 10.0) -> bool:
    """Wait until a TCP port is accepting connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


# ── Local binary fixtures ───────────────────────────────────────────


@pytest.fixture(scope="session")
def relay_binary() -> str:
    binary = _find_binary(RELAY_BINARY_CANDIDATES)
    if not binary:
        pytest.skip(
            "Relay binary not found. Build with:\n"
            "  cd agentanycast-relay && go build -o bin/relay ./cmd/relay\n"
            "Or set RELAY_BINARY env var."
        )
    return binary


@pytest.fixture(scope="session")
def node_binary() -> str:
    binary = _find_binary(NODE_BINARY_CANDIDATES)
    if not binary:
        pytest.skip(
            "Node binary not found. Build with:\n"
            "  cd agentanycast-node && make build\n"
            "Or set NODE_BINARY env var."
        )
    return binary


@pytest.fixture(scope="session")
def relay_process(
    relay_binary: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[dict[str, str], None, None]:
    """Start a real relay process for the test session.

    Yields a dict with connection info:
        {
            "p2p_port": "12345",
            "registry_port": "12346",
            "registry_addr": "127.0.0.1:12346",
            "p2p_multiaddr": "/ip4/127.0.0.1/tcp/12345",
        }
    """
    p2p_port = _free_port()
    registry_port = _free_port()
    key_path = str(tmp_path_factory.mktemp("relay") / "key")

    cmd = [
        relay_binary,
        "--listen",
        f"/ip4/127.0.0.1/tcp/{p2p_port}",
        "--registry-listen",
        f"127.0.0.1:{registry_port}",
        "--registry-ttl",
        "30s",
        "--log-level",
        "error",
        "--key",
        key_path,
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for registry gRPC port.
    if not _wait_for_port(registry_port):
        proc.kill()
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        pytest.fail(f"Relay failed to start within 10s.\nStderr: {stderr}")

    # Parse peer ID from stdout.
    relay_multiaddr = ""
    if proc.stdout:
        for line in iter(proc.stdout.readline, b""):
            text = line.decode().strip()
            if text.startswith("RELAY_ADDR="):
                relay_multiaddr = text.split("=", 1)[1]
            if text.startswith("REGISTRY_ADDR="):
                break

    info = {
        "p2p_port": str(p2p_port),
        "registry_port": str(registry_port),
        "registry_addr": f"127.0.0.1:{registry_port}",
        "p2p_multiaddr": relay_multiaddr or f"/ip4/127.0.0.1/tcp/{p2p_port}",
    }

    yield info

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def daemon_factory(
    node_binary: str,
    relay_process: dict[str, str],
    tmp_path: Path,
) -> Generator:
    """Factory fixture that creates daemon processes on demand.

    Usage in tests:

        info_a = daemon_factory("agent-a")
        info_b = daemon_factory("agent-b")
        # info_a["grpc_addr"] is the Unix socket or TCP address
    """
    processes: list[subprocess.Popen] = []  # type: ignore[type-arg]
    counter = 0

    def _create(name: str = "test-agent") -> dict[str, str]:
        nonlocal counter
        counter += 1

        home = tmp_path / f"daemon-{counter}"
        home.mkdir()
        grpc_port = _free_port()
        grpc_addr = f"tcp://127.0.0.1:{grpc_port}"

        bootstrap = relay_process["p2p_multiaddr"]

        cmd = [
            node_binary,
            "--grpc-listen",
            grpc_addr,
            "--key",
            str(home / "key"),
            "--log-level",
            "error",
            "--bootstrap-peers",
            bootstrap,
        ]

        # Set config via env to avoid needing a config file.
        env = os.environ.copy()
        env["AGENTANYCAST_STORE_PATH"] = str(home / "data")
        env["AGENTANYCAST_ENABLE_MDNS"] = "false"

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        processes.append(proc)

        # Wait for gRPC port.
        if not _wait_for_port(grpc_port):
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            pytest.fail(f"Daemon {name} failed to start.\nStderr: {stderr}")

        # Parse peer ID from stdout.
        peer_id = ""
        if proc.stdout:
            for line in iter(proc.stdout.readline, b""):
                text = line.decode().strip()
                if text.startswith("PEER_ID="):
                    peer_id = text.split("=", 1)[1]
                    break

        return {
            "name": name,
            "peer_id": peer_id,
            "grpc_addr": grpc_addr,
            "grpc_port": str(grpc_port),
            "home": str(home),
        }

    yield _create

    # Cleanup all daemon processes.
    for proc in processes:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
