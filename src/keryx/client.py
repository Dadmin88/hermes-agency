"""Async gRPC client for Keryx daemon and relay registry."""

from __future__ import annotations

import os
import socket
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import grpc

if TYPE_CHECKING:
    from keryx.card import AgentCard

_PROTO_ROOT = Path(__file__).resolve().parent / "proto"
if str(_PROTO_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROTO_ROOT))

from hermes.keryx.v1 import (  # noqa: E402
    common_pb2,
    daemon_pb2,
    daemon_pb2_grpc,
    registry_pb2,
    registry_pb2_grpc,
    task_pb2,
)


def default_daemon_endpoint() -> str:
    socket_path = Path.home().expanduser() / ".hermes" / "keryx" / "run" / "keryx-daemon.sock"
    return f"unix://{socket_path}"


def _unix_socket_path(endpoint: str) -> Path | None:
    if not endpoint.startswith("unix://"):
        return None
    return Path(endpoint.removeprefix("unix://")).expanduser()


def _validate_unix_socket_endpoint(endpoint: str) -> None:
    path = _unix_socket_path(endpoint)
    if path is None:
        return

    try:
        parent_stat = path.parent.stat()
        socket_stat = path.stat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"daemon socket does not exist: {path}") from exc

    current_uid = os.getuid()
    if parent_stat.st_uid != current_uid:
        raise RuntimeError(
            f"daemon socket directory is not owned by the current user: {path.parent}"
        )
    if parent_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise RuntimeError(
            f"daemon socket directory must not be accessible by group or other users: {path.parent}"
        )
    if socket_stat.st_uid != current_uid:
        raise RuntimeError(f"daemon socket is not owned by the current user: {path}")
    if not stat.S_ISSOCK(socket_stat.st_mode):
        raise RuntimeError(f"daemon endpoint is not a Unix socket: {path}")
    if socket_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError(f"daemon socket must not be writable by group or other users: {path}")


def _assert_unix_peer_owned_by_current_user(endpoint: str) -> None:
    path = _unix_socket_path(endpoint)
    if path is None or not hasattr(socket, "SO_PEERCRED"):
        return

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.connect(str(path))
            credentials = probe.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    except OSError as exc:
        raise RuntimeError(f"daemon socket peer could not be verified: {path}") from exc
    _, peer_uid, _ = struct.unpack("3i", credentials)
    if peer_uid != os.getuid():
        raise RuntimeError(f"daemon socket peer is not owned by the current user: {path}")


def _grpc_target(endpoint: str) -> str:
    if endpoint.startswith("unix://"):
        return endpoint
    if endpoint.startswith("tcp://"):
        return endpoint.removeprefix("tcp://")
    return endpoint


@dataclass
class PeerInfo:
    peer_id: str
    connected: bool
    local: bool


