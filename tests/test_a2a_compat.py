"""Tests for A2A v1.0 compatibility layer (agentanycast.compat.a2a_v1)."""

from datetime import datetime, timezone

from agentanycast.card import AgentCard, Skill  # noqa: F401
from agentanycast.compat.a2a_v1 import (
    card_from_a2a_json,
    card_to_a2a_json,
    message_from_a2a_json,
    message_to_a2a_json,
    skill_from_a2a_json,
    skill_to_a2a_json,
    task_from_a2a_json,
    task_to_a2a_json,
)
from agentanycast.task import Artifact, Message, Part, Task, TaskStatus

# ── Part round-trip ──────────────────────────────────────────


class TestPartConversion:
    def test_text_part_roundtrip(self):
        task = Task(
            task_id="t1",
            messages=[Message(role="user", parts=[Part(text="hello")])],
        )
        json_data = task_to_a2a_json(task)
        restored = task_from_a2a_json(json_data)
        assert restored.messages[0].parts[0].text == "hello"

    def test_data_part_roundtrip(self):
        task = Task(
            task_id="t2",
            messages=[Message(role="agent", parts=[Part(data={"key": "value"})])],
        )
        json_data = task_to_a2a_json(task)
        restored = task_from_a2a_json(json_data)
        assert restored.messages[0].parts[0].data == {"key": "value"}

    def test_url_part_roundtrip(self):
        task = Task(
            task_id="t3",
            messages=[
                Message(
                    role="user",
                    parts=[Part(url="https://example.com/doc.pdf", media_type="application/pdf")],
                )
            ],
        )
        json_data = task_to_a2a_json(task)
        restored = task_from_a2a_json(json_data)
        part = restored.messages[0].parts[0]
        assert part.url == "https://example.com/doc.pdf"
        assert part.media_type == "application/pdf"

    def test_raw_part_roundtrip(self):
        task = Task(
            task_id="t4",
            messages=[Message(role="user", parts=[Part(raw=b"\x00\xff\x42")])],
        )
        json_data = task_to_a2a_json(task)
        restored = task_from_a2a_json(json_data)
        assert restored.messages[0].parts[0].raw == b"\x00\xff\x42"


# ── Message conversion ───────────────────────────────────────


class TestMessageConversion:
    def test_basic_roundtrip(self):
        msg = Message(role="user", parts=[Part(text="analyze this")], message_id="msg-1")
        json_data = message_to_a2a_json(msg)
        assert json_data["role"] == "user"
        assert json_data["messageId"] == "msg-1"
        assert json_data["parts"][0]["text"] == "analyze this"

        restored = message_from_a2a_json(json_data)
        assert restored.role == "user"
        assert restored.message_id == "msg-1"
        assert restored.parts[0].text == "analyze this"

    def test_empty_message_id_omitted(self):
        msg = Message(role="agent", parts=[Part(text="done")])
        json_data = message_to_a2a_json(msg)
        assert "messageId" not in json_data

    def test_parse_with_extra_a2a_fields(self):
        """A2A v1.0 messages may have context_id, extensions, etc."""
        data = {
            "role": "agent",
            "parts": [{"type": "text", "text": "result"}],
            "messageId": "m-99",
            "contextId": "ctx-1",
            "taskId": "task-1",
            "extensions": {"custom": True},
            "referenceTaskIds": ["task-0"],
        }
        msg = message_from_a2a_json(data)
        assert msg.role == "agent"
        assert msg.message_id == "m-99"
        assert msg.parts[0].text == "result"


# ── Task conversion ──────────────────────────────────────────


