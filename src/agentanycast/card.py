"""Agent Card and Skill data models — A2A compatible."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_SKILL_ID_LENGTH = 128
MAX_SKILL_DESCRIPTION_LENGTH = 4 * 1024
MAX_AGENT_CARD_NAME_LENGTH = 256
MAX_AGENT_CARD_DESCRIPTION_LENGTH = 4 * 1024
MAX_SKILLS_PER_CARD = 256

_SAFE_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\/-]{0,127}$")


def _is_safe_skill_id(skill_id: str) -> bool:
    if not _SAFE_SKILL_ID_RE.fullmatch(skill_id):
        return False
    if "/" not in skill_id:
        return True
    parts = skill_id.split("/")
    return all(part and part not in {".", ".."} for part in parts)


def _require_mapping(data: Any, model_name: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{model_name}.from_dict expected a dictionary")
    return data


def _require_string(data: dict[str, Any], field_name: str, model_name: str) -> str:
    if field_name not in data:
        raise ValueError(f"{model_name} requires '{field_name}'")
    value = data[field_name]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{model_name} {field_name} must be a non-empty string")
    return value


def _optional_string(data: dict[str, Any], field_name: str, model_name: str) -> str | None:
    value = data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{model_name} {field_name} must be a string")
    return value


def _validate_max_length(value: str, field_name: str, limit: int) -> None:
    if len(value) > limit:
        raise ValueError(f"{field_name} exceeds maximum length of {limit} characters")


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
        data = _require_mapping(data, "Skill")
        skill_id = _require_string(data, "id", "Skill")
        if not _is_safe_skill_id(skill_id):
            raise ValueError(
                "Skill id must be 1-128 safe path-free characters: "
                "alphanumeric, hyphen, underscore, dot, or slash separator"
            )
        description = data.get("description", "")
        if not isinstance(description, str):
            raise ValueError("Skill description must be a string")
        _validate_max_length(description, "Skill description", MAX_SKILL_DESCRIPTION_LENGTH)
        return cls(
            id=skill_id,
            description=description,
            input_schema=_optional_string(data, "input_schema", "Skill"),
            output_schema=_optional_string(data, "output_schema", "Skill"),
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
        has_p2p = self.peer_id or self.did_key or self.did_web or self.did_dns
        if has_p2p:
            p2p: dict[str, Any] = {}
            if self.peer_id:
                p2p["peer_id"] = self.peer_id
            if self.supported_transports:
                p2p["supported_transports"] = self.supported_transports
            if self.relay_addresses:
                p2p["relay_addresses"] = self.relay_addresses
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
        data = _require_mapping(data, "AgentCard")
        name = _require_string(data, "name", "AgentCard")
        _validate_max_length(name, "AgentCard name", MAX_AGENT_CARD_NAME_LENGTH)
        description = data.get("description", "")
        if not isinstance(description, str):
            raise ValueError("AgentCard description must be a string")
        _validate_max_length(
            description,
            "AgentCard description",
            MAX_AGENT_CARD_DESCRIPTION_LENGTH,
        )

        raw_skills = data.get("skills", [])
        if not isinstance(raw_skills, list):
            raise ValueError("AgentCard skills must be a list")
        if len(raw_skills) > MAX_SKILLS_PER_CARD:
            raise ValueError(f"AgentCard skills exceeds maximum count of {MAX_SKILLS_PER_CARD}")
        skills = [Skill.from_dict(s) for s in raw_skills]

        p2p = data.get("agentanycast", {})
        if p2p is None:
            p2p = {}
        if not isinstance(p2p, dict):
            raise ValueError("AgentCard agentanycast extension must be a dictionary")

        supported_transports = p2p.get("supported_transports", [])
        if not isinstance(supported_transports, list) or not all(
            isinstance(item, str) for item in supported_transports
        ):
            raise ValueError("AgentCard supported_transports must be a list of strings")
        relay_addresses = p2p.get("relay_addresses", [])
        if not isinstance(relay_addresses, list) or not all(
            isinstance(item, str) for item in relay_addresses
        ):
            raise ValueError("AgentCard relay_addresses must be a list of strings")
        verifiable_credentials = p2p.get("verifiable_credentials", [])
        if not isinstance(verifiable_credentials, list) or not all(
            isinstance(item, str) for item in verifiable_credentials
        ):
            raise ValueError("AgentCard verifiable_credentials must be a list of strings")

        return cls(
            name=name,
            description=description,
            version=_optional_string(data, "version", "AgentCard") or "1.0.0",
            protocol_version=_optional_string(data, "protocol_version", "AgentCard") or "a2a/0.3",
            skills=skills,
            peer_id=_optional_string(p2p, "peer_id", "AgentCard"),
            supported_transports=supported_transports,
            relay_addresses=relay_addresses,
            did_key=_optional_string(p2p, "did_key", "AgentCard"),
            did_web=_optional_string(p2p, "did_web", "AgentCard"),
            did_dns=_optional_string(p2p, "did_dns", "AgentCard"),
            verifiable_credentials=verifiable_credentials,
        )