class DaemonClient:
    """Thin wrapper over ``KeryxDaemon`` and ``RegistryService`` stubs."""

    def __init__(
        self,
        *,
        daemon_endpoint: str,
        registry_endpoint: str | None = None,
        channel: grpc.aio.Channel | None = None,
        registry_channel: grpc.aio.Channel | None = None,
    ) -> None:
        self._daemon_endpoint = daemon_endpoint
        self._registry_endpoint = registry_endpoint or os.environ.get(
            "HERMES_KERYX_REGISTRY_ENDPOINT"
        )
        self._channel = channel
        self._registry_channel = registry_channel
        self._owns_channel = channel is None
        self._owns_registry_channel = registry_channel is None
        self._daemon: daemon_pb2_grpc.KeryxDaemonStub | None = None
        self._registry: registry_pb2_grpc.RegistryServiceStub | None = None

    async def connect(self) -> None:
        if self._channel is None:
            _validate_unix_socket_endpoint(self._daemon_endpoint)
            _assert_unix_peer_owned_by_current_user(self._daemon_endpoint)
            self._channel = grpc.aio.insecure_channel(_grpc_target(self._daemon_endpoint))
            self._owns_channel = True
        self._daemon = daemon_pb2_grpc.KeryxDaemonStub(self._channel)
        if self._registry_endpoint:
            if self._registry_channel is None:
                self._registry_channel = grpc.aio.insecure_channel(
                    _grpc_target(self._registry_endpoint)
                )
                self._owns_registry_channel = True
            self._registry = registry_pb2_grpc.RegistryServiceStub(self._registry_channel)

    async def close(self) -> None:
        if self._channel is not None and self._owns_channel:
            await self._channel.close()
        self._channel = None
        if self._registry_channel is not None and self._owns_registry_channel:
            await self._registry_channel.close()
        self._registry_channel = None
        self._daemon = None
        self._registry = None

    async def list_peers(self) -> list[PeerInfo]:
        assert self._daemon is not None
        response = await self._daemon.ListPeers(daemon_pb2.ListPeersRequest())
        return [
            PeerInfo(peer_id=item.peer_id, connected=item.connected, local=item.local)
            for item in response.peers
        ]

    async def local_peer_id(self) -> str:
        for peer in await self.list_peers():
            if peer.local:
                return peer.peer_id
        peers = await self.list_peers()
        if peers:
            return peers[0].peer_id
        raise RuntimeError("daemon did not report a local peer id")

    async def send_task(
        self,
        *,
        target_peer_id: str,
        task_id: str,
        message_text: str,
        metadata: dict[str, str] | None = None,
        timeout_ms: int = 0,
    ) -> daemon_pb2.SendTaskResponse:
        assert self._daemon is not None
        envelope = task_pb2.TaskEnvelope(
            task_id=common_pb2.TaskId(value=task_id),
            status=task_pb2.TASK_STATUS_CREATED,
            messages=[
                task_pb2.TaskMessage(
                    parts=[
                        task_pb2.TaskMessagePart(
                            text=message_text,
                            media_type="text/plain",
                        )
                    ]
                )
            ],
            metadata=metadata or {},
        )
        request = daemon_pb2.SendTaskRequest(
            target_peer_id=target_peer_id,
            envelope=envelope,
            timeout_ms=timeout_ms,
        )
        return await self._daemon.SendTask(request)

    async def get_task_result(self, task_id: str) -> daemon_pb2.GetTaskResultResponse:
        assert self._daemon is not None
        return await self._daemon.GetTaskResult(
            daemon_pb2.GetTaskResultRequest(task_id=common_pb2.TaskId(value=task_id))
        )

    async def cancel_task(self, task_id: str, *, reason: str = "") -> daemon_pb2.CancelTaskResponse:
        assert self._daemon is not None
        return await self._daemon.CancelTask(
            daemon_pb2.CancelTaskRequest(
                task_id=common_pb2.TaskId(value=task_id),
                reason=reason,
            )
        )

    async def discover(
        self,
        skill_id: str,
        *,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if self._registry is None:
            return []
        assert self._registry is not None
        requested_tags = {tag.strip() for tag in tags or [] if tag.strip()}
        response = await self._registry.DiscoverBySkill(
            registry_pb2.DiscoverBySkillRequest(
                skill_id=skill_id,
                tags=tags or [],
                limit=limit,
            )
        )
        registrations = list(response.registrations)

        # Registry gossip can briefly expose a node before its secondary skill
        # index catches up. Fall back to one bounded full-registry read and
        # filter locally so discovery remains correct without an unbounded scan.
        if skill_id and not registrations:
            fallback_limit = limit if limit > 0 else 100
            fallback = await self._registry.DiscoverBySkill(
                registry_pb2.DiscoverBySkillRequest(
                    skill_id="",
                    limit=fallback_limit,
                )
            )
            registrations = []
            for registration in fallback.registrations:
                matching_skill = next(
                    (skill for skill in registration.skills if skill.skill_id == skill_id),
                    None,
                )
                if matching_skill is None:
                    continue
                skill_tags = {tag.strip() for tag in matching_skill.tags if tag.strip()}
                if requested_tags and not requested_tags.issubset(skill_tags):
                    continue
                registrations.append(registration)
                if limit > 0 and len(registrations) >= limit:
                    break

        return [
            {
                "peer_id": registration.peer_id,
                "agent_name": registration.name,
                "agent_description": registration.description,
                "skills": [skill.skill_id for skill in registration.skills],
            }
            for registration in registrations
        ]

    async def register_skills(
        self,
        *,
        peer_id: str,
        name: str,
        description: str,
        skills: list[tuple[str, str]],
        ttl_seconds: int = 300,
    ) -> bool:
        if self._registry is None:
            return False
        assert self._registry is not None
        request = registry_pb2.RegisterSkillsRequest(
            peer_id=peer_id,
            name=name,
            description=description,
            ttl_seconds=ttl_seconds,
            skills=[
                registry_pb2.SkillInfo(
                    skill_id=skill_id,
                    description=skill_description,
                )
                for skill_id, skill_description in skills
            ],
        )
        response = await self._registry.RegisterSkills(request)
        return bool(response.accepted)

    async def unregister_skills(self, *, peer_id: str, skill_ids: list[str]) -> bool:
        if self._registry is None:
            return False
        assert self._registry is not None
        response = await self._registry.UnregisterSkills(
            registry_pb2.UnregisterSkillsRequest(
                peer_id=peer_id,
                skill_ids=skill_ids,
            )
        )
        return bool(response.accepted)

    async def get_card(self, peer_id: str) -> AgentCard:
        from keryx.card import AgentCard, Skill

        if self._registry is None:
            raise RuntimeError("registry client is not configured")
        assert self._registry is not None
        response = await self._registry.DiscoverBySkill(
            registry_pb2.DiscoverBySkillRequest(skill_id="", limit=100)
        )
        for registration in response.registrations:
            if registration.peer_id == peer_id:
                return AgentCard(
                    name=registration.name or registration.peer_id,
                    description=registration.description,
                    skills=[
                        Skill(
                            id=skill.skill_id,
                            description=skill.description,
                        )
                        for skill in registration.skills
                    ],
                    peer_id=registration.peer_id,
                )
        raise RuntimeError(f"No agent card for peer {peer_id}")
