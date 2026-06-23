"""Structured context packets for Hermes Agency task delegation."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

PACKET_SCHEMA = "agency.context_packet.v1"
_PACKET_PREFIX = "AGENTANYCAST_CONTEXT_PACKET "


@dataclass
class ContextPacket:
    """A structured brief sent as the body of an A2A delegation task."""

    goal: str
    context: str = ""
    sender: str = ""
    channel: str = ""
    dependencies: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    validation: str = ""
    context_id: str = ""
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema: str = PACKET_SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "goal": self.goal,
            "context": self.context,
            "sender": self.sender,
            "channel": self.channel,
            "dependencies": list(self.dependencies),
            "constraints": list(self.constraints),
            "validation": self.validation,
            "context_id": self.context_id,
            "conversation_history": list(self.conversation_history),
            "metadata": dict(self.metadata),
        }


def _profile_name() -> str:
    env_profile = os.getenv("HERMES_PROFILE", "").strip()
    if env_profile:
        return env_profile
    home = Path(get_hermes_home()).expanduser()
    if home.parent.name == "profiles":
        return home.name
    return "default"


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list | tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _conversation_history_from(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    history: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        clean = {str(k): v for k, v in item.items() if v not in (None, "")}
        if clean:
            history.append(clean)
    return history


def _summarize_messages(messages: list[dict[str, Any]], *, limit: int = 6) -> str:
    snippets: list[str] = []
    for msg in messages[-limit:]:
        role = str(msg.get("role") or "unknown")
        content = msg.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("text"):
                    parts.append(str(item["text"]))
                elif isinstance(item, str):
                    parts.append(item)
            text = " ".join(parts)
        else:
            text = str(content or "")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            snippets.append(f"{role}: {text[:500]}")
    return "\n".join(snippets)


def _context_from(conversation_context: Any) -> str:
    if conversation_context is None:
        return ""
    if isinstance(conversation_context, str):
        return conversation_context.strip()
    if isinstance(conversation_context, list):
        if all(isinstance(item, dict) for item in conversation_context):
            return _summarize_messages(conversation_context)  # type: ignore[arg-type]
        return "\n".join(str(item) for item in conversation_context if str(item).strip())
    if isinstance(conversation_context, dict):
        if isinstance(conversation_context.get("summary"), str):
            return conversation_context["summary"].strip()
        if isinstance(conversation_context.get("conversation_history"), list):
            return _summarize_messages(conversation_context["conversation_history"])
        if isinstance(conversation_context.get("messages"), list):
            return _summarize_messages(conversation_context["messages"])
        metadata = conversation_context.get("metadata")
        if isinstance(metadata, dict) and metadata:
            pairs = [
                f"{key}: {value}" for key, value in metadata.items() if value not in (None, "")
            ]
            return "\n".join(pairs)
    return str(conversation_context).strip()


def _channel_from(conversation_context: Any) -> str:
    if not isinstance(conversation_context, dict):
        return ""
    for key in ("channel", "channel_id", "thread_id", "platform", "source"):
        value = conversation_context.get(key)
        if value:
            return str(value)
    metadata = conversation_context.get("metadata")
    if isinstance(metadata, dict):
        platform = metadata.get("platform") or metadata.get("source")
        channel = metadata.get("channel") or metadata.get("channel_id") or metadata.get("thread_id")
        if platform and channel:
            return f"{platform}:{channel}"
        if channel:
            return str(channel)
        if platform:
            return str(platform)
    return ""


def build_context_packet(message: str, conversation_context: Any = None) -> dict[str, Any] | str:
    """Build a structured A2A task packet.

    On unexpected failure this function returns the bare message, matching the
    Phase 1 fail-open requirement.
    """

    try:
        goal = str(message or "").strip()
        if not goal:
            return message
        ctx = conversation_context if isinstance(conversation_context, dict) else {}
        packet = ContextPacket(
            goal=goal,
            context=_context_from(conversation_context),
            sender=str(ctx.get("sender") or ctx.get("profile") or _profile_name()).strip(),
            channel=_channel_from(conversation_context),
            dependencies=_as_list(ctx.get("dependencies")),
            constraints=_as_list(ctx.get("constraints")),
            validation=str(ctx.get("validation") or "").strip(),
            context_id=str(ctx.get("context_id") or "").strip(),
            conversation_history=_conversation_history_from(ctx.get("conversation_history")),
            metadata={str(k): v for k, v in (ctx.get("metadata") or {}).items()}
            if isinstance(ctx.get("metadata"), dict)
            else {},
        )
        return packet.as_dict()
    except Exception:
        return message


def packet_to_message_text(packet_or_message: dict[str, Any] | str) -> str:
    """Serialize a packet for transport as an Hermes Agency text part."""

    if isinstance(packet_or_message, dict):
        return _PACKET_PREFIX + json.dumps(packet_or_message, ensure_ascii=False, sort_keys=True)
    return str(packet_or_message)


def parse_context_packet(text: str) -> dict[str, Any] | None:
    """Parse a context packet from an incoming A2A text part, if present."""

    raw = (text or "").strip()
    if raw.startswith(_PACKET_PREFIX):
        raw = raw[len(_PACKET_PREFIX) :].strip()
    elif not raw.startswith("{"):
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, dict) and data.get("schema") == PACKET_SCHEMA:
        return data
    return None


def packet_goal_or_text(text: str) -> str:
    """Return the packet goal when text contains a packet; otherwise raw text."""

    packet = parse_context_packet(text)
    if packet:
        return str(packet.get("goal") or text)
    return text
