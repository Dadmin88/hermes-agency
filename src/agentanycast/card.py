"""Agent Card and Skill data models — A2A compatible."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Skill:
    """Describes a single capability an agent exposes."""

    id: str
    description: str = ""
    input_schema: str | None = None
    output_schema: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.id, "description": self.description}
        if self.input_schema:
            d["input_schema"] = self.input_schema
        if self.output_schema:
            d["output_schema"] = self.output_schema
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        return cls(
            id=data["id"],
            description=data.get("description", ""),
            input_schema=data.get("input_schema"),
            output_schema=data.get("output_schema"),
        )


@dataclass
class AgentCard:
    """A2A-compatible capability descriptor for an agent node.

    Standard A2A fields are preserved. The P2P extension fields (peer_id,
    transports, relay_addresses) are populated automatically by the daemon
    after node startup.
    """

    name: str
    description: str = ""
    version: str = "1.0.0"
    protocol_version: str = "a2a/0.3"
    skills: list[Skill] = field(default_factory=list)

    # P2P extension (read-only, populated by daemon)
    peer_id: str | None = None
    supported_transports: list[str] = field(default_factory=list)
    relay_addresses: list[str] = field(default_factory=list)
    # v0.3: W3C DID (did:key) derived from the node's Ed25519 public key.
    did_key: str | None = None
    # v0.5: Additional identity fields
    did_web: str | None = None
    did_dns: str | None = None
    verifiable_credentials: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "protocol_version": self.protocol_version,
            "skills": [s.to_dict() for s in self.skills],
        }
        if self.peer_id:
            p2p: dict[str, Any] = {
                "peer_id": self.peer_id,
                "supported_transports": self.supported_transports,
                "relay_addresses": self.relay_addresses,
            }
            if self.did_key:
                p2p["did_key"] = self.did_key
            if self.did_web:
                p2p["did_web"] = self.did_web
            if self.did_dns:
                p2p["did_dns"] = self.did_dns
            if self.verifiable_credentials:
                p2p["verifiable_credentials"] = list(self.verifiable_credentials)
            d["agentanycast"] = p2p
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCard:
        skills = [Skill.from_dict(s) for s in data.get("skills", [])]
        p2p = data.get("agentanycast", {})
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            protocol_version=data.get("protocol_version", "a2a/0.3"),
            skills=skills,
            peer_id=p2p.get("peer_id"),
            supported_transports=p2p.get("supported_transports", []),
            relay_addresses=p2p.get("relay_addresses", []),
            did_key=p2p.get("did_key"),
            did_web=p2p.get("did_web"),
            did_dns=p2p.get("did_dns"),
            verifiable_credentials=p2p.get("verifiable_credentials", []),
        )