class TestTaskConversion:
    def test_full_roundtrip(self):
        task = Task(
            task_id="task-abc",
            context_id="ctx-1",
            status=TaskStatus.WORKING,
            messages=[
                Message(role="user", parts=[Part(text="analyze Q4 sales")]),
                Message(role="agent", parts=[Part(text="working on it...")]),
            ],
            artifacts=[
                Artifact(
                    artifact_id="art-1",
                    name="report",
                    parts=[Part(data={"revenue": 1000})],
                ),
            ],
            updated_at=datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        )
        json_data = task_to_a2a_json(task)

        assert json_data["id"] == "task-abc"
        assert json_data["contextId"] == "ctx-1"
        assert json_data["status"]["state"] == "working"
        assert "2026-01-15" in json_data["status"]["timestamp"]
        assert len(json_data["history"]) == 2
        assert len(json_data["artifacts"]) == 1

        restored = task_from_a2a_json(json_data)
        assert restored.task_id == "task-abc"
        assert restored.context_id == "ctx-1"
        assert restored.status == TaskStatus.WORKING
        assert len(restored.messages) == 2
        assert restored.messages[0].parts[0].text == "analyze Q4 sales"
        assert len(restored.artifacts) == 1
        assert restored.artifacts[0].name == "report"

    def test_minimal_task(self):
        task = Task(task_id="t-min", status=TaskStatus.SUBMITTED)
        json_data = task_to_a2a_json(task)
        assert json_data["id"] == "t-min"
        assert json_data["status"]["state"] == "submitted"
        assert "contextId" not in json_data
        assert "history" not in json_data
        assert "artifacts" not in json_data

        restored = task_from_a2a_json(json_data)
        assert restored.task_id == "t-min"
        assert restored.status == TaskStatus.SUBMITTED

    def test_p2p_fields_stripped(self):
        """P2P-only fields should not appear in A2A v1.0 JSON."""
        task = Task(
            task_id="t-p2p",
            target_skill_id="weather",
            originator_peer_id="12D3KooWPeer123",
        )
        json_data = task_to_a2a_json(task)
        assert "target_skill_id" not in json_data
        assert "originator_peer_id" not in json_data

    def test_all_status_values(self):
        for status in TaskStatus:
            task = Task(task_id="t-status", status=status)
            json_data = task_to_a2a_json(task)
            restored = task_from_a2a_json(json_data)
            assert restored.status == status

    def test_parse_auth_required_state(self):
        """A2A v1.0 has auth-required; we map it to INPUT_REQUIRED."""
        data = {
            "id": "t-auth",
            "status": {"state": "auth-required"},
        }
        task = task_from_a2a_json(data)
        assert task.status == TaskStatus.INPUT_REQUIRED


# ── Skill conversion ─────────────────────────────────────────


class TestSkillConversion:
    def test_basic_roundtrip(self):
        skill = Skill(id="weather", description="Get weather forecasts")
        json_data = skill_to_a2a_json(skill)
        assert json_data["id"] == "weather"
        assert json_data["name"] == "Get weather forecasts"
        assert json_data["description"] == "Get weather forecasts"

        restored = skill_from_a2a_json(json_data)
        assert restored.id == "weather"
        assert restored.description == "Get weather forecasts"

    def test_with_schemas(self):
        skill = Skill(
            id="translate",
            description="Translate text",
            input_schema="text/plain",
            output_schema="text/plain",
        )
        json_data = skill_to_a2a_json(skill)
        assert json_data["inputModes"] == ["text/plain"]
        assert json_data["outputModes"] == ["text/plain"]

        restored = skill_from_a2a_json(json_data)
        assert restored.input_schema == "text/plain"
        assert restored.output_schema == "text/plain"

    def test_parse_a2a_skill_with_tags_and_examples(self):
        """A2A v1.0 AgentSkill has tags and examples we don't model."""
        data = {
            "id": "summarize",
            "name": "Summarize Documents",
            "description": "Summarize long documents into key points",
            "tags": ["nlp", "summarization"],
            "examples": ["Summarize this PDF"],
            "inputModes": ["application/pdf"],
            "outputModes": ["text/plain"],
        }
        skill = skill_from_a2a_json(data)
        assert skill.id == "summarize"
        assert skill.description == "Summarize long documents into key points"
        assert skill.input_schema == "application/pdf"
        assert skill.output_schema == "text/plain"

    def test_empty_description_uses_id_as_name(self):
        skill = Skill(id="ping")
        json_data = skill_to_a2a_json(skill)
        assert json_data["name"] == "ping"


# ── AgentCard conversion ─────────────────────────────────────


