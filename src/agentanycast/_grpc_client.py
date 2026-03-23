"""gRPC client wrapper for communicating with the agentanycastd daemon."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import grpc

from agentanycast._generated.agentanycast.v1 import (
    a2a_models_pb2,
    agent_card_pb2,
    common_pb2,
    node_service_pb2,
    node_service_pb2_grpc,
)
from agentanycast.exceptions import (
    CardNotAvailableError,
    DaemonConnectionError,
    PeerNotFoundError,
    SkillNotFoundError,
    TaskNotFoundError,
)

logger = logging.getLogger(__name__)

# gRPC status codes that indicate transient failures worth retrying.
_RETRYABLE_CODES = frozenset(
    {
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.INTERNAL,
        grpc.StatusCode.UNKNOWN,
    }
)

# Default retry parameters for unary RPCs.
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_INITIAL_BACKOFF = 0.5


async def _retry_unary(
    coro_factory: Any,
    *,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    initial_backoff: float = _DEFAULT_INITIAL_BACKOFF,
) -> Any:
    """Retry a unary gRPC call on transient failures with exponential backoff.

    Args:
        coro_factory: A zero-argument callable that returns an awaitable gRPC call.
        max_retries: Maximum number of retry attempts.
        initial_backoff: Initial backoff delay in seconds (doubles each retry).

    Returns:
        The result of the successful call.

    Raises:
        grpc.aio.AioRpcError: Re-raised if all retries are exhausted or the
            error is not transient.
    """
    backoff = initial_backoff
    last_error: grpc.aio.AioRpcError | None = None
    for attempt in range(1 + max_retries):
        try:
            return await coro_factory()
        except grpc.aio.AioRpcError as e:
            last_error = e
            if e.code() not in _RETRYABLE_CODES or attempt >= max_retries:
                raise
            logger.warning(
                "gRPC call failed (retry %d/%d): %s", attempt + 1, max_retries, e.details()
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10.0)
    raise last_error  # type: ignore[misc]  # unreachable but satisfies type checker


class GrpcClient:
    """Async gRPC client wrapping NodeService calls.

    Translates gRPC errors into AgentAnycast exception types.
    """

    def __init__(self, address: str) -> None:
        self._address = address
        self._channel: grpc.aio.Channel | None = None
        self._stub: node_service_pb2_grpc.NodeServiceStub | None = None

    async def connect(self) -> None:
        """Establish the gRPC channel and validate the connection."""
        target = self._address
        if target.startswith("unix://"):
            target = self._address  # grpc.aio handles unix:// natively
        elif target.startswith("tcp://"):
            target = target[6:]

        self._channel = grpc.aio.insecure_channel(target)
        self._stub = node_service_pb2_grpc.NodeServiceStub(self._channel)
        logger.debug("gRPC channel created for %s", target)

        # Validate the connection by performing a health check
        try:
            await self._stub.GetNodeInfo(
                node_service_pb2.GetNodeInfoRequest(),
                timeout=5,
            )
            logger.debug("gRPC connection validated to %s", target)
        except grpc.aio.AioRpcError as e:
            # Clean up the channel on failure
            await self._channel.close()
            self._channel = None
            self._stub = None
            raise DaemonConnectionError(
                f"Failed to connect to daemon at {self._address}: {e.details() or e.code()}. "
                f"Ensure the daemon is running and reachable."
            ) from e

    async def close(self) -> None:
        """Close the gRPC channel."""
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None

    def _ensure_connected(self) -> node_service_pb2_grpc.NodeServiceStub:
        if self._stub is None:
            raise DaemonConnectionError("gRPC client not connected")
        return self._stub

    # ── Node Management ────────────────────────────────────────

    async def get_node_info(self) -> common_pb2.NodeInfo:
        """Get the local node's info (PeerID, addresses, etc.)."""
        stub = self._ensure_connected()
        resp = await stub.GetNodeInfo(node_service_pb2.GetNodeInfoRequest())
        return resp.node_info

    async def set_agent_card(self, card: agent_card_pb2.AgentCard) -> None:
        """Set or update the local agent card."""
        stub = self._ensure_connected()
        await stub.SetAgentCard(node_service_pb2.SetAgentCardRequest(card=card))

    # ── Peer Management ────────────────────────────────────────

    async def connect_peer(
        self, peer_id: str, addresses: list[str] | None = None
    ) -> common_pb2.PeerInfo:
        """Connect to a remote peer."""
        stub = self._ensure_connected()
        try:
            resp = await stub.ConnectPeer(
                node_service_pb2.ConnectPeerRequest(
                    peer_id=peer_id,
                    addresses=addresses or [],
                )
            )
            return resp.peer_info
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                raise PeerNotFoundError(f"Cannot connect to peer {peer_id}: {e.details()}")
            raise

    async def list_peers(self) -> list[common_pb2.PeerInfo]:
        """List all connected peers."""
        stub = self._ensure_connected()
        resp = await stub.ListPeers(node_service_pb2.ListPeersRequest())
        return list(resp.peers)

    async def get_peer_card(self, peer_id: str) -> agent_card_pb2.AgentCard:
        """Get the agent card of a connected peer.

        Automatically retries on transient gRPC failures.
        """
        stub = self._ensure_connected()
        try:
            resp = await _retry_unary(
                lambda: stub.GetPeerCard(node_service_pb2.GetPeerCardRequest(peer_id=peer_id))
            )
            return resp.card
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                raise CardNotAvailableError(f"No card for peer {peer_id}")
            if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                raise PeerNotFoundError(f"Invalid peer_id: {peer_id}")
            raise

    # ── Task Client Operations ─────────────────────────────────

    async def send_task(
        self,
        message: a2a_models_pb2.Message,
        *,
        peer_id: str | None = None,
        skill_id: str | None = None,
        url: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> a2a_models_pb2.Task:
        """Send a task to a remote agent. Exactly one of peer_id, skill_id, or url must be set.

        Automatically retries on transient gRPC failures (UNAVAILABLE, INTERNAL)
        with exponential backoff.
        """
        stub = self._ensure_connected()

        kwargs: dict[str, Any] = {"message": message}
        if metadata:
            kwargs["metadata"] = metadata
        if peer_id is not None:
            kwargs["peer_id"] = peer_id
        elif skill_id is not None:
            kwargs["skill_id"] = skill_id
        elif url is not None:
            kwargs["url"] = url

        try:
            resp = await _retry_unary(
                lambda: stub.SendTask(node_service_pb2.SendTaskRequest(**kwargs))
            )
            return resp.task
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                raise PeerNotFoundError(f"Cannot reach target: {e.details()}")
            if e.code() == grpc.StatusCode.NOT_FOUND:
                raise SkillNotFoundError(f"No agents for skill: {e.details()}")
            raise

    async def discover(
        self,
        skill_id: str,
        *,
        tags: dict[str, str] | None = None,
        limit: int = 0,
    ) -> node_service_pb2.DiscoverResponse:
        """Discover agents offering a specific skill."""
        stub = self._ensure_connected()
        try:
            return await stub.Discover(
                node_service_pb2.DiscoverRequest(
                    skill_id=skill_id,
                    tags=tags or {},
                    limit=limit,
                )
            )
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                raise SkillNotFoundError(f"Discovery unavailable: {e.details()}")
            raise

    async def subscribe_task_stream(
        self, task_id: str, *, max_retries: int = 3
    ) -> AsyncIterator[node_service_pb2.SubscribeTaskStreamResponse]:
        """Stream artifact chunks for a task."""
        backoff = 0.5
        retries = 0
        while True:
            stub = self._ensure_connected()
            try:
                async for event in stub.SubscribeTaskStream(
                    node_service_pb2.SubscribeTaskStreamRequest(task_id=task_id)
                ):
                    retries = 0
                    backoff = 0.5
                    yield event
                return
            except grpc.aio.AioRpcError as e:
                if e.code() in _RETRYABLE_CODES and retries < max_retries:
                    retries += 1
                    logger.warning(
                        "Task stream broken (retry %d/%d): %s",
                        retries,
                        max_retries,
                        e.code(),
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                else:
                    raise

    async def get_task(self, task_id: str) -> a2a_models_pb2.Task:
        """Get the current state of a task."""
        stub = self._ensure_connected()
        try:
            resp = await stub.GetTask(node_service_pb2.GetTaskRequest(task_id=task_id))
            return resp.task
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                raise TaskNotFoundError(f"Task {task_id} not found")
            raise

    async def cancel_task(self, task_id: str) -> a2a_models_pb2.Task:
        """Cancel a task."""
        stub = self._ensure_connected()
        try:
            resp = await stub.CancelTask(node_service_pb2.CancelTaskRequest(task_id=task_id))
            return resp.task
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                raise TaskNotFoundError(f"Task {task_id} not found")
            raise

    async def subscribe_task_updates(
        self, task_id: str, *, max_retries: int = 3
    ) -> AsyncIterator[node_service_pb2.SubscribeTaskUpdatesResponse]:
        """Stream status updates for a specific task.

        Automatically reconnects on transient gRPC errors with exponential backoff.
        """
        backoff = 0.5
        retries = 0
        while True:
            stub = self._ensure_connected()
            try:
                async for event in stub.SubscribeTaskUpdates(
                    node_service_pb2.SubscribeTaskUpdatesRequest(task_id=task_id)
                ):
                    retries = 0  # reset on successful message
                    backoff = 0.5
                    yield event
                return  # stream completed normally
            except grpc.aio.AioRpcError as e:
                if e.code() in _RETRYABLE_CODES and retries < max_retries:
                    retries += 1
                    logger.warning(
                        "Task update stream broken (retry %d/%d): %s",
                        retries,
                        max_retries,
                        e.code(),
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                else:
                    raise

    # ── Task Server Operations ─────────────────────────────────

    async def subscribe_incoming_tasks(
        self, *, max_retries: int = 5
    ) -> AsyncIterator[node_service_pb2.SubscribeIncomingTasksResponse]:
        """Stream new incoming task requests from remote agents.

        Automatically reconnects on transient gRPC errors with exponential backoff.
        """
        backoff = 0.5
        retries = 0
        while True:
            stub = self._ensure_connected()
            try:
                async for event in stub.SubscribeIncomingTasks(
                    node_service_pb2.SubscribeIncomingTasksRequest()
                ):
                    retries = 0
                    backoff = 0.5
                    yield event
                return
            except grpc.aio.AioRpcError as e:
                if e.code() in _RETRYABLE_CODES and retries < max_retries:
                    retries += 1
                    logger.warning(
                        "Incoming tasks stream broken (retry %d/%d): %s",
                        retries,
                        max_retries,
                        e.code(),
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                else:
                    raise

    async def update_task_status(
        self,
        task_id: str,
        status: a2a_models_pb2.TaskStatus.ValueType,
        message: a2a_models_pb2.Message | None = None,
    ) -> None:
        """Update the status of a task this node is processing."""
        stub = self._ensure_connected()
        await stub.UpdateTaskStatus(
            node_service_pb2.UpdateTaskStatusRequest(
                task_id=task_id,
                status=status,
                message=message,
            )
        )

    async def complete_task(
        self,
        task_id: str,
        artifacts: list[a2a_models_pb2.Artifact] | None = None,
        message: a2a_models_pb2.Message | None = None,
    ) -> None:
        """Complete a task with artifacts."""
        stub = self._ensure_connected()
        await stub.CompleteTask(
            node_service_pb2.CompleteTaskRequest(
                task_id=task_id,
                artifacts=artifacts or [],
                message=message,
            )
        )

    async def fail_task(self, task_id: str, error_message: str) -> None:
        """Fail a task with an error message."""
        stub = self._ensure_connected()
        await stub.FailTask(
            node_service_pb2.FailTaskRequest(
                task_id=task_id,
                error_message=error_message,
            )
        )
