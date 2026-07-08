"""Agent card models compatible with AgentAnycast / A2A."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Skill:
    id: str
    description: str = ""
    input_schema: str | None = None
    output_schema: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "description": self.description}
        if self.input_schema:
            data["input_schema"] = self.input_schema
        if self.output_schema:
            data["output_schema"] = self.output_schema
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        if not isinstance(data, dict):
            raise ValueError("Skill.from_dict expected a dictionary")
        skill_id = data.get("id")
        if not isinstance(skill_id, str) or not skill_id:
            raise ValueError("Skill requires non-empty id")
        description = data.get("description", "")
        if not isinstance(description, str):
            raise ValueError("Skill description must be a string")
        return cls(
            id=skill_id,
            description=description,
            input_schema=data.get("input_schema"),
            output_schema=data.get("output_schema"),
        )


@dataclass
class AgentCard:
    name: str
    description: str = ""
    version: str = "1.0.0"
    protocol_version: str = "a2a/0.3"
    skills: list[Skill] = field(default_factory=list)
    peer_id: str | None = None
    did_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "protocol_version": self.protocol_version,
            "skills": [skill.to_dict() for skill in self.skills],
        }
        if self.peer_id or self.did_key:
            payload["agentanycast"] = {
                **({"peer_id": self.peer_id} if self.peer_id else {}),
                **({"did_key": self.did_key} if self.did_key else {}),
            }
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCard:
        if not isinstance(data, dict):
            raise ValueError("AgentCard.from_dict expected a dictionary")
        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("AgentCard requires non-empty name")
        raw_skills = data.get("skills", [])
        if not isinstance(raw_skills, list):
            raise ValueError("AgentCard skills must be a list")
        skills = [Skill.from_dict(item) for item in raw_skills]
        p2p = data.get("agentanycast") or {}
        if p2p and not isinstance(p2p, dict):
            raise ValueError("AgentCard agentanycast extension must be a dictionary")
        return cls(
            name=name,
            description=data.get("description", "") if isinstance(data.get("description", ""), str) else "",
            version=data.get("version", "1.0.0"),
            protocol_version=data.get("protocol_version", "a2a/0.3"),
            skills=skills,
            peer_id=p2p.get("peer_id") if isinstance(p2p.get("peer_id"), str) else None,
            did_key=p2p.get("did_key") if isinstance(p2p.get("did_key"), str) else None,
        )