class TestCardConversion:
    def test_basic_roundtrip(self):
        card = AgentCard(
            name="WeatherBot",
            description="Provides weather forecasts",
            version="2.0.0",
            skills=[
                Skill(id="weather", description="Get weather"),
                Skill(id="forecast", description="Get 5-day forecast"),
            ],
        )
        json_data = card_to_a2a_json(card)
        assert json_data["name"] == "WeatherBot"
        assert json_data["description"] == "Provides weather forecasts"
        assert json_data["version"] == "2.0.0"
        assert len(json_data["skills"]) == 2

        restored = card_from_a2a_json(json_data)
        assert restored.name == "WeatherBot"
        assert restored.version == "2.0.0"
        assert len(restored.skills) == 2
        assert restored.skills[0].id == "weather"

    def test_p2p_extension_stripped(self):
        """P2P extension fields should not appear in A2A v1.0 JSON."""
        card = AgentCard(
            name="P2PBot",
            peer_id="12D3KooWTest",
            did_key="did:key:z6Mk...",
            relay_addresses=["/ip4/1.2.3.4/tcp/4001"],
            supported_transports=["libp2p"],
        )
        json_data = card_to_a2a_json(card)
        assert "peer_id" not in json_data
        assert "agentanycast" not in json_data
        assert "did_key" not in json_data

    def test_url_included_when_provided(self):
        card = AgentCard(name="Bot")
        json_data = card_to_a2a_json(card, url="https://bot.example.com/.well-known/agent.json")
        assert json_data["url"] == "https://bot.example.com/.well-known/agent.json"

    def test_url_omitted_when_empty(self):
        card = AgentCard(name="Bot")
        json_data = card_to_a2a_json(card)
        assert "url" not in json_data

    def test_parse_official_a2a_card(self):
        """Parse a full A2A v1.0 Agent Card with fields we don't model."""
        data = {
            "name": "CurrencyConverter",
            "description": "Convert between currencies",
            "version": "1.0.0",
            "url": "https://converter.example.com",
            "provider": {
                "organization": "FinCorp",
                "url": "https://fincorp.example.com",
            },
            "capabilities": {
                "streaming": True,
                "pushNotifications": False,
                "stateTransitionHistory": True,
            },
            "securitySchemes": [{"type": "apiKey", "in": "header", "name": "X-API-Key"}],
            "skills": [
                {
                    "id": "convert",
                    "name": "Currency Conversion",
                    "description": "Convert an amount from one currency to another",
                    "tags": ["finance", "currency"],
                    "examples": ["Convert 100 USD to EUR"],
                    "inputModes": ["application/json"],
                    "outputModes": ["application/json"],
                },
            ],
            "signatures": {"keyId": "key-1"},
        }
        card = card_from_a2a_json(data)
        assert card.name == "CurrencyConverter"
        assert card.description == "Convert between currencies"
        assert len(card.skills) == 1
        assert card.skills[0].id == "convert"
        assert card.skills[0].description == "Convert an amount from one currency to another"

    def test_parse_card_with_no_skills(self):
        data = {"name": "EmptyBot", "description": "Does nothing"}
        card = card_from_a2a_json(data)
        assert card.name == "EmptyBot"
        assert card.skills == []


# ── Edge cases and missing fields ────────────────────────────


class TestEdgeCases:
    def test_task_missing_optional_fields(self):
        """Parsing JSON with only required fields should not raise."""
        data = {"id": "t-bare"}
        task = task_from_a2a_json(data)
        assert task.task_id == "t-bare"
        assert task.status == TaskStatus.SUBMITTED
        assert task.messages == []
        assert task.artifacts == []

    def test_message_missing_parts(self):
        data = {"role": "user"}
        msg = message_from_a2a_json(data)
        assert msg.role == "user"
        assert msg.parts == []

    def test_part_with_unknown_type(self):
        """Unknown part types should produce an empty Part rather than crash."""
        data = {"type": "custom_widget", "widget_data": "foo"}
        from agentanycast.compat.a2a_v1 import _part_from_a2a_json

        part = _part_from_a2a_json(data)
        assert part.text is None
        assert part.data is None

    def test_task_status_unknown_state(self):
        """Unknown state strings should default to SUBMITTED."""
        data = {"id": "t-unk", "status": {"state": "future_state_42"}}
        task = task_from_a2a_json(data)
        assert task.status == TaskStatus.SUBMITTED

    def test_task_status_timestamp_parsing(self):
        data = {
            "id": "t-ts",
            "status": {
                "state": "completed",
                "timestamp": "2026-03-15T10:00:00+00:00",
            },
        }
        task = task_from_a2a_json(data)
        assert task.status == TaskStatus.COMPLETED
        assert task.updated_at is not None
        assert task.updated_at.year == 2026

    def test_task_status_invalid_timestamp(self):
        """Invalid timestamps should be ignored, not crash."""
        data = {
            "id": "t-bad-ts",
            "status": {"state": "working", "timestamp": "not-a-date"},
        }
        task = task_from_a2a_json(data)
        assert task.status == TaskStatus.WORKING
        assert task.updated_at is None

    def test_artifact_camelcase_fields(self):
        """A2A v1.0 uses camelCase (artifactId)."""
        data = {
            "id": "t-art",
            "status": {"state": "completed"},
            "artifacts": [
                {
                    "artifactId": "art-99",
                    "name": "output",
                    "parts": [{"type": "text", "text": "done"}],
                }
            ],
        }
        task = task_from_a2a_json(data)
        assert task.artifacts[0].artifact_id == "art-99"
        assert task.artifacts[0].name == "output"

    def test_card_default_version(self):
        data = {"name": "NoVersion"}
        card = card_from_a2a_json(data)
        assert card.version == "1.0.0"
