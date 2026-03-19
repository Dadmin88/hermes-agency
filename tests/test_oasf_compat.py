"""Tests for OASF (Open Agentic Schema Framework) compatibility."""

from agentanycast.card import AgentCard, Skill
from agentanycast.compat.oasf import (
    card_from_oasf_record,
    card_to_oasf_record,
    skill_from_oasf,
    skill_to_oasf,
)

# ---------------------------------------------------------------------------
# Skill conversion
# ---------------------------------------------------------------------------


class TestSkillToOASF:
    def test_simple_skill(self):
        skill = Skill(id="get_weather", description="Get current weather")
        result = skill_to_oasf(skill)
        assert result == {"name": "get_weather"}

    def test_hierarchical_skill(self):
        skill = Skill(id="natural_language_processing/text_completion")
        result = skill_to_oasf(skill)
        assert result == {"name": "natural_language_processing/text_completion"}


class TestSkillFromOASF:
    def test_with_name_and_description(self):
        oasf = {"name": "agent_orchestration/task_decomposition", "id": 2001}
        skill = skill_from_oasf(oasf)
        assert skill.id == "agent_orchestration/task_decomposition"

    def test_minimal_entry(self):
        skill = skill_from_oasf({})
        assert skill.id == ""
        assert skill.description == ""

    def test_with_description(self):
        oasf = {"name": "echo", "description": "Echo input back"}
        skill = skill_from_oasf(oasf)
        assert skill.id == "echo"
        assert skill.description == "Echo input back"


# ---------------------------------------------------------------------------
# card_to_oasf_record
# ---------------------------------------------------------------------------


class TestCardToOASFRecord:
    def _make_card(self, **overrides) -> AgentCard:
        defaults = {
            "name": "TestAgent",
            "description": "A test agent",
            "version": "2.0.0",
            "skills": [Skill(id="echo", description="Echo input")],
            "peer_id": "12D3KooWExample",
            "did_key": "key:z6MkExample",
        }
        defaults.update(overrides)
        return AgentCard(**defaults)

    def test_basic_fields(self):
        card = self._make_card()
        record = card_to_oasf_record(card)
        assert record["name"] == "TestAgent"
        assert record["description"] == "A test agent"
        assert record["version"] == "2.0.0"
        assert record["schema_version"] == "1.0.0"
        assert "created_at" in record

    def test_skills_mapped(self):
        card = self._make_card(
            skills=[
                Skill(id="nlp/text_completion"),
                Skill(id="echo"),
            ]
        )
        record = card_to_oasf_record(card)
        assert len(record["skills"]) == 2
        assert record["skills"][0] == {"name": "nlp/text_completion"}
        assert record["skills"][1] == {"name": "echo"}

    def test_a2a_module_embedded(self):
        card = self._make_card()
        record = card_to_oasf_record(card)
        modules = record["modules"]
        assert len(modules) == 1
        a2a = modules[0]
        assert a2a["name"] == "a2a"
        assert a2a["id"] == 3
        assert "card_data" in a2a["data"]
        assert a2a["data"]["card_data"]["name"] == "TestAgent"
        assert "card_schema_version" in a2a["data"]

    def test_p2p_locator(self):
        card = self._make_card()
        record = card_to_oasf_record(card)
        urls = [u for loc in record["locators"] for u in loc.get("urls", [])]
        assert "p2p://12D3KooWExample" in urls

    def test_did_locator(self):
        card = self._make_card()
        record = card_to_oasf_record(card)
        urls = [u for loc in record["locators"] for u in loc.get("urls", [])]
        assert "did:key:z6MkExample" in urls

    def test_no_locators_without_peer_id_and_did(self):
        card = self._make_card(peer_id=None, did_key=None)
        record = card_to_oasf_record(card)
        assert record["locators"] == []

    def test_custom_authors_and_domains(self):
        card = self._make_card()
        record = card_to_oasf_record(
            card,
            authors=["Alice <alice@example.com>"],
            domains=[{"name": "hospitality_and_tourism/tourism_management", "id": 1505}],
        )
        assert record["authors"] == ["Alice <alice@example.com>"]
        assert len(record["domains"]) == 1
        assert record["domains"][0]["id"] == 1505

    def test_version_override(self):
        card = self._make_card(version="2.0.0")
        record = card_to_oasf_record(card, version="3.0.0")
        assert record["version"] == "3.0.0"

    def test_default_version_from_card(self):
        card = self._make_card(version="")
        record = card_to_oasf_record(card)
        assert record["version"] == "1.0.0"


