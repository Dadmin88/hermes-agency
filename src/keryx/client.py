"""Async gRPC client for Keryx daemon and relay registry."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import grpc

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
        self._registry_endpoint = registry_endpoint or os.environ.get("HERMES_KERYX_REGISTRY_ENDPOINT")
        self._channel = channel
        self._registry_channel = registry_channel
        self._daemon: daemon_pb2_grpc.KeryxDaemonStub | None = None
        self._registry: registry_pb2_grpc.RegistryServiceStub | None = None

    async def connect(self) -> None:
        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(_grpc_target(self._daemon_endpoint))
        self._daemon = daemon_pb2_grpc.KeryxDaemonStub(self._channel)
        if self._registry_endpoint:
            if self._registry_channel is None:
                self._registry_channel = grpc.aio.insecure_channel(_grpc_target(self._registry_endpoint))
            self._registry = registry_pb2_grpc.RegistryServiceStub(self._registry_channel)

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
        if self._registry_channel is not None:
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
                    parts=[task_pb2.TaskMessagePart(text=message_text, media_type="text/plain")]
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

    async def discover(self, skill_id: str, *, tags: list[str] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        if self._registry is None:
            return []
        assert self._registry is not None
        response = await self._registry.DiscoverBySkill(
            registry_pb2.DiscoverBySkillRequest(skill_id=skill_id, tags=tags or [], limit=limit)
        )
        results: list[dict[str, Any]] = []
        for registration in response.registrations:
            results.append(
                {
                    "peer_id": registration.peer_id,
                    "agent_name": registration.name,
                    "agent_description": registration.description,
                    "skills": [skill.skill_id for skill in registration.skills],
                }
            )
        return results

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
                registry_pb2.SkillInfo(skill_id=skill_id, description=skill_description)
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
            registry_pb2.UnregisterSkillsRequest(peer_id=peer_id, skill_ids=skill_ids)
        )
        return bool(response.accepted)

    async def get_card(self, peer_id: str) -> "AgentCard":
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
                        Skill(id=skill.skill_id, description=skill.description)
                        for skill in registration.skills
                    ],
                    peer_id=registration.peer_id,
                )
        raise RuntimeError(f"No agent card for peer {peer_id}")