# ---------------------------------------------------------------------------
# card_from_oasf_record — with A2A module
# ---------------------------------------------------------------------------


class TestCardFromOASFWithModule:
    def test_extracts_from_a2a_module(self):
        record = {
            "name": "RecordName",
            "modules": [
                {
                    "name": "a2a",
                    "id": 3,
                    "data": {
                        "card_data": {
                            "name": "CardName",
                            "description": "From module",
                            "version": "2.0.0",
                            "protocol_version": "a2a/0.3",
                            "skills": [{"id": "echo", "description": "Echo"}],
                        },
                    },
                },
            ],
            "locators": [
                {"type": "url", "urls": ["p2p://12D3KooWFromLocator"]},
            ],
        }
        card = card_from_oasf_record(record)
        assert card.name == "CardName"  # from module, not record-level
        assert card.description == "From module"
        assert card.peer_id == "12D3KooWFromLocator"

    def test_module_matched_by_id(self):
        """Module can be matched by numeric id instead of name."""
        record = {
            "modules": [
                {
                    "name": "something_else",
                    "id": 3,
                    "data": {
                        "card_data": {
                            "name": "MatchedByID",
                            "skills": [],
                        },
                    },
                },
            ],
        }
        card = card_from_oasf_record(record)
        assert card.name == "MatchedByID"

    def test_did_key_from_locator(self):
        record = {
            "modules": [
                {
                    "name": "a2a",
                    "id": 3,
                    "data": {
                        "card_data": {"name": "WithDID", "skills": []},
                    },
                },
            ],
            "locators": [
                {"type": "url", "urls": ["did:key:z6MkTest"]},
            ],
        }
        card = card_from_oasf_record(record)
        assert card.did_key == "key:z6MkTest"


# ---------------------------------------------------------------------------
# card_from_oasf_record — fallback (no A2A module)
# ---------------------------------------------------------------------------


class TestCardFromOASFFallback:
    def test_constructs_from_record_fields(self):
        record = {
            "name": "FallbackAgent",
            "description": "Built from record fields",
            "version": "1.5.0",
            "skills": [
                {"name": "nlp/summarization", "id": 1002},
                {"name": "echo"},
            ],
            "locators": [
                {"type": "url", "urls": ["p2p://12D3KooWFallback"]},
            ],
        }
        card = card_from_oasf_record(record)
        assert card.name == "FallbackAgent"
        assert card.description == "Built from record fields"
        assert card.version == "1.5.0"
        assert len(card.skills) == 2
        assert card.skills[0].id == "nlp/summarization"
        assert card.peer_id == "12D3KooWFallback"

    def test_empty_record(self):
        card = card_from_oasf_record({})
        assert card.name == ""
        assert card.skills == []
        assert card.peer_id is None

    def test_no_modules_key(self):
        record = {"name": "NoModules", "skills": []}
        card = card_from_oasf_record(record)
        assert card.name == "NoModules"

    def test_empty_module_data_falls_back(self):
        """If the a2a module exists but card_data is missing, fall back."""
        record = {
            "name": "EmptyModule",
            "modules": [{"name": "a2a", "id": 3, "data": {}}],
            "skills": [{"name": "test_skill"}],
        }
        card = card_from_oasf_record(record)
        assert card.name == "EmptyModule"
        assert len(card.skills) == 1


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_card_survives_round_trip(self):
        original = AgentCard(
            name="RoundTripAgent",
            description="Tests round-trip conversion",
            version="3.0.0",
            skills=[
                Skill(id="nlp/text_completion", description="Complete text"),
                Skill(id="echo", description="Echo back"),
            ],
            peer_id="12D3KooWRoundTrip",
            did_key="key:z6MkRoundTrip",
        )
        record = card_to_oasf_record(original, authors=["Test <t@t.com>"])
        restored = card_from_oasf_record(record)

        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.version == original.version
        assert restored.peer_id == original.peer_id
        assert restored.did_key == original.did_key
        assert len(restored.skills) == len(original.skills)
        for orig_s, rest_s in zip(original.skills, restored.skills):
            assert rest_s.id == orig_s.id
            assert rest_s.description == orig_s.description

    def test_card_without_p2p_round_trip(self):
        original = AgentCard(name="PlainAgent", skills=[Skill(id="hello")])
        record = card_to_oasf_record(original)
        restored = card_from_oasf_record(record)
        assert restored.name == original.name
        assert restored.peer_id is None
        assert restored.did_key is None
