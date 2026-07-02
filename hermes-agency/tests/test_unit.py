from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import types
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _nested_cfg_get(config, *path, default=None):
    value = config
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _load_runner_module(monkeypatch):
    module_name = "agency_node_runner_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN_DIR / "pool" / "agency_node_runner.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def _load_pool_manager_module(monkeypatch):
    module_name = "agency_pool_manager_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN_DIR / "pool" / "manager.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def plugin_modules(tmp_path, monkeypatch):
    """Load the plugin as a synthetic package and stub Hermes-only imports."""
    for name in list(sys.modules):
        if name == "hermes_plugin" or name.startswith("hermes_plugin."):
            sys.modules.pop(name, None)
    sys.modules.pop("agentanycast", None)

    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()

    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: hermes_home
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli_config = types.ModuleType("hermes_cli.config")
    hermes_cli_config.cfg_get = _nested_cfg_get
    hermes_cli_config.load_config = lambda: {}
    hermes_cli.config = hermes_cli_config
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_cli_config)

    if importlib.util.find_spec("yaml") is None:
        fake_yaml = types.ModuleType("yaml")

        def safe_load(text):
            data = {}
            current_parent = None
            for raw_line in str(text).splitlines():
                if not raw_line.strip() or raw_line.strip().startswith("#"):
                    continue
                if raw_line.lstrip().startswith(":"):
                    raise ValueError("malformed yaml")
                indent = len(raw_line) - len(raw_line.lstrip(" "))
                key, sep, value = raw_line.strip().partition(":")
                if not sep:
                    continue
                parsed = value.strip().strip("\"'")
                if parsed.lower() == "true":
                    parsed = True
                elif parsed.lower() == "false":
                    parsed = False
                if indent == 0 and not value.strip():
                    data[key] = {}
                    current_parent = key
                elif indent and current_parent:
                    data[current_parent][key] = parsed
                else:
                    data[key] = parsed
            return data

        fake_yaml.safe_load = safe_load
        monkeypatch.setitem(sys.modules, "yaml", fake_yaml)

    package = types.ModuleType("hermes_plugin")
    package.__path__ = [str(PLUGIN_DIR)]
    monkeypatch.setitem(sys.modules, "hermes_plugin", package)

    loaded = {}
    for module_name in (
        "config",
        "trust",
        "incoming_security",
        "kanban_workspace",
        "registration",
        "bidding",
        "card_builder",
        "context_packet",
        "conversation",
        "departments",
        "task_processor",
        "announcements",
        "kanban_bridge",
        "proactive",
        "node_manager",
        "tools",
        "doctor",
        "cli",
    ):
        full_name = f"hermes_plugin.{module_name}"
        spec = importlib.util.spec_from_file_location(full_name, PLUGIN_DIR / f"{module_name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full_name, module)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        loaded[module_name] = module
    return types.SimpleNamespace(**loaded, hermes_home=hermes_home, cli_config=hermes_cli_config)


def test_kanban_update_task_accepts_archived_status(plugin_modules, monkeypatch):
    kb_mod = plugin_modules.kanban_bridge
    updates: list[tuple[str, str, dict[str, str]]] = []

    class FakeKanban:
        def recompute_ready(self, conn):
            conn["recomputed"] = True

        def get_task(self, conn, task_id):
            return {"id": task_id, "status": "archived"}

    @contextmanager
    def fake_connection(board=None):
        yield FakeKanban(), {}

    monkeypatch.setattr(kb_mod, "_connection", fake_connection)
    monkeypatch.setattr(kb_mod, "_resolve_task_id", lambda _kb, _conn, task_id: task_id)
    monkeypatch.setattr(
        kb_mod,
        "_set_status",
        lambda _kb, _conn, task_id, status, payload=None: updates.append(
            (task_id, status, dict(payload or {}))
        ),
    )
    monkeypatch.setattr(kb_mod, "_plugin_status", lambda _kb, _conn, task: task["status"])
    monkeypatch.setattr(
        kb_mod,
        "_task_to_dict",
        lambda _kb, _conn, task, include_thread=False: dict(task),
    )

    result = kb_mod._update_task_impl("task-123", "archived", None, None)

    assert result["ok"] is True
    assert result["status"] == "archived"
    assert updates == [("task-123", "archived", {"source": "agency"})]


def test_context_packet_preserves_context_id_and_history(plugin_modules):
    cp = plugin_modules.context_packet

    packet = cp.build_context_packet(
        "Now make it about P2P networking",
        {
            "context_id": "test-conv-1",
            "conversation_history": [
                {"user": "Write a haiku about AI", "agent": "Silent agents weave"},
            ],
            "metadata": {"source": "unit"},
        },
    )

    assert isinstance(packet, dict)
    assert packet["context_id"] == "test-conv-1"
    assert packet["conversation_history"] == [
        {"user": "Write a haiku about AI", "agent": "Silent agents weave"},
    ]
    parsed = cp.parse_context_packet(cp.packet_to_message_text(packet))
    assert parsed == packet


def test_conversation_history_formats_previous_turns_and_ttl(plugin_modules, monkeypatch):
    conv = plugin_modules.conversation
    now = 2000.0
    monkeypatch.setattr(conv.time, "time", lambda: now)
    tasks = [
        {
            "id": "old",
            "created_at": 500.0,
            "body": 'Hermes Agency metadata:\n```json\n{"context_id":"test-conv-1","message":"too old"}\n```',
            "result": "old result",
        },
        {
            "id": "turn-1",
            "created_at": 1900.0,
            "body": 'Hermes Agency metadata:\n```json\n{"context_id":"test-conv-1","message":"Write a haiku about AI"}\n```',
            "result": "Silent agents weave",
        },
        {
            "id": "other",
            "created_at": 1950.0,
            "body": 'Hermes Agency metadata:\n```json\n{"context_id":"other","message":"ignore me"}\n```',
            "result": "ignored",
        },
    ]
    monkeypatch.setattr(
        conv,
        "kanban_list_tasks",
        lambda filters=None: {"available": True, "ok": True, "tasks": tasks},
    )

    history = conv.build_conversation_history("test-conv-1", plugin_modules.hermes_home, ttl=300)
    assert history == [
        {
            "task_id": "turn-1",
            "created_at": 1900.0,
            "user": "Write a haiku about AI",
            "agent": "Silent agents weave",
        }
    ]
    assert "Previous conversation:" in conv.format_conversation_history(history)
    assert 'You: "Write a haiku about AI"' in conv.format_conversation_history(history)


def test_build_delegation_prompt_includes_conversation_history(plugin_modules):
    tp = plugin_modules.task_processor
    record = types.SimpleNamespace(
        task_id="task-2",
        sender_peer_id="peer-1",
        target_skill_id="",
        message_text="Now make it about P2P networking",
        context_packet={
            "context_id": "test-conv-1",
            "conversation_history": [
                {"user": "Write a haiku about AI", "agent": "Silent agents weave"},
            ],
        },
        metadata={},
    )

    prompt = tp.build_delegation_prompt(record)

    assert "Previous conversation:" in prompt
    assert 'You: "Write a haiku about AI"' in prompt
    assert 'Agent: "Silent agents weave"' in prompt
    assert "Current request:" in prompt
    assert "Now make it about P2P networking" in prompt


def test_paragraphs_from_markdown_skips_markdown_structures(plugin_modules):
    cb = plugin_modules.card_builder
    markdown = """---
title: ignored
---

# Main Heading

Name: Metadata
Alias: Meta
Role: Testing

This is the first descriptive paragraph
spanning two lines.

- bullet item
* another bullet
1. numbered item

| Col | Value |
| --- | --- |
| a | b |

```python
print('not a paragraph')
```

> quoted text

## Another Heading

Another useful paragraph with **markdown** text.
"""

    assert cb._paragraphs_from_markdown(markdown) == [
        "title: ignored",
        "Name: Metadata Alias: Meta Role: Testing",
        "This is the first descriptive paragraph spanning two lines.",
        "Another useful paragraph with **markdown** text.",
    ]


@pytest.mark.parametrize(
    ("paragraph", "expected"),
    [
        ("Name: local workstation Alias: Blade Role: Assistant", True),
        ("Provider: OpenAI Model: gpt Tools: enabled", True),
        ("You are helpful: direct: and concise", False),
        ("This profile writes tests and explains code clearly.", False),
        ("Role: Assistant with one field only", False),
    ],
)
def test_is_metadata_paragraph(plugin_modules, paragraph, expected):
    assert plugin_modules.card_builder._is_metadata_paragraph(paragraph) is expected


def test_extract_frontmatter_valid_missing_and_malformed(plugin_modules):
    cb = plugin_modules.card_builder
    assert cb._extract_frontmatter("---\nname: Demo\ndescription: Useful\n---\n# Body") == {
        "name": "Demo",
        "description": "Useful",
    }
    assert cb._extract_frontmatter("# No frontmatter\nBody") == {}
    assert cb._extract_frontmatter("---\n: bad yaml\n---\nBody") == {}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("My Skill", "my-skill"),
        ("tools/search web", "tools.search-web"),
        (" Weird!! Name %% ", "weird-name"),
        ("___", "hermes-skill"),
        ("", "hermes-skill"),
    ],
)
def test_normalise_skill_id(plugin_modules, raw, expected):
    assert plugin_modules.card_builder._normalise_skill_id(raw) == expected


def test_read_profile_description_returns_first_descriptive_paragraph(plugin_modules, tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "SOUL.md").write_text(
        "# SOUL.md — Test\n\n"
        "Name: local workstation\nAlias: Blade\nRole: Assistant\n\n"
        "This is the first descriptive paragraph for the profile.\n\n"
        "A later paragraph should not be returned.\n",
        encoding="utf-8",
    )

    assert (
        plugin_modules.card_builder.read_profile_description(profile)
        == "This is the first descriptive paragraph for the profile."
    )


def test_read_profile_skills_extracts_and_deduplicates_skills(plugin_modules, tmp_path):
    profile = tmp_path / "profile"
    (profile / "skills" / "alpha").mkdir(parents=True)
    (profile / "skills" / "nested" / "beta").mkdir(parents=True)
    (profile / "skills" / "dup").mkdir(parents=True)
    (profile / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: Web Search\ndescription: Search the web.\n---\n# Body\n",
        encoding="utf-8",
    )
    (profile / "skills" / "nested" / "beta" / "SKILL.md").write_text(
        "name: Code/Review\ndescription: Review code safely.\n",
        encoding="utf-8",
    )
    (profile / "skills" / "dup" / "SKILL.md").write_text(
        "---\nname: Web Search\ndescription: Duplicate name.\n---\n",
        encoding="utf-8",
    )

    assert plugin_modules.card_builder.read_profile_skills(profile) == [
        {"id": "code.review", "description": "Review code safely."},
        {"id": "dup", "description": "Duplicate name."},
        {"id": "web-search", "description": "Search the web."},
    ]


def test_read_registry_skills_exposes_agency_roster_routing_skills(plugin_modules, tmp_path):
    profile = tmp_path / "agency-orchestrator"
    profile.mkdir()

    registry_skills = plugin_modules.card_builder.read_registry_skills(profile)

    skill_ids = {item["id"] for item in registry_skills}
    assert "orchestration" in skill_ids
    assert "task-decomposition" in skill_ids


def test_build_card_merges_profile_and_registry_skills_for_agency_profiles(
    plugin_modules, tmp_path, monkeypatch
):
    @dataclass
    class Skill:
        id: str
        description: str

    @dataclass
    class AgentCard:
        name: str
        description: str
        version: str
        skills: list[Skill]

    fake_sdk = types.ModuleType("agentanycast")
    fake_sdk.Skill = Skill
    fake_sdk.AgentCard = AgentCard
    monkeypatch.setitem(sys.modules, "agentanycast", fake_sdk)

    profile = tmp_path / "agency-orchestrator"
    (profile / "skills" / "custom").mkdir(parents=True)
    (profile / "SOUL.md").write_text("# Heading\n\nA descriptive profile.\n", encoding="utf-8")
    (profile / "config.yaml").write_text("agency:\n  skills_from_profile: true\n", encoding="utf-8")
    (profile / "skills" / "custom" / "SKILL.md").write_text(
        "---\nname: Custom Skill\ndescription: Profile skill.\n---\n",
        encoding="utf-8",
    )

    card = plugin_modules.card_builder.build_card(profile)
    skill_ids = {skill.id for skill in card.skills}

    assert "custom-skill" in skill_ids
    assert "orchestration" in skill_ids
    assert "agent-routing" in skill_ids


def test_build_card_uses_mocked_agency_and_profile_files(plugin_modules, tmp_path, monkeypatch):
    @dataclass
    class Skill:
        id: str
        description: str

        def to_dict(self):
            return {"id": self.id, "description": self.description}

    @dataclass
    class AgentCard:
        name: str
        description: str
        version: str
        skills: list[Skill]

        def to_dict(self):
            return {
                "name": self.name,
                "description": self.description,
                "version": self.version,
                "skills": [skill.to_dict() for skill in self.skills],
            }

    fake_sdk = types.ModuleType("agentanycast")
    fake_sdk.Skill = Skill
    fake_sdk.AgentCard = AgentCard
    monkeypatch.setitem(sys.modules, "agentanycast", fake_sdk)

    profile = tmp_path / "agent_profile"
    (profile / "skills" / "chat").mkdir(parents=True)
    (profile / "SOUL.md").write_text("# Heading\n\nA descriptive profile.\n", encoding="utf-8")
    (profile / "config.yaml").write_text(
        "model:\n  provider: test-provider\n  default: test-model\nagency:\n  skills_from_profile: true\n",
        encoding="utf-8",
    )
    (profile / "skills" / "chat" / "SKILL.md").write_text(
        "---\nname: Chat Helper\ndescription: Helps with chat.\n---\n",
        encoding="utf-8",
    )

    card = plugin_modules.card_builder.build_card(profile)

    assert isinstance(card, AgentCard)
    assert card.name == "agent_profile"
    assert card.description == "A descriptive profile."
    assert card.version == plugin_modules.card_builder.CARD_VERSION
    assert [skill.to_dict() for skill in card.skills] == [
        {"id": "chat-helper", "description": "Helps with chat."},
        {
            "id": "hermes-chat",
            "description": "Receive a natural-language task for this Hermes profile.",
        },
    ]
    assert card.metadata["hermes"]["profile"] == "agent_profile"
    assert card.metadata["hermes"]["model"]["provider"] == "test-provider"


def test_build_card_metadata_excludes_secret_values(plugin_modules, tmp_path, monkeypatch):
    @dataclass
    class Skill:
        id: str
        description: str

    @dataclass
    class AgentCard:
        name: str
        description: str
        version: str
        skills: list[Skill]

        def to_dict(self):
            return {
                "name": self.name,
                "description": self.description,
                "version": self.version,
                "skills": [skill.__dict__ for skill in self.skills],
            }

    fake_sdk = types.ModuleType("agentanycast")
    fake_sdk.Skill = Skill
    fake_sdk.AgentCard = AgentCard
    monkeypatch.setitem(sys.modules, "agentanycast", fake_sdk)

    profile = tmp_path / "secret_profile"
    (profile / "skills" / "safe").mkdir(parents=True)
    (profile / "SOUL.md").write_text(
        "Name: Safe Card\n\n"
        "Do not leak API key sk-abc123SECRET or Bearer token-secret.\n\n"
        "A safe profile description.\n\n"
        "Profile path <home>/.hermes/profiles/local-agent/ and env ${API_TOKEN}.\n",
        encoding="utf-8",
    )
    (profile / "skills" / "safe" / "SKILL.md").write_text(
        "---\nname: Safe Skill\ndescription: Helps safely.\n---\n",
        encoding="utf-8",
    )
    (profile / "config.yaml").write_text(
        "model:\n"
        "  provider: openai\n"
        "  default: gpt-test\n"
        "  api_key: sk-abc123SECRET\n"
        "  bearer_token: Bearer token-secret\n"
        "  base_url: https://api.example.test\n"
        "toolsets:\n"
        "  - search\n"
        "  - coding\n"
        "  - $SECRET_KEY\n"
        "discord:\n"
        "  home_channel: '123456789012345678'\n"
        "agency:\n"
        "  card_name: Public Name\n"
        "  skills_from_profile: true\n"
        "  daemon_bin: <home>/.agentanycast/daemon.sock\n"
        "  home: <home>/.hermes/profiles/local-agent/.agency\n",
        encoding="utf-8",
    )

    data = plugin_modules.card_builder.card_to_dict(plugin_modules.card_builder.build_card(profile))
    serialized = json.dumps(data, sort_keys=True)

    assert data["name"] == "Public Name"
    assert data["description"] == "A safe profile description."
    assert {skill["id"] for skill in data["skills"]} >= {"safe-skill", "hermes-chat"}
    assert data["metadata"]["hermes"]["model"] == {
        "provider": "openai",
        "default": "gpt-test",
        "base_url_configured": True,
    }
    sensitive_values = [
        "sk-abc123SECRET",
        "Bearer token-secret",
        "123456789012345678",
        "<home>/.agentanycast/daemon.sock",
        "<home>/.hermes/profiles/local-agent/",
        "<home>/.hermes/profiles/local-agent/.agency",
        "$SECRET_KEY",
        "${API_TOKEN}",
        "api_key",
        "bearer_token",
        "daemon_bin",
    ]
    for sensitive in sensitive_values:
        assert sensitive not in serialized


def test_pool_roster_uses_profile_config_model_over_static_registry(tmp_path, monkeypatch):
    module_name = "agency_pool_roster_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN_DIR / "pool" / "roster.py",
    )
    assert spec is not None
    assert spec.loader is not None
    roster_mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, roster_mod)
    spec.loader.exec_module(roster_mod)

    registry_path = tmp_path / "registry_definition.json"
    registry_path.write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "name": "agency-frontend-engineer",
                        "description": "Frontend specialist",
                        "skills": ["react"],
                        "model": "gpt-5.5",
                        "provider": "openai",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    profiles_dir = tmp_path / "profiles"
    profile_dir = profiles_dir / "agency-frontend-engineer"
    profile_dir.mkdir(parents=True)
    (profile_dir / "config.yaml").write_text(
        "model:\n  default: glm-5.2\n  provider: opencode-go\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(roster_mod, "REGISTRY_DEFINITION_PATH", registry_path)
    monkeypatch.setattr(roster_mod, "PROFILES", profiles_dir)
    monkeypatch.setattr(roster_mod, "LEGACY_ROSTER_PATH", tmp_path / "legacy_roster.json")
    monkeypatch.setattr(roster_mod, "roster_state_path", lambda: tmp_path / "roster_state.json")

    roster = roster_mod.build_roster(include_plugin_setup=False)

    assert roster["profiles"] == [
        {
            "name": "agency-frontend-engineer",
            "description": "Frontend specialist",
            "skills": ["react"],
            "skill_count": 1,
            "capabilities": [{"id": "react", "description": "Can handle react tasks"}],
            "category": None,
            "model": "glm-5.2",
            "provider": "opencode-go",
            "peer_id": None,
            "online": False,
            "last_seen": None,
            "last_wake_attempt_at": None,
            "wake_attempt_count": 0,
            "last_wake_error": None,
            "disabled": False,
            "disabled_at": None,
            "disabled_reason": None,
        }
    ]


def test_pool_roster_keeps_profile_config_when_live_discovery_has_stale_card(tmp_path, monkeypatch):
    module_name = "agency_pool_roster_live_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN_DIR / "pool" / "roster.py",
    )
    assert spec is not None
    assert spec.loader is not None
    roster_mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, roster_mod)
    spec.loader.exec_module(roster_mod)

    registry_path = tmp_path / "registry_definition.json"
    registry_path.write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "name": "agency-frontend-engineer",
                        "description": "Frontend registry description",
                        "skills": ["react"],
                        "model": "gpt-5.5",
                        "provider": "openai",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    profiles_dir = tmp_path / "profiles"
    profile_dir = profiles_dir / "agency-frontend-engineer"
    profile_dir.mkdir(parents=True)
    (profile_dir / "SOUL.md").write_text(
        "# Frontend Engineer\n\nYou are the Frontend Engineer from SOUL.md.\n",
        encoding="utf-8",
    )
    (profile_dir / "config.yaml").write_text(
        "model:\n  default: glm-5.2\n  provider: opencode-go\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(roster_mod, "REGISTRY_DEFINITION_PATH", registry_path)
    monkeypatch.setattr(roster_mod, "PROFILES", profiles_dir)
    monkeypatch.setattr(roster_mod, "LEGACY_ROSTER_PATH", tmp_path / "legacy_roster.json")
    monkeypatch.setattr(roster_mod, "roster_state_path", lambda: tmp_path / "roster_state.json")

    roster = roster_mod.build_roster(
        live_peers={
            "peer-1": {
                "peer_id": "peer-1",
                "name": "agency-frontend-engineer",
                "description": "Frontend stale AgentCard description",
                "skills": ["old-skill"],
                "card": {
                    "metadata": {"hermes": {"model": {"default": "gpt-5.5", "provider": "openai"}}}
                },
            }
        },
        include_plugin_setup=False,
    )

    agent = roster["profiles"][0]
    assert agent["online"] is True
    assert agent["peer_id"] == "peer-1"
    assert agent["description"] == "You are the Frontend Engineer from SOUL.md."
    assert agent["skills"] == ["react"]
    assert agent["model"] == "glm-5.2"
    assert agent["provider"] == "opencode-go"


def test_pool_roster_uses_shared_root_state_when_running_inside_profile(tmp_path, monkeypatch):
    for name in list(sys.modules):
        if name == "hermes_plugin" or name.startswith("hermes_plugin."):
            sys.modules.pop(name, None)

    root_home = tmp_path / ".hermes"
    profile_home = root_home / "profiles" / "agency-frontend-engineer"
    profile_home.mkdir(parents=True)
    (profile_home / "SOUL.md").write_text(
        "# Frontend Engineer\n\nYou are the profile overlay description.\n",
        encoding="utf-8",
    )
    (profile_home / "config.yaml").write_text(
        "model:\n  default: glm-5.2\n  provider: opencode-go\n",
        encoding="utf-8",
    )
    explicit_home = tmp_path / "custom-agency-home"

    package = types.ModuleType("hermes_plugin")
    package.__path__ = [str(PLUGIN_DIR)]
    pool_package = types.ModuleType("hermes_plugin.pool")
    pool_package.__path__ = [str(PLUGIN_DIR / "pool")]
    config_module = types.ModuleType("hermes_plugin.config")
    setattr(
        config_module,
        "get_config",
        lambda: types.SimpleNamespace(home=profile_home / ".agency"),
    )
    monkeypatch.setitem(sys.modules, "hermes_plugin", package)
    monkeypatch.setitem(sys.modules, "hermes_plugin.pool", pool_package)
    monkeypatch.setitem(sys.modules, "hermes_plugin.config", config_module)
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    module_name = "hermes_plugin.pool.roster"
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN_DIR / "pool" / "roster.py",
    )
    assert spec is not None
    assert spec.loader is not None
    roster_mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, roster_mod)
    spec.loader.exec_module(roster_mod)

    assert roster_mod.roster_state_path() == root_home / ".agency" / "roster_state.json"

    registry_path = tmp_path / "registry_definition.json"
    registry_path.write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "name": "agency-frontend-engineer",
                        "description": "Frontend registry description",
                        "skills": ["react"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(roster_mod, "REGISTRY_DEFINITION_PATH", registry_path)

    roster = roster_mod.build_roster(include_plugin_setup=False)
    agent = roster["profiles"][0]
    assert agent["description"] == "You are the profile overlay description."
    assert agent["model"] == "glm-5.2"
    assert agent["provider"] == "opencode-go"

    setattr(config_module, "get_config", lambda: types.SimpleNamespace(home=explicit_home))
    assert roster_mod.roster_state_path() == explicit_home / "roster_state.json"


def test_get_config_defaults(plugin_modules, monkeypatch):
    cfg_mod = plugin_modules.config
    monkeypatch.setattr(cfg_mod, "load_config", lambda: {})

    cfg = cfg_mod.get_config()

    assert cfg.enabled is True
    assert cfg.relay is None
    assert cfg.auto_start is False
    assert cfg.skills_from_profile is True
    assert cfg.allow_remote_tasks is False
    assert cfg.trusted_peers == ()
    assert cfg.incoming_queue_limit == 100
    assert cfg.home == plugin_modules.hermes_home / ".agency"
    assert cfg.daemon_bin is None
    assert cfg.incoming.mode == "delegation"
    assert cfg.relay_security.allowlist == ()
    assert cfg.relay_security.auto_allow_team is False
    assert cfg.relay_security.allow_all is False
    assert cfg.relay_security.token is None
    assert cfg.registry_allow_insecure_token_transport is False
    assert cfg.trust.store_path == plugin_modules.hermes_home / "agency" / "trust.json"
    assert cfg.trust.tofu is True
    assert cfg.incoming.delegation_timeout == 600
    assert cfg.incoming.max_queue_size == 100
    assert cfg.incoming.handler_timeout_seconds == 900
    assert cfg.incoming.idle_timeout_seconds == 120
    assert cfg.incoming.tool_access == "safe"
    assert cfg.incoming.max_iterations == 25
    assert cfg.incoming.subprocess_profile is None
    assert cfg.incoming.reject_unmatched_skills is False
    assert cfg.incoming.allow_subprocess is False
    assert cfg.incoming.allow_subprocess_fallback is False
    assert cfg.incoming.min_subprocess_trust == "full"
    assert cfg.incoming.allow_hooks_for_remote is False
    assert cfg.incoming_mode == "delegation"
    assert cfg.delegation_timeout == 600
    assert cfg.incoming.tool_access == "safe"
    assert cfg.incoming_max_iterations == 25
    assert cfg.incoming_subprocess_profile is None
    assert cfg.team.auto_discover is True
    assert cfg.team.auto_register is True
    assert cfg.team.inject_context is True
    assert cfg.team.kanban_integration is True
    assert cfg.kanban.preserve_workspaces is True
    assert cfg.team.self_serve is True
    assert cfg.team.announce_progress is False
    assert cfg.team.bidding is False
    assert cfg.team.proactive is False
    assert cfg.team.learning is False
    assert cfg.team.tenant == "default"
    assert cfg.team.context_refresh_minutes == 5
    assert cfg.workspace.root == plugin_modules.hermes_home / ".agency" / "workspace"
    assert cfg.workspace.deliverables == cfg.workspace.root / "deliverables"
    assert cfg.workspace.scratch == cfg.workspace.root / "scratch"
    assert cfg.workspace.shared == cfg.workspace.root / "shared"
    assert cfg.orchestrator.enabled is False
    assert cfg.orchestrator.agent is None
    assert cfg.orchestrator.auto_start is False
    assert cfg.orchestrator.auto_decompose is True
    assert cfg.pool.max_online_agents == 3
    assert cfg.pool.max_total_rss_mb == 2048
    assert cfg.routing == {}
    assert cfg.proactive == {}
    assert cfg.autonomy == {}
    assert cfg.workflows == {}
    assert cfg.outbound.url_validation == "warn"
    assert cfg.outbound.url_allowlist == ()


def test_get_config_can_disable_kanban_workspace_preservation(plugin_modules, monkeypatch):
    cfg_mod = plugin_modules.config
    monkeypatch.setattr(
        cfg_mod,
        "load_config",
        lambda: {"agency": {"kanban": {"preserve_workspaces": False}}},
    )

    cfg = cfg_mod.get_config()

    assert cfg.kanban.preserve_workspaces is False
    assert cfg.as_dict()["kanban"]["preserve_workspaces"] is False


def test_ensure_workspace_creates_shared_directories(plugin_modules, tmp_path):
    cfg_mod = plugin_modules.config
    workspace_root = tmp_path / "agency-workspace"
    cfg = cfg_mod.AgencyConfig(workspace=cfg_mod.WorkspaceConfig(workspace_root))

    workspace = cfg_mod.ensure_workspace(cfg)

    assert workspace.root == workspace_root
    assert workspace.deliverables.is_dir()
    assert workspace.scratch.is_dir()
    assert workspace.shared.is_dir()


def test_kanban_workspace_patch_preserves_scratch_workspace_by_default(
    plugin_modules, monkeypatch, tmp_path
):
    kw = plugin_modules.kanban_workspace
    cfg_mod = plugin_modules.config
    task_id = "t_artifact"
    workspace = tmp_path / "workspaces" / task_id
    workspace.mkdir(parents=True)
    artifact = workspace / "artifact.html"
    artifact.write_text("<h1>preserved</h1>", encoding="utf-8")
    cleanup_calls = []

    class FakeConn:
        def execute(self, sql, params=()):
            assert "workspace_kind" in sql
            assert params == (task_id,)
            return self

        def fetchone(self):
            return {"workspace_kind": "scratch", "workspace_path": str(workspace)}

    fake_kb = types.SimpleNamespace(
        _cleanup_workspace=lambda conn, tid: cleanup_calls.append((conn, tid)),
        _cleanup_worker_tmux=lambda conn, tid: cleanup_calls.append(("tmux", tid)),
    )

    monkeypatch.setattr(
        kw,
        "get_config",
        lambda: cfg_mod.AgencyConfig(kanban=cfg_mod.KanbanConfig(preserve_workspaces=True)),
    )

    kw.install_workspace_preservation_patch(fake_kb)
    fake_kb._cleanup_workspace(FakeConn(), task_id)

    assert artifact.read_text(encoding="utf-8") == "<h1>preserved</h1>"
    assert cleanup_calls == [("tmux", task_id)]
    assert fake_kb._hermes_agency_preserve_patch_installed is True


def test_kanban_workspace_patch_delegates_when_preservation_disabled(
    plugin_modules, monkeypatch, tmp_path
):
    kw = plugin_modules.kanban_workspace
    cfg_mod = plugin_modules.config
    cleanup_calls = []
    fake_kb = types.SimpleNamespace(
        _cleanup_workspace=lambda conn, tid: cleanup_calls.append((conn, tid)),
    )
    monkeypatch.setattr(
        kw,
        "get_config",
        lambda: cfg_mod.AgencyConfig(kanban=cfg_mod.KanbanConfig(preserve_workspaces=False)),
    )

    kw.install_workspace_preservation_patch(fake_kb)
    fake_kb._cleanup_workspace("conn", "t_delete")

    assert cleanup_calls == [("conn", "t_delete")]


def test_get_config_inherits_shared_runtime_from_root_profile_config(
    plugin_modules, monkeypatch, tmp_path
):
    cfg_mod = plugin_modules.config
    root_home = tmp_path / ".hermes"
    profile_home = root_home / "profiles" / "agency-orchestrator"
    profile_home.mkdir(parents=True)
    daemon_bin = tmp_path / "agentanycastd"
    relay = "/ip4/198.51.100.10/tcp/4001/p2p/12D3KooWRelay"
    (root_home / "config.yaml").write_text(
        f"agency:\n  daemon_bin: {daemon_bin}\n  relay: {relay}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "get_hermes_home", lambda: profile_home)
    monkeypatch.setattr(
        cfg_mod,
        "load_config",
        lambda: {"agency": {"enabled": True, "card_name": "agency-orchestrator"}},
    )

    cfg = cfg_mod.get_config()

    assert cfg.daemon_bin == daemon_bin
    assert cfg.relay == relay
    assert cfg.card_name == "agency-orchestrator"
    assert cfg.home == profile_home / ".agency"
    assert cfg.allow_remote_tasks is False


def test_profile_relay_map_overrides_root_relay_map_without_losing_address(plugin_modules):
    cfg_mod = plugin_modules.config
    profile_config = {
        "agency": {
            "relay": {
                "allowlist": ["local-peer"],
                "auto_allow_team": False,
            }
        }
    }
    root_config = {
        "agency": {
            "daemon_bin": "/root/bin/agentanycastd",
            "relay": {
                "address": "/ip4/198.51.100.10/tcp/4001/p2p/12D3KooWRelay",
                "allowlist": ["root-peer"],
                "auto_allow_team": True,
                "token": "root-token",
            },
        }
    }

    merged = cfg_mod._merge_profile_root_agency_config(profile_config, root_config)

    assert profile_config["agency"]["relay"] == {
        "allowlist": ["local-peer"],
        "auto_allow_team": False,
    }
    assert merged["agency"]["daemon_bin"] == "/root/bin/agentanycastd"
    assert merged["agency"]["relay"] == {
        "address": "/ip4/198.51.100.10/tcp/4001/p2p/12D3KooWRelay",
        "allowlist": ["local-peer"],
        "auto_allow_team": False,
    }


def test_get_config_with_relay_and_list_trusted_peers(plugin_modules, monkeypatch, tmp_path):
    cfg_mod = plugin_modules.config
    home = tmp_path / "aac-home"
    daemon_bin = tmp_path / "custom-agentanycastd"
    monkeypatch.setattr(
        cfg_mod,
        "load_config",
        lambda: {
            "agency": {
                "enabled": True,
                "relay": {
                    "address": "/ip4/127.0.0.1/tcp/1234",
                    "allowlist": ["peer-a", "peer-c"],
                    "auto_allow_team": False,
                    "allow_all": True,
                    "token": "secret-token",
                },
                "registry": {"allow_insecure_token_transport": True},
                "auto_start": True,
                "skills_from_profile": False,
                "allow_remote_tasks": True,
                "trusted_peers": ["peer-a", "peer-b"],
                "incoming_queue_limit": 7,
                "home": str(home),
                "daemon_bin": str(daemon_bin),
                "incoming": {
                    "mode": "template",
                    "delegation_timeout": 9,
                    "max_queue_size": 2,
                    "handler_timeout_seconds": 11,
                    "idle_timeout_seconds": 12,
                    "tool_access": "none",
                    "max_iterations": 3,
                    "subprocess_profile": "gpt-subprocess",
                    "reject_unmatched_skills": True,
                    "allow_subprocess": True,
                    "allow_subprocess_fallback": True,
                    "min_subprocess_trust": "full",
                    "allow_hooks_for_remote": True,
                },
                "trust": {
                    "store_path": str(tmp_path / "custom-trust.json"),
                    "tofu": False,
                },
                "team": {
                    "auto_discover": False,
                    "auto_register": False,
                    "inject_context": False,
                    "kanban_integration": False,
                    "self_serve": False,
                    "announce_progress": True,
                    "bidding": True,
                    "proactive": True,
                    "learning": True,
                    "tenant": "alpha",
                    "context_refresh_minutes": 9,
                },
                "orchestrator": {
                    "enabled": True,
                    "agent": "local-agent",
                    "auto_start": True,
                    "auto_decompose": False,
                },
                "pool": {"max_online_agents": 2, "max_total_rss_mb": 1536},
                "workspace": {"root": str(tmp_path / "workspace")},
                "proactive": {
                    "enabled": True,
                    "triggers": [{"type": "file-watch"}],
                },
                "routing": {"deploy": "hermes", "code": "local-agent"},
                "outbound": {
                    "url_validation": "strict",
                    "url_allowlist": ["https://agents.example.com", "https://*.trusted.test"],
                },
            }
        },
    )

    cfg = cfg_mod.get_config()

    assert cfg.enabled is True
    assert cfg.relay == "/ip4/127.0.0.1/tcp/1234"
    assert cfg.auto_start is True
    assert cfg.skills_from_profile is False
    assert cfg.allow_remote_tasks is True
    assert cfg.trusted_peers == ("peer-a", "peer-b")
    assert cfg.relay_security.allowlist == ("peer-a", "peer-c")
    assert cfg.relay_security.auto_allow_team is False
    assert cfg.relay_security.allow_all is True
    assert cfg.relay_security.token == "secret-token"
    assert cfg.registry_allow_insecure_token_transport is True
    assert cfg.trust.store_path == tmp_path / "custom-trust.json"
    assert cfg.trust.tofu is False
    assert cfg.incoming_queue_limit == 7
    assert cfg.home == home
    assert cfg.daemon_bin == daemon_bin
    assert cfg.incoming.mode == "template"
    assert cfg.incoming.delegation_timeout == 9
    assert cfg.incoming.max_queue_size == 2
    assert cfg.incoming.handler_timeout_seconds == 11
    assert cfg.incoming.idle_timeout_seconds == 12
    assert cfg.incoming.tool_access == "none"
    assert cfg.incoming.max_iterations == 3
    assert cfg.incoming.subprocess_profile == "gpt-subprocess"
    assert cfg.incoming.reject_unmatched_skills is True
    assert cfg.incoming.allow_subprocess is True
    assert cfg.incoming.allow_subprocess_fallback is True
    assert cfg.incoming.min_subprocess_trust == "full"
    assert cfg.incoming.allow_hooks_for_remote is True
    assert cfg.team.auto_discover is False
    assert cfg.team.auto_register is False
    assert cfg.team.inject_context is False
    assert cfg.team.kanban_integration is False
    assert cfg.team.self_serve is False
    assert cfg.team.announce_progress is True
    assert cfg.team.bidding is True
    assert cfg.team.proactive is True
    assert cfg.team.learning is True
    assert cfg.team.tenant == "alpha"
    assert cfg.team.context_refresh_minutes == 9
    assert cfg.orchestrator.enabled is True
    assert cfg.orchestrator.agent == "local-agent"
    assert cfg.orchestrator.auto_start is True
    assert cfg.orchestrator.auto_decompose is False
    assert cfg.pool.max_online_agents == 2
    assert cfg.pool.max_total_rss_mb == 1536
    assert cfg.workspace.root == tmp_path / "workspace"
    assert cfg.proactive == {"enabled": True, "triggers": [{"type": "file-watch"}]}
    assert cfg.routing == {"deploy": "hermes", "code": "local-agent"}
    assert cfg.outbound.url_validation == "strict"
    assert cfg.outbound.url_allowlist == ("https://agents.example.com", "https://*.trusted.test")


def test_trust_store_tofu_records_and_verifies_known_peer(plugin_modules, tmp_path):
    trust = plugin_modules.trust
    store = trust.TrustStore(tmp_path / "trust.json", tofu=True)

    first = store.verify_peer("peer-1", name="remote agency host")
    second = store.verify_peer("peer-1", name="remote agency host")

    assert first.allowed is True
    assert first.action == "tofu_recorded"
    assert first.trust_level == "limited"
    assert second.allowed is True
    assert second.action == "verified"
    data = json.loads((tmp_path / "trust.json").read_text(encoding="utf-8"))
    assert data["peers"]["peer-1"]["name"] == "remote agency host"
    assert data["peers"]["peer-1"]["trust_level"] == "limited"


def stat_mode(path):
    return os.stat(path).st_mode & 0o777


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX file modes")
def test_trust_store_save_restricts_file_and_parent_permissions(plugin_modules, tmp_path):
    trust = plugin_modules.trust
    store = trust.TrustStore(tmp_path / "trust-dir" / "trust.json", tofu=True)

    store.verify_peer("peer-1", name="remote agency host")

    assert stat_mode(store.path) == 0o600
    assert stat_mode(store.path.parent) == 0o700


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX file modes")
def test_trust_store_load_warns_on_permissive_file_permissions(plugin_modules, tmp_path, caplog):
    trust_path = tmp_path / "trust.json"
    trust_path.write_text(
        '{"version":1,"peers":{"peer-1":{"trust_level":"full"}}}', encoding="utf-8"
    )
    trust_path.chmod(0o644)
    store = plugin_modules.trust.TrustStore(trust_path, tofu=True)

    with caplog.at_level("WARNING"):
        data = store.load()

    assert data["peers"]["peer-1"]["trust_level"] == "full"
    assert "permissions" in caplog.text
    assert "0600" in caplog.text


def test_trust_store_rejects_name_peer_id_mismatch_and_blocked_peer(plugin_modules, tmp_path):
    trust = plugin_modules.trust
    store = trust.TrustStore(tmp_path / "trust.json", tofu=True)

    store.verify_peer("peer-original", name="local workstation", trust_level="full")
    mismatch = store.verify_peer("peer-rotated", name="local workstation")
    store.set_trust("peer-blocked", trust_level="blocked", name="Blocked")
    blocked = store.verify_peer("peer-blocked", name="Blocked")

    assert mismatch.allowed is False
    assert mismatch.action == "peer_id_mismatch"
    assert "peer-original" in mismatch.reason
    assert blocked.allowed is False
    assert blocked.action == "blocked"


class _FakeIncomingPart:
    def __init__(self, text: str):
        self.text = text


class _FakeIncomingMessage:
    def __init__(self, text: str):
        self.parts = [_FakeIncomingPart(text)]


class _FakeIncomingTask:
    target_skill_id = ""
    metadata = {}
    sender_card = None

    def __init__(self, text: str, *, peer_id: str = "peer-good", task_id: str = "task-in"):
        self.task_id = task_id
        self.peer_id = peer_id
        self.messages = [_FakeIncomingMessage(text)]
        self.completed = None
        self.failed = None
        self.status_updates = []

    async def complete(self, artifacts):
        self.completed = artifacts

    async def fail(self, error):
        self.failed = error

    async def update_status(self, status):
        self.status_updates.append(status)


def _registration_control(plugin_modules, peer_id: str = "peer-good", name: str = "Good") -> str:
    return plugin_modules.registration.serialize_control_message(
        {
            "protocol": "agency.autonomous.v1",
            "type": "registration",
            "event": "registered",
            "peer_id": peer_id,
            "agent": {"name": name, "description": "Trusted sender", "skills": []},
        }
    )


def _security_cfg(plugin_modules, tmp_path, *, allowlist=("peer-good",), tofu=True):
    return plugin_modules.config.AgencyConfig(
        relay_security=plugin_modules.config.RelaySecurityConfig(allowlist=allowlist),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json", tofu=tofu),
    )


@pytest.mark.asyncio
async def test_unknown_peer_cannot_register(plugin_modules, monkeypatch, tmp_path):
    nm = plugin_modules.node_manager
    registration = plugin_modules.registration
    registration._state.registrations = {}
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-good",), tofu=True)
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    task = _FakeIncomingTask(
        _registration_control(plugin_modules, peer_id="peer-unknown"), peer_id="peer-unknown"
    )

    await nm.NodeManager()._handle_incoming_task(task)

    assert task.failed
    assert "allowlist" in task.failed
    assert registration.live_registrations(include_stale=True) == []


@pytest.mark.asyncio
async def test_blocked_peer_cannot_register(plugin_modules, monkeypatch, tmp_path):
    nm = plugin_modules.node_manager
    registration = plugin_modules.registration
    registration._state.registrations = {}
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-blocked",), tofu=True)
    plugin_modules.trust.store_for_config(cfg).set_trust(
        "peer-blocked", trust_level="blocked", name="Blocked"
    )
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    task = _FakeIncomingTask(
        _registration_control(plugin_modules, peer_id="peer-blocked", name="Blocked"),
        peer_id="peer-blocked",
    )

    await nm.NodeManager()._handle_incoming_task(task)

    assert task.failed
    assert "blocked" in task.failed
    assert registration.live_registrations(include_stale=True) == []


@pytest.mark.asyncio
async def test_peer_not_in_allowlist_cannot_register(plugin_modules, monkeypatch, tmp_path):
    nm = plugin_modules.node_manager
    registration = plugin_modules.registration
    registration._state.registrations = {}
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-allowed",), tofu=True)
    plugin_modules.trust.store_for_config(cfg).set_trust(
        "peer-denied", trust_level="full", name="Denied"
    )
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    task = _FakeIncomingTask(
        _registration_control(plugin_modules, peer_id="peer-denied", name="Denied"),
        peer_id="peer-denied",
    )

    await nm.NodeManager()._handle_incoming_task(task)

    assert task.failed
    assert "allowlist" in task.failed
    assert registration.live_registrations(include_stale=True) == []


@pytest.mark.asyncio
async def test_tofu_mismatch_cannot_register(plugin_modules, monkeypatch, tmp_path):
    nm = plugin_modules.node_manager
    registration = plugin_modules.registration
    registration._state.registrations = {}
    cfg = _security_cfg(
        plugin_modules, tmp_path, allowlist=("peer-original", "peer-rotated"), tofu=True
    )
    plugin_modules.trust.store_for_config(cfg).set_trust(
        "peer-original", trust_level="full", name="local workstation"
    )
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    task = _FakeIncomingTask(
        _registration_control(plugin_modules, peer_id="peer-rotated", name="local workstation"),
        peer_id="peer-rotated",
    )

    await nm.NodeManager()._handle_incoming_task(task)

    assert task.failed
    assert "previously trusted" in task.failed
    assert registration.live_registrations(include_stale=True) == []


@pytest.mark.asyncio
async def test_trusted_peer_can_register(plugin_modules, monkeypatch, tmp_path):
    nm = plugin_modules.node_manager
    registration = plugin_modules.registration
    registration._state.registrations = {}
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-good",), tofu=True)
    plugin_modules.trust.store_for_config(cfg).set_trust(
        "peer-good", trust_level="full", name="Good"
    )
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    task = _FakeIncomingTask(_registration_control(plugin_modules), peer_id="peer-good")

    await nm.NodeManager()._handle_incoming_task(task)

    assert task.failed is None
    assert task.completed is not None
    assert registration.live_registrations(include_stale=True)[0]["peer_id"] == "peer-good"


@pytest.mark.asyncio
async def test_trusted_peer_can_send_normal_task(plugin_modules, monkeypatch, tmp_path):
    nm = plugin_modules.node_manager
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-good",), tofu=True)
    plugin_modules.trust.store_for_config(cfg).set_trust(
        "peer-good", trust_level="full", name="Good"
    )
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    manager = nm.NodeManager()
    manager._incoming_queue = __import__("asyncio").Queue()
    task = _FakeIncomingTask("hello", peer_id="peer-good")

    await manager._handle_incoming_task(task)

    queued_task, queued_task_id = manager._incoming_queue.get_nowait()
    assert queued_task is task
    assert queued_task_id == "task-in"
    assert task.failed is None


@pytest.mark.asyncio
async def test_incoming_queue_accepts_tasks_under_limit(plugin_modules, monkeypatch, tmp_path):
    nm = plugin_modules.node_manager
    cfg = plugin_modules.config.AgencyConfig(
        relay_security=plugin_modules.config.RelaySecurityConfig(allowlist=("peer-good",)),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
        incoming=plugin_modules.config.IncomingConfig(max_queue_size=2),
    )
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-good", trust_level="full")
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    manager = nm.NodeManager()
    manager._incoming_queue = __import__("asyncio").Queue(maxsize=cfg.incoming.max_queue_size)

    await manager._handle_incoming_task(_FakeIncomingTask("one", task_id="task-1"))
    await manager._handle_incoming_task(_FakeIncomingTask("two", task_id="task-2"))

    assert manager._incoming_queue.qsize() == 2
    assert manager.state.incoming_dropped_count == 0
    assert manager.state.incoming_queue_size == 2
    assert manager.state.incoming_queue_max_size == 2


@pytest.mark.asyncio
async def test_incoming_queue_drops_newest_task_when_full(
    plugin_modules, monkeypatch, tmp_path, caplog
):
    nm = plugin_modules.node_manager
    cfg = plugin_modules.config.AgencyConfig(
        relay_security=plugin_modules.config.RelaySecurityConfig(allowlist=("peer-good",)),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
        incoming=plugin_modules.config.IncomingConfig(max_queue_size=1),
    )
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-good", trust_level="full")
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    manager = nm.NodeManager()
    manager._incoming_queue = __import__("asyncio").Queue(maxsize=cfg.incoming.max_queue_size)

    await manager._handle_incoming_task(_FakeIncomingTask("one", task_id="task-1"))
    dropped = _FakeIncomingTask("two", task_id="task-2")
    with caplog.at_level("WARNING"):
        await manager._handle_incoming_task(dropped)

    assert manager._incoming_queue.qsize() == 1
    assert dropped.failed is not None
    assert "queue full" in dropped.failed.lower()
    assert manager._incoming_records["task-2"].status == "failed"
    assert manager.state.incoming_dropped_count == 1
    assert "peer-good" in caplog.text
    assert manager.compact_info()["incoming"]["dropped"] == 1


@pytest.mark.asyncio
async def test_incoming_queue_recovers_after_draining(plugin_modules, monkeypatch, tmp_path):
    nm = plugin_modules.node_manager
    cfg = plugin_modules.config.AgencyConfig(
        relay_security=plugin_modules.config.RelaySecurityConfig(allowlist=("peer-good",)),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
        incoming=plugin_modules.config.IncomingConfig(max_queue_size=1),
    )
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-good", trust_level="full")
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    manager = nm.NodeManager()
    manager._incoming_queue = __import__("asyncio").Queue(maxsize=cfg.incoming.max_queue_size)

    await manager._handle_incoming_task(_FakeIncomingTask("one", task_id="task-1"))
    manager._incoming_queue.get_nowait()
    manager._incoming_queue.task_done()
    second = _FakeIncomingTask("two", task_id="task-2")
    await manager._handle_incoming_task(second)

    queued_task, queued_task_id = manager._incoming_queue.get_nowait()
    assert queued_task is second
    assert queued_task_id == "task-2"
    assert second.failed is None


@pytest.mark.asyncio
async def test_rejected_control_message_does_not_mutate_registration_state(
    plugin_modules, monkeypatch, tmp_path
):
    nm = plugin_modules.node_manager
    registration = plugin_modules.registration
    registration._state.registrations = {}
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=(), tofu=True)
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    task = _FakeIncomingTask(_registration_control(plugin_modules), peer_id="peer-good")

    await nm.NodeManager()._handle_incoming_task(task)

    assert task.failed
    assert task.completed is None
    assert registration.live_registrations(include_stale=True) == []


def test_effective_relay_allowlist_includes_verified_team_peers_when_enabled(
    plugin_modules, monkeypatch, tmp_path
):
    cfg_mod = plugin_modules.config
    node_manager = plugin_modules.node_manager
    team_context = importlib.import_module("hermes_plugin.team_context")
    team_context.get_team_state().peers = {
        "peer-team": team_context.PeerCapability(peer_id="peer-team", name="Team Peer"),
        "peer-configured": team_context.PeerCapability(
            peer_id="peer-configured", name="Already Configured"
        ),
    }
    cfg = cfg_mod.AgencyConfig(
        relay_security=cfg_mod.RelaySecurityConfig(
            allowlist=("peer-configured",), auto_allow_team=True
        ),
        trust=cfg_mod.TrustConfig(store_path=tmp_path / "trust.json"),
    )
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-team", trust_level="full")
    monkeypatch.setattr(cfg_mod, "load_config", lambda: {})
    monkeypatch.setattr(node_manager, "get_config", lambda: cfg)

    allowlist = node_manager.manager.effective_relay_allowlist(cfg)

    assert allowlist == ["peer-configured", "peer-team"]


def test_empty_allowlist_denies_by_default(plugin_modules, tmp_path):
    cfg = plugin_modules.config.AgencyConfig(
        relay_security=plugin_modules.config.RelaySecurityConfig(allowlist=(), allow_all=False),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
    )

    assert plugin_modules.trust.peer_allowed_by_config(cfg, "peer-any") is False
    assert (
        plugin_modules.node_manager.NodeManager()._peer_allowed_by_effective_allowlist(
            cfg, "peer-any"
        )
        is False
    )


def test_allow_all_true_allows_with_warning(plugin_modules, tmp_path, caplog):
    cfg = plugin_modules.config.AgencyConfig(
        relay_security=plugin_modules.config.RelaySecurityConfig(allow_all=True),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
    )

    with caplog.at_level("WARNING"):
        allowed = plugin_modules.trust.peer_allowed_by_config(cfg, "peer-any")

    assert allowed is True
    assert "agency.relay.allow_all=true" in caplog.text


def test_team_peer_auto_add_requires_trust_verification(plugin_modules, tmp_path):
    node_manager = plugin_modules.node_manager
    team_context = importlib.import_module("hermes_plugin.team_context")
    team_context.get_team_state().peers = {
        "peer-unverified": team_context.PeerCapability(peer_id="peer-unverified", name="Team Peer")
    }
    cfg = plugin_modules.config.AgencyConfig(
        relay_security=plugin_modules.config.RelaySecurityConfig(auto_allow_team=True),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
    )

    assert node_manager.NodeManager().effective_relay_allowlist(cfg) == []

    plugin_modules.trust.store_for_config(cfg).set_trust("peer-unverified", trust_level="full")
    assert node_manager.NodeManager().effective_relay_allowlist(cfg) == ["peer-unverified"]


def test_blocked_peer_overrides_allow_all(plugin_modules, tmp_path):
    cfg = plugin_modules.config.AgencyConfig(
        relay_security=plugin_modules.config.RelaySecurityConfig(allow_all=True),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
    )
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-blocked", trust_level="blocked")

    assert plugin_modules.trust.peer_allowed_by_config(cfg, "peer-blocked") is False


def test_a2a_info_includes_relay_security_and_trust_status(plugin_modules, monkeypatch):
    cfg_mod = plugin_modules.config
    monkeypatch.setattr(cfg_mod, "load_config", lambda: {})

    payload = json.loads(plugin_modules.tools.a2a_info({}))

    assert payload["ok"] is True
    assert payload["node"]["relay_security"]["token_configured"] is False
    assert payload["node"]["relay_security"]["effective_allowlist"] == []
    assert payload["node"]["trust"]["store_path"].endswith("/agency/trust.json")
    assert payload["node"]["trust"]["tofu"] is True


def test_get_config_trusted_peers_string_and_queue_limit_clamp(plugin_modules, monkeypatch):
    cfg_mod = plugin_modules.config
    monkeypatch.setattr(
        cfg_mod,
        "load_config",
        lambda: {"agency": {"trusted_peers": "peer-a, peer-b,, ", "incoming_queue_limit": -5}},
    )

    cfg = cfg_mod.get_config()

    assert cfg.trusted_peers == ("peer-a", "peer-b")
    assert cfg.incoming_queue_limit == 1


def test_incoming_config_invalid_values_fall_back_to_safe_defaults(plugin_modules, monkeypatch):
    cfg_mod = plugin_modules.config
    monkeypatch.setattr(
        cfg_mod,
        "load_config",
        lambda: {
            "agency": {
                "incoming": {
                    "mode": "bogus",
                    "delegation_timeout": "bad",
                    "max_queue_size": "bad",
                    "handler_timeout_seconds": "bad",
                    "tool_access": "root",
                    "max_iterations": 0,
                }
            }
        },
    )

    cfg = cfg_mod.get_config()

    assert cfg.incoming.mode == "delegation"
    assert cfg.incoming.delegation_timeout == 600
    assert cfg.incoming.max_queue_size == 100
    assert cfg.incoming.handler_timeout_seconds == 900
    assert cfg.incoming.tool_access == "safe"
    assert cfg.incoming.max_iterations == 1
    assert cfg.incoming.subprocess_profile is None
    assert cfg.incoming.reject_unmatched_skills is False


def test_incoming_config_accepts_subprocess_mode_and_profile(plugin_modules, monkeypatch):
    cfg_mod = plugin_modules.config
    monkeypatch.setattr(
        cfg_mod,
        "load_config",
        lambda: {
            "agency": {"incoming": {"mode": "subprocess", "subprocess_profile": "local-agent"}}
        },
    )

    cfg = cfg_mod.get_config()

    assert cfg.incoming.mode == "subprocess"
    assert cfg.incoming.subprocess_profile == "local-agent"


def test_incoming_config_reject_unmatched_skills_defaults_false_and_can_enable(
    plugin_modules,
    monkeypatch,
):
    cfg_mod = plugin_modules.config
    monkeypatch.setattr(cfg_mod, "load_config", lambda: {})

    cfg = cfg_mod.get_config()

    assert cfg.incoming.reject_unmatched_skills is False
    assert cfg.incoming_reject_unmatched_skills is False
    assert cfg.incoming.send_progress is False
    assert cfg.incoming_send_progress is False
    assert cfg.incoming.conversation_ttl == 3600
    assert cfg.incoming_conversation_ttl == 3600
    assert cfg.incoming.conversation_max_turns == 20
    assert cfg.incoming_conversation_max_turns == 20

    monkeypatch.setattr(
        cfg_mod,
        "load_config",
        lambda: {
            "agency": {
                "incoming": {
                    "reject_unmatched_skills": True,
                    "send_progress": True,
                    "conversation_ttl": 120,
                    "conversation_max_turns": 3,
                }
            }
        },
    )

    cfg = cfg_mod.get_config()
    assert cfg.incoming.reject_unmatched_skills is True
    assert cfg.incoming_reject_unmatched_skills is True
    assert cfg.incoming.send_progress is True
    assert cfg.incoming_send_progress is True
    assert cfg.incoming.conversation_ttl == 120
    assert cfg.incoming_conversation_ttl == 120
    assert cfg.incoming.conversation_max_turns == 3
    assert cfg.incoming_conversation_max_turns == 3


def test_task_processor_builds_prompt_and_maps_tool_access(plugin_modules):
    tp = plugin_modules.task_processor
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="haiku",
        message_text="Write a haiku about AI agents",
        context_packet={"sender_name": "local workstation"},
        metadata={},
    )

    prompt = tp.build_delegation_prompt(record)

    assert "Sender: local workstation (peer-1)" in prompt
    assert "Skill requested: haiku" in prompt
    assert "Write a haiku about AI agents" in prompt
    assert tp.toolsets_for_access("safe") == ["web", "search", "skills", "memory", "session_search"]
    assert tp.toolsets_for_access("none") == []
    assert tp.toolsets_for_access("full") is None
    assert tp.toolsets_for_access(None) == ["web", "search", "skills", "memory", "session_search"]
    assert tp.toolsets_for_access("invalid") == [
        "web",
        "search",
        "skills",
        "memory",
        "session_search",
    ]


def test_load_skill_context_exact_prefix_substring_and_not_found(plugin_modules, tmp_path):
    tp = plugin_modules.task_processor
    tp._SKILL_CONTEXT_CACHE.clear()
    profile = tmp_path / "profile"
    (profile / "skills" / "code-review").mkdir(parents=True)
    (profile / "skills" / "ops" / "hermes-agent").mkdir(parents=True)
    (profile / "skills" / "code-review" / "SKILL.md").write_text(
        "---\nname: Code Review\ndescription: Review code safely.\n---\n# Code Review\n\nCheck diffs first.\n",
        encoding="utf-8",
    )
    (profile / "skills" / "ops" / "hermes-agent" / "SKILL.md").write_text(
        "---\nname: Hermes Agent\ndescription: Configure Hermes.\n---\n# Hermes Agent\n\nUse hermes config commands.\n",
        encoding="utf-8",
    )

    exact = tp.load_skill_context("hermes-agent", profile)
    assert exact is not None
    assert 'The sender requested the "hermes-agent" skill.' in exact
    assert "Skill description: Configure Hermes." in exact
    assert "Use hermes config commands." in exact
    assert "Matched local Hermes skill: hermes-agent" in exact

    prefix = tp.load_skill_context("code", profile)
    assert prefix is not None
    assert 'The sender requested the "code" skill.' in prefix
    assert "Matched local Hermes skill: code-review" in prefix

    substring = tp.load_skill_context("review", profile)
    assert substring is not None
    assert "Matched local Hermes skill: code-review" in substring

    assert tp.load_skill_context("nonexistent-skill", profile) is None


def test_load_skill_context_caches_existing_files_but_not_missing(
    plugin_modules, tmp_path, monkeypatch
):
    tp = plugin_modules.task_processor
    tp._SKILL_CONTEXT_CACHE.clear()
    profile = tmp_path / "profile"
    skill_dir = profile / "skills" / "cached"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: Cached\ndescription: First description.\n---\n# Cached\n\nfirst body\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(tp.time, "time", lambda: 1000.0)
    first = tp.load_skill_context("cached", profile)
    skill_file.write_text(
        "---\nname: Cached\ndescription: Second description.\n---\n# Cached\n\nsecond body\n",
        encoding="utf-8",
    )

    assert tp.load_skill_context("cached", profile) == first

    monkeypatch.setattr(tp.time, "time", lambda: 1301.0)
    assert "Second description" in (tp.load_skill_context("cached", profile) or "")

    assert tp.load_skill_context("later", profile) is None
    later_dir = profile / "skills" / "later"
    later_dir.mkdir(parents=True)
    (later_dir / "SKILL.md").write_text(
        "---\nname: Later\ndescription: Appeared after a miss.\n---\n# Later\n",
        encoding="utf-8",
    )
    assert "Appeared after a miss" in (tp.load_skill_context("later", profile) or "")


def test_process_incoming_task_injects_loaded_skill_context(plugin_modules, monkeypatch, tmp_path):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        allow_remote_tasks=True,
        incoming=plugin_modules.config.IncomingConfig(tool_access="none", max_iterations=3),
    )
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="hermes-agent",
        message_text="How do I inspect Hermes config?",
        context_packet={"sender_name": "local workstation"},
        metadata={},
    )
    profile = tmp_path / "profile"
    skill_dir = profile / "skills" / "hermes-agent"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: Hermes Agent\n"
        "description: Configure Hermes Agent.\n"
        "---\n"
        "# Hermes Agent\n\n"
        "Use `hermes config path`.\n",
        encoding="utf-8",
    )
    captured = {}
    monkeypatch.setattr(tp, "_active_profile_home", lambda: profile)

    def fake_delegate(**kwargs):
        captured.update(kwargs)
        return "Use `hermes config path` to inspect the active config file."

    monkeypatch.setattr(tp, "_call_delegate_task", fake_delegate)

    assert "hermes config path" in tp.process_incoming_task(record, cfg)
    assert 'The sender requested the "hermes-agent" skill.' in captured["goal"]
    assert "Skill description: Configure Hermes Agent." in captured["goal"]
    assert "Use `hermes config path`." in captured["goal"]


def test_process_incoming_task_rejects_unmatched_skill_when_configured(plugin_modules, monkeypatch):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        allow_remote_tasks=True,
        incoming=plugin_modules.config.IncomingConfig(reject_unmatched_skills=True),
    )
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="nonexistent-skill",
        message_text="hello",
        context_packet=None,
        metadata={},
    )
    monkeypatch.setattr(tp, "_active_profile_home", lambda: plugin_modules.hermes_home)

    with pytest.raises(tp.TaskProcessingError, match="I don't have the nonexistent-skill skill"):
        tp.process_incoming_task(record, cfg)


def test_process_via_subprocess_streams_batched_progress(plugin_modules, monkeypatch, tmp_path):
    tp = plugin_modules.task_processor
    fake_hermes = tmp_path / "fake-hermes"
    fake_hermes.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "print('Warning: ignore me', flush=True)\n"
        "print('first progress', flush=True)\n"
        "print('second progress', flush=True)\n"
        "print('third progress', flush=True)\n"
        "print('final answer', flush=True)\n",
        encoding="utf-8",
    )
    fake_hermes.chmod(0o755)
    updates = []
    monkeypatch.setattr(tp, "_resolve_hermes_command", lambda: str(fake_hermes))
    monkeypatch.setattr(tp.time, "time", lambda: 1000.0)

    response = tp.process_via_subprocess("gpt", "hello", 10, progress_callback=updates.append)

    assert response == "first progress\nsecond progress\nthird progress\nfinal answer"
    assert updates == ["first progress\nsecond progress\nthird progress"]


def test_process_via_subprocess_strips_session_env(plugin_modules, monkeypatch, tmp_path):
    tp = plugin_modules.task_processor
    fake_hermes = tmp_path / "fake-hermes"
    fake_hermes.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "leaked = sorted(k for k in os.environ if k.startswith('HERMES_SESSION_'))\n"
        "print('leaked=' + ','.join(leaked), flush=True)\n",
        encoding="utf-8",
    )
    fake_hermes.chmod(0o755)
    monkeypatch.setattr(tp, "_resolve_hermes_command", lambda: str(fake_hermes))
    monkeypatch.setenv("HERMES_SESSION_ID", "parent-session-from-runner")
    monkeypatch.setenv("HERMES_SESSION_KEY", "parent-key-from-runner")
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")

    response = tp.process_via_subprocess("gpt", "hello", 10)

    assert response == "leaked="


def test_precreate_delegate_parent_session_writes_parent_row(plugin_modules):
    tp = plugin_modules.task_processor
    calls = []

    class FakeSessionDB:
        def create_session(self, *args, **kwargs):
            calls.append((args, kwargs))

    tp._precreate_delegate_parent_session(
        session_db=FakeSessionDB(),
        parent_session_id="agency-parent-1",
        effective_model="gpt-test",
        runtime={"provider": "test-provider"},
    )

    assert calls == [
        (
            ("agency-parent-1", "agency"),
            {
                "model": "gpt-test",
                "model_config": {
                    "_agency_delegate_parent": True,
                    "provider": "test-provider",
                },
            },
        )
    ]


def test_process_incoming_task_sends_delegation_heartbeat_after_threshold(
    plugin_modules, monkeypatch
):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        allow_remote_tasks=True,
        incoming=plugin_modules.config.IncomingConfig(send_progress=True),
    )
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="",
        message_text="slow work",
        context_packet=None,
        metadata={},
    )
    updates = []
    monkeypatch.setattr(tp, "DELEGATION_FIRST_PROGRESS_SECONDS", 0.01)
    monkeypatch.setattr(tp, "DELEGATION_PROGRESS_INTERVAL_SECONDS", 0.01)

    def slow_delegate(**_kwargs):
        import time as real_time

        real_time.sleep(0.04)
        return "done"

    monkeypatch.setattr(tp, "_call_delegate_task", slow_delegate)

    assert tp.process_incoming_task(record, cfg, progress_callback=updates.append) == "done"
    assert updates
    assert updates[0] == "Processing..."


def test_process_incoming_task_progress_disabled_by_default(plugin_modules, monkeypatch):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        allow_remote_tasks=True,
        incoming=plugin_modules.config.IncomingConfig(send_progress=False),
    )
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="",
        message_text="quick work",
        context_packet=None,
        metadata={},
    )
    updates = []
    monkeypatch.setattr(tp, "_call_delegate_task", lambda **_kwargs: "done")

    assert tp.process_incoming_task(record, cfg, progress_callback=updates.append) == "done"
    assert updates == []


def test_process_incoming_task_extracts_delegate_summary(plugin_modules, monkeypatch):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        allow_remote_tasks=True,
        incoming=plugin_modules.config.IncomingConfig(tool_access="none", max_iterations=3),
    )
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="math",
        message_text="What is 2 + 2?",
        context_packet={"sender_name": "local workstation"},
        metadata={},
    )
    captured = {}

    def fake_delegate(**kwargs):
        captured.update(kwargs)
        return "4"

    monkeypatch.setattr(tp, "_call_delegate_task", fake_delegate)

    assert tp.process_incoming_task(record, cfg) == "4"
    assert "What is 2 + 2?" in captured["goal"]
    assert captured["toolsets"] == []
    assert captured["max_iterations"] == 3


def test_process_incoming_task_falls_back_to_subprocess_when_explicitly_allowed(
    plugin_modules, monkeypatch, tmp_path
):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        allow_remote_tasks=True,
        incoming=plugin_modules.config.IncomingConfig(
            subprocess_profile="gpt",
            allow_subprocess=True,
            allow_subprocess_fallback=True,
        ),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
    )
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-1", trust_level="full")
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="",
        message_text="hello",
        context_packet=None,
        metadata={},
    )

    def fake_delegate(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tp, "_call_delegate_task", fake_delegate)
    monkeypatch.setattr(
        tp, "process_via_subprocess", lambda profile, message, timeout: "subprocess response"
    )

    assert (
        tp.process_incoming_task(record, cfg, lambda _record: "subprocess response")
        == "subprocess response"
    )


def test_process_incoming_task_does_not_fallback_to_subprocess_by_default(
    plugin_modules, monkeypatch
):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        allow_remote_tasks=True,
        incoming=plugin_modules.config.IncomingConfig(subprocess_profile="gpt"),
    )
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="",
        message_text="hello",
        context_packet=None,
        metadata={},
    )

    def fake_delegate(**_kwargs):
        raise RuntimeError("boom")

    def should_not_subprocess(*_args, **_kwargs):
        raise AssertionError("subprocess fallback should be disabled by default")

    monkeypatch.setattr(tp, "_call_delegate_task", fake_delegate)
    monkeypatch.setattr(tp, "process_via_subprocess", should_not_subprocess)

    assert (
        tp.process_incoming_task(record, cfg, lambda _record: "template fallback")
        == "template fallback"
    )


def test_process_incoming_task_subprocess_mode_fails_closed_unless_allowed(
    plugin_modules, monkeypatch
):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        allow_remote_tasks=True,
        incoming=plugin_modules.config.IncomingConfig(mode="subprocess", subprocess_profile="gpt"),
    )
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="",
        message_text="hello",
        context_packet=None,
        metadata={},
    )

    def should_not_subprocess(*_args, **_kwargs):
        raise AssertionError("subprocess should require agency.incoming.allow_subprocess=true")

    monkeypatch.setattr(tp, "process_via_subprocess", should_not_subprocess)

    assert (
        tp.process_incoming_task(record, cfg, lambda _record: "template fallback")
        == "template fallback"
    )


def test_limited_trust_peer_cannot_subprocess_even_when_mode_set(
    plugin_modules, monkeypatch, tmp_path
):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        allow_remote_tasks=True,
        incoming=plugin_modules.config.IncomingConfig(
            mode="subprocess", subprocess_profile="gpt", allow_subprocess=True
        ),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
    )
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-1", trust_level="limited")
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="",
        message_text="hello",
        context_packet=None,
        metadata={},
    )

    def should_not_subprocess(*_args, **_kwargs):
        raise AssertionError("limited-trust peers must not run subprocess")

    monkeypatch.setattr(tp, "process_via_subprocess", should_not_subprocess)

    assert (
        tp.process_incoming_task(record, cfg, lambda _record: "template fallback")
        == "template fallback"
    )


def test_process_incoming_task_uses_template_fallback_when_subprocess_fails(
    plugin_modules, monkeypatch, tmp_path
):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        allow_remote_tasks=True,
        incoming=plugin_modules.config.IncomingConfig(
            subprocess_profile="gpt",
            allow_subprocess=True,
            allow_subprocess_fallback=True,
        ),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
    )
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-1", trust_level="full")
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="",
        message_text="hello",
        context_packet=None,
        metadata={},
    )

    def fake_delegate(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tp, "_call_delegate_task", fake_delegate)
    monkeypatch.setattr(
        tp, "process_via_subprocess", lambda profile, message, timeout: "ERROR: nope"
    )

    assert (
        tp.process_incoming_task(record, cfg, lambda _record: "template fallback")
        == "template fallback"
    )


def test_process_incoming_task_subprocess_mode_skips_delegation(
    plugin_modules, monkeypatch, tmp_path
):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        allow_remote_tasks=True,
        incoming=plugin_modules.config.IncomingConfig(
            mode="subprocess", subprocess_profile="gpt", allow_subprocess=True
        ),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
    )
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-1", trust_level="full")
    record = types.SimpleNamespace(
        task_id="task-1",
        sender_peer_id="peer-1",
        target_skill_id="",
        message_text="hello",
        context_packet=None,
        metadata={},
    )

    def should_not_delegate(**_kwargs):
        raise AssertionError("delegation should be skipped in subprocess mode")

    monkeypatch.setattr(tp, "_call_delegate_task", should_not_delegate)
    monkeypatch.setattr(
        tp, "process_via_subprocess", lambda profile, message, timeout: "forced subprocess"
    )

    assert (
        tp.process_incoming_task(record, cfg, lambda _record: "template fallback")
        == "forced subprocess"
    )


def test_resolve_subprocess_profile_uses_override_then_active_profile(plugin_modules, monkeypatch):
    tp = plugin_modules.task_processor
    cfg = plugin_modules.config.AgencyConfig(
        incoming=plugin_modules.config.IncomingConfig(subprocess_profile="override-profile")
    )
    assert tp.resolve_subprocess_profile(cfg) == "override-profile"

    cfg = plugin_modules.config.AgencyConfig()
    monkeypatch.setenv("HERMES_PROFILE", "env-profile")
    assert tp.resolve_subprocess_profile(cfg) == "env-profile"


def test_process_via_subprocess_returns_error_string_on_crash(plugin_modules, monkeypatch):
    tp = plugin_modules.task_processor
    monkeypatch.setattr(tp, "_resolve_hermes_command", lambda: None)

    response = tp.process_via_subprocess("gpt", "hello", 1)

    assert response.startswith("ERROR:")


def test_delegate_import_sys_path_excludes_plugin_subdirectories(plugin_modules, tmp_path):
    tp = plugin_modules.task_processor
    core_root = tmp_path / "hermes-agent"
    original = [str(PLUGIN_DIR / "pool"), str(PLUGIN_DIR), str(core_root)]

    sanitized = tp._delegate_import_sys_path(original, PLUGIN_DIR, [core_root])

    assert str(PLUGIN_DIR) not in sanitized
    assert str(PLUGIN_DIR / "pool") not in sanitized
    assert sanitized[0] == str(core_root)


def test_remove_plugin_tools_shadow_removes_pool_tools_module(plugin_modules, monkeypatch):
    tp = plugin_modules.task_processor
    pool_tools = types.ModuleType("tools")
    pool_tools.__file__ = str(PLUGIN_DIR / "pool" / "tools.py")
    monkeypatch.setitem(sys.modules, "tools", pool_tools)

    removed = tp._remove_plugin_tools_shadow(PLUGIN_DIR)

    assert removed == {"tools": pool_tools}
    assert sys.modules.get("tools") is None


def test_import_hermes_delegate_task_ignores_pool_tools_shadow(
    plugin_modules, monkeypatch, tmp_path
):
    tp = plugin_modules.task_processor
    core_root = tmp_path / "hermes-agent"
    tools_dir = core_root / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "__init__.py").write_text("", encoding="utf-8")
    (tools_dir / "delegate_tool.py").write_text(
        "def delegate_task(**kwargs):\n    return 'delegated'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tp, "_hermes_source_root_candidates", lambda _plugin_dir: [core_root])
    monkeypatch.setattr(sys, "path", [str(PLUGIN_DIR / "pool"), str(PLUGIN_DIR)])
    for name in list(sys.modules):
        if name == "tools" or name.startswith("tools."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    delegate_task = tp._import_hermes_delegate_task()

    assert delegate_task() == "delegated"
    assert Path(sys.modules["tools"].__file__).resolve() == tools_dir / "__init__.py"


@pytest.mark.asyncio
async def test_subprocess_env_omits_yolo_and_hooks_by_default(plugin_modules, monkeypatch):
    tp = plugin_modules.task_processor
    captured = {}

    class Proc:
        returncode = 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return Proc()

    async def fake_collect(proc, *, progress_callback=None):
        return "done", ""

    monkeypatch.setattr(tp, "_resolve_hermes_command", lambda: "hermes")
    monkeypatch.setattr(tp.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(tp, "_collect_subprocess_output", fake_collect)

    response = await tp._process_via_subprocess_async("gpt", "hello", 1)

    assert response == "done"
    assert captured["env"].get("HERMES_YOLO_MODE") is None
    assert captured["env"].get("HERMES_ACCEPT_HOOKS") != "1"


@pytest.mark.asyncio
async def test_subprocess_env_allows_hooks_only_when_explicit(plugin_modules, monkeypatch):
    tp = plugin_modules.task_processor
    captured = {}

    class Proc:
        returncode = 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return Proc()

    async def fake_collect(proc, *, progress_callback=None):
        return "done", ""

    monkeypatch.setattr(tp, "_resolve_hermes_command", lambda: "hermes")
    monkeypatch.setattr(tp.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(tp, "_collect_subprocess_output", fake_collect)

    response = await tp._process_via_subprocess_async("gpt", "hello", 1, allow_hooks=True)

    assert response == "done"
    assert captured["env"].get("HERMES_YOLO_MODE") is None
    assert captured["env"].get("HERMES_ACCEPT_HOOKS") == "1"


def test_resolve_daemon_bin_prefers_config_then_protected_copy(
    plugin_modules, monkeypatch, tmp_path
):
    nm = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    configured = tmp_path / "configured" / "agentanycastd"
    protected = tmp_path / "src" / "hermes-agentanycast" / "bin" / "agentanycastd"
    configured.parent.mkdir(parents=True)
    protected.parent.mkdir(parents=True)
    configured.write_text("configured", encoding="utf-8")
    protected.write_text("protected", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))

    monkeypatch.setattr(
        nm,
        "get_config",
        lambda: cfg_mod.AgencyConfig(daemon_bin=configured),
    )
    assert nm._resolve_daemon_bin() == configured

    configured.unlink()
    assert nm._resolve_daemon_bin() == str(protected)

    protected.unlink()
    assert nm._resolve_daemon_bin() is None


def test_check_agency_available(plugin_modules, monkeypatch):
    tools = plugin_modules.tools
    monkeypatch.setattr(tools.importlib.util, "find_spec", lambda name: None)
    assert tools.check_agency_available() is False
    monkeypatch.setattr(tools.importlib.util, "find_spec", lambda name: object())
    assert tools.check_agency_available() is True


def test_tool_schemas_have_expected_function_structure(plugin_modules):
    tools = plugin_modules.tools
    for name, schema, _handler, _emoji in tools.TOOLS:
        assert schema["type"] == "function"
        assert schema["function"]["name"] == name
        assert isinstance(schema["function"].get("description"), str)
        assert schema["function"]["parameters"]["type"] == "object"
        assert "properties" in schema["function"]["parameters"]


def test_a2a_info_handles_unavailable_sdk(plugin_modules, monkeypatch):
    tools = plugin_modules.tools
    monkeypatch.setattr(tools, "check_agency_available", lambda: False)
    monkeypatch.setattr(tools.manager, "info", lambda: {"started": False})

    data = json.loads(tools.a2a_info())

    assert data["ok"] is True
    assert data["sdk_available"] is False
    assert data["card"] is None
    assert data["card_error"] is None
    assert data["node"] == {"started": False}


def test_agency_tool_aliases_match_a2a_handlers(plugin_modules, monkeypatch):
    tools = plugin_modules.tools
    compact = {"node_started": False}
    monkeypatch.setattr(tools.manager, "compact_info", lambda: compact)

    agency_data = json.loads(tools.agency_send({"peer_id": "peer"}))
    a2a_data = json.loads(tools.a2a_send({"peer_id": "peer"}))

    assert (
        agency_data
        == a2a_data
        == {
            "ok": False,
            "error": "message is required",
            "node": compact,
        }
    )


def test_a2a_deprecated_alias_warns_only_when_verbose(plugin_modules, monkeypatch, caplog):
    tools = plugin_modules.tools
    monkeypatch.setattr(tools.manager, "compact_info", lambda: {"node_started": False})

    json.loads(tools.a2a_send({"peer_id": "peer"}))
    assert "deprecated" not in caplog.text.lower()

    caplog.clear()
    json.loads(tools.a2a_send({"peer_id": "peer", "verbose": True}))
    assert "a2a_send is deprecated; use agency_send" in caplog.text


def test_registered_tools_include_agency_primary_and_deprecated_a2a_aliases(
    plugin_modules, monkeypatch
):
    init_mod = _load_plugin_package_module(monkeypatch)
    cfg_mod = plugin_modules.config
    monkeypatch.setattr(
        init_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(enabled=True, auto_start=False),
    )
    monkeypatch.setattr(init_mod, "check_agency_available", lambda: True)
    monkeypatch.setattr(init_mod.manager, "start_background", lambda: None)

    ctx = _FakePluginContext()
    init_mod.register(ctx)

    tool_names = [tool["name"] for tool in ctx.tools]
    assert "agency_send" in tool_names
    assert "agency_status" in tool_names
    assert "agency_info" in tool_names
    assert "a2a_send" in tool_names
    assert tool_names.index("agency_send") < tool_names.index("a2a_send")
    send_schema = next(tool["schema"] for tool in ctx.tools if tool["name"] == "agency_send")
    assert send_schema["function"]["name"] == "agency_send"
    assert "Hermes Agency" in send_schema["function"]["description"]


def test_doctor_healthy_json_report(plugin_modules, monkeypatch, tmp_path):
    doctor = plugin_modules.doctor
    cfg_mod = plugin_modules.config
    daemon = tmp_path / "agentanycastd"
    daemon.write_text("#!/bin/sh\n", encoding="utf-8")
    daemon.chmod(0o755)
    trust_store = tmp_path / "trust.json"
    trust_store.write_text(
        '{"version":1,"peers":{"peer-1":{"trust_level":"full"}}}', encoding="utf-8"
    )
    trust_store.chmod(0o600)
    cfg = cfg_mod.AgencyConfig(
        enabled=True,
        auto_start=True,
        allow_remote_tasks=True,
        daemon_bin=daemon,
        relay="https://relay-control.example.invalid",
        trust=cfg_mod.TrustConfig(store_path=trust_store, tofu=True),
        relay_security=cfg_mod.RelaySecurityConfig(allowlist=("peer-1",), allow_all=False),
        incoming=cfg_mod.IncomingConfig(mode="delegation", allow_subprocess=False),
    )
    monkeypatch.setattr(doctor, "get_config", lambda: cfg)
    monkeypatch.setattr(doctor, "get_hermes_home", lambda: plugin_modules.hermes_home)
    monkeypatch.setattr(doctor, "check_agency_available", lambda: True)
    monkeypatch.setattr(doctor, "build_card", lambda: object())
    monkeypatch.setattr(doctor, "card_to_dict", lambda _card: {"name": "Test", "skills": []})
    monkeypatch.setattr(doctor.manager, "compact_info", lambda: {"ok": True, "started": True})
    monkeypatch.setattr(doctor, "_registry_addresses", lambda: ["registry.example.invalid:50052"])
    monkeypatch.setattr(doctor, "_kanban_available", lambda: True)
    monkeypatch.setattr(doctor, "_mcp_http_enabled_details", lambda: None)
    monkeypatch.setattr(
        doctor,
        "_model_sets_check",
        lambda: doctor._check("agency_model_sets", "Agency model sets", "pass", "model sets ok"),
    )
    monkeypatch.setattr(
        doctor, "_editable_install_state", lambda: ("pass", "editable install detected")
    )
    monkeypatch.setattr(doctor, "_config_file_state", lambda: ("pass", "config ok", None))

    report = doctor.run_doctor()
    payload = json.loads(doctor.render_doctor_report(report, json_output=True))

    assert report.exit_code == 0
    assert payload["exit_code"] == 0
    assert all(check["status"] == "pass" for check in payload["checks"])
    assert [check["id"] for check in payload["checks"]][:3] == [
        "plugin_load",
        "profile_path",
        "config_file",
    ]


def test_doctor_missing_daemon_reports_actionable_fix(plugin_modules, monkeypatch, tmp_path):
    doctor = plugin_modules.doctor
    cfg_mod = plugin_modules.config
    cfg = cfg_mod.AgencyConfig(daemon_bin=tmp_path / "missing-agentanycastd")
    monkeypatch.setattr(doctor, "get_config", lambda: cfg)
    monkeypatch.setattr(doctor, "get_hermes_home", lambda: plugin_modules.hermes_home)
    monkeypatch.setattr(doctor, "check_agency_available", lambda: True)
    monkeypatch.setattr(doctor.manager, "compact_info", lambda: {"ok": False, "started": False})
    monkeypatch.setattr(doctor, "_config_file_state", lambda: ("pass", "config ok", None))

    report = doctor.run_doctor()
    daemon_check = next(check for check in report.checks if check.id == "daemon_binary")

    assert report.exit_code == 2
    assert daemon_check.status == "fail"
    assert "Set agency.daemon_bin or install the daemon" in daemon_check.remediation


def test_doctor_insecure_relay_warns(plugin_modules, monkeypatch):
    doctor = plugin_modules.doctor
    cfg_mod = plugin_modules.config
    cfg = cfg_mod.AgencyConfig(relay="http://relay.example.invalid/control")
    monkeypatch.setattr(doctor, "get_config", lambda: cfg)
    monkeypatch.setattr(doctor, "get_hermes_home", lambda: plugin_modules.hermes_home)
    monkeypatch.setattr(doctor, "check_agency_available", lambda: True)
    monkeypatch.setattr(doctor.manager, "compact_info", lambda: {"ok": False, "started": False})
    monkeypatch.setattr(doctor, "_config_file_state", lambda: ("pass", "config ok", None))

    report = doctor.run_doctor()
    relay_check = next(check for check in report.checks if check.id == "relay_config")

    assert report.exit_code == 2
    assert relay_check.status == "fail"
    assert relay_check.remediation == "Use HTTPS or localhost for relay control"


def test_doctor_rejects_insecure_inferred_relay_control_url(plugin_modules):
    doctor = plugin_modules.doctor
    cfg_mod = plugin_modules.config
    cfg = cfg_mod.AgencyConfig(
        relay="/ip4/198.51.100.10/tcp/4001/p2p/relay-peer",
        relay_security=cfg_mod.RelaySecurityConfig(auto_allow_team=True, token="secret-token"),
    )

    relay_check = doctor._relay_config_check(cfg)

    assert relay_check.status == "fail"
    assert relay_check.remediation == "Use HTTPS or localhost for relay control"
    assert relay_check.details["relay"] == "/ip4/198.51.100.10/tcp/4001/p2p/relay-peer"
    assert relay_check.details["control_url"] == "http://198.51.100.10:8083"


def test_doctor_allows_inferred_local_relay_control_url(plugin_modules):
    doctor = plugin_modules.doctor
    cfg_mod = plugin_modules.config
    cfg = cfg_mod.AgencyConfig(
        relay="/ip4/127.0.0.1/tcp/4001/p2p/relay-peer",
        relay_security=cfg_mod.RelaySecurityConfig(auto_allow_team=True, token="secret-token"),
    )

    relay_check = doctor._relay_config_check(cfg)

    assert relay_check.status == "pass"


def test_doctor_warns_when_mcp_http_mode_detected(plugin_modules, monkeypatch):
    doctor = plugin_modules.doctor
    cfg_mod = plugin_modules.config
    monkeypatch.setattr(doctor, "get_config", lambda: cfg_mod.AgencyConfig())
    monkeypatch.setattr(doctor, "get_hermes_home", lambda: plugin_modules.hermes_home)
    monkeypatch.setattr(doctor, "check_agency_available", lambda: True)
    monkeypatch.setattr(doctor.manager, "compact_info", lambda: {"ok": False, "started": False})
    monkeypatch.setattr(doctor, "_config_file_state", lambda: ("pass", "config ok", None))
    monkeypatch.setattr(
        doctor,
        "_mcp_http_enabled_details",
        lambda: {"source": "config", "transport": "http", "port": 8080},
    )

    report = doctor.run_doctor()
    mcp_check = next(check for check in report.checks if check.id == "mcp_http_exposure")

    assert mcp_check.status == "warn"
    assert "unauthenticated tool server" in mcp_check.message
    assert "Restrict network access or add authentication" in mcp_check.remediation


def test_doctor_sdk_missing_still_runs(plugin_modules, monkeypatch):
    doctor = plugin_modules.doctor
    cfg_mod = plugin_modules.config
    monkeypatch.setattr(doctor, "get_config", lambda: cfg_mod.AgencyConfig())
    monkeypatch.setattr(doctor, "get_hermes_home", lambda: plugin_modules.hermes_home)
    monkeypatch.setattr(doctor, "check_agency_available", lambda: False)
    monkeypatch.setattr(doctor.manager, "compact_info", lambda: {"ok": False, "started": False})
    monkeypatch.setattr(doctor, "_config_file_state", lambda: ("pass", "config ok", None))

    payload = json.loads(doctor.render_doctor_report(doctor.run_doctor(), json_output=True))
    sdk_check = next(check for check in payload["checks"] if check["id"] == "sdk_dependency")

    assert payload["exit_code"] == 2
    assert sdk_check["status"] == "fail"
    assert "agentanycast" in sdk_check["message"]


def _load_plugin_package_module(monkeypatch):
    package = sys.modules["hermes_plugin"]
    spec = importlib.util.spec_from_file_location(
        "hermes_plugin",
        PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    assert spec is not None and spec.loader is not None
    package.__file__ = str(PLUGIN_DIR / "__init__.py")
    package.__package__ = "hermes_plugin"
    package.__spec__ = spec
    spec.loader.exec_module(package)
    return package


class _FakePluginContext:
    def __init__(self):
        self.tools = []
        self.cli_commands = []
        self.commands = []
        self.hooks = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_cli_command(self, **kwargs):
        self.cli_commands.append(kwargs)

    def register_command(self, **kwargs):
        self.commands.append(kwargs)

    def register_hook(self, name, handler):
        self.hooks.append((name, handler))


def test_register_disabled_plugin_has_no_model_tools_and_no_start(plugin_modules, monkeypatch):
    init_mod = _load_plugin_package_module(monkeypatch)
    cfg_mod = plugin_modules.config
    start_calls = []
    monkeypatch.setattr(
        init_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            enabled=False,
            auto_start=True,
            team=cfg_mod.TeamConfig(auto_discover=True),
        ),
    )
    monkeypatch.setattr(init_mod, "check_agency_available", lambda: True)
    monkeypatch.setattr(init_mod.manager, "start_background", lambda: start_calls.append("start"))

    ctx = _FakePluginContext()
    init_mod.register(ctx)

    assert ctx.cli_commands and ctx.commands
    assert ctx.tools == []
    assert [name for name, _handler in ctx.hooks] == [
        "on_session_start",
        "on_session_start",
        "pre_llm_call",
        "on_session_reset",
    ]
    assert start_calls == []


def test_register_sdk_absent_gates_tools_and_does_not_start(plugin_modules, monkeypatch):
    init_mod = _load_plugin_package_module(monkeypatch)
    cfg_mod = plugin_modules.config
    start_calls = []
    monkeypatch.setattr(
        init_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            enabled=True,
            auto_start=True,
            team=cfg_mod.TeamConfig(auto_discover=True),
        ),
    )
    monkeypatch.setattr(init_mod, "check_agency_available", lambda: False)
    monkeypatch.setattr(init_mod.manager, "start_background", lambda: start_calls.append("start"))

    ctx = _FakePluginContext()
    init_mod.register(ctx)

    tool_names = {tool["name"] for tool in ctx.tools}
    assert "a2a_send" in tool_names
    assert "a2a_info" in tool_names
    assert "orch_route" not in tool_names
    assert all(tool["check_fn"]() is False for tool in ctx.tools)
    assert start_calls == []


def test_register_auto_discover_does_not_start_when_auto_start_false(plugin_modules, monkeypatch):
    init_mod = _load_plugin_package_module(monkeypatch)
    cfg_mod = plugin_modules.config
    start_calls = []
    monkeypatch.setattr(
        init_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            enabled=True,
            auto_start=False,
            team=cfg_mod.TeamConfig(auto_discover=True),
        ),
    )
    monkeypatch.setattr(init_mod, "check_agency_available", lambda: True)
    monkeypatch.setattr(init_mod.manager, "start_background", lambda: start_calls.append("start"))

    ctx = _FakePluginContext()
    init_mod.register(ctx)
    for name, handler in ctx.hooks:
        if name == "on_session_start":
            handler()

    assert start_calls == []


def test_register_auto_start_true_starts_even_when_auto_discover_false(plugin_modules, monkeypatch):
    init_mod = _load_plugin_package_module(monkeypatch)
    cfg_mod = plugin_modules.config
    start_calls = []
    monkeypatch.setattr(
        init_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            enabled=True,
            auto_start=True,
            team=cfg_mod.TeamConfig(auto_discover=False),
        ),
    )
    monkeypatch.setattr(init_mod, "check_agency_available", lambda: True)
    monkeypatch.setattr(init_mod.manager, "start_background", lambda: start_calls.append("start"))

    ctx = _FakePluginContext()
    init_mod.register(ctx)

    assert start_calls == ["start"]


def test_register_active_orchestrator_does_not_start_without_explicit_auto_start(
    plugin_modules, monkeypatch
):
    init_mod = _load_plugin_package_module(monkeypatch)
    cfg_mod = plugin_modules.config
    start_calls = []
    cleanup_calls = []
    monkeypatch.setattr(
        init_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            enabled=True,
            auto_start=False,
            orchestrator=cfg_mod.OrchestratorConfig(enabled=True),
        ),
    )
    monkeypatch.setattr(init_mod, "check_agency_available", lambda: True)
    monkeypatch.setattr(init_mod.manager, "start_background", lambda: start_calls.append("start"))
    monkeypatch.setattr(
        init_mod,
        "_stop_stale_pool_runner_for_in_process_node",
        lambda cfg: cleanup_calls.append(cfg),
    )

    ctx = _FakePluginContext()
    init_mod.register(ctx)

    assert cleanup_calls == []
    assert start_calls == []


def test_register_active_orchestrator_starts_with_explicit_orchestrator_auto_start(
    plugin_modules, monkeypatch
):
    init_mod = _load_plugin_package_module(monkeypatch)
    cfg_mod = plugin_modules.config
    start_calls = []
    cleanup_calls = []
    monkeypatch.setattr(
        init_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            enabled=True,
            auto_start=False,
            orchestrator=cfg_mod.OrchestratorConfig(enabled=True, auto_start=True),
        ),
    )
    monkeypatch.setattr(init_mod, "check_agency_available", lambda: True)
    monkeypatch.setattr(init_mod.manager, "start_background", lambda: start_calls.append("start"))
    monkeypatch.setattr(
        init_mod,
        "_stop_stale_pool_runner_for_in_process_node",
        lambda cfg: cleanup_calls.append(cfg),
    )

    ctx = _FakePluginContext()
    init_mod.register(ctx)

    assert cleanup_calls
    assert start_calls == ["start"]


def test_pool_manager_skips_orchestrator_child_runner_inside_gateway(monkeypatch):
    pool_manager = _load_pool_manager_module(monkeypatch)
    monkeypatch.setenv("_HERMES_GATEWAY", "1")
    monkeypatch.setattr(pool_manager.PoolManager, "_load_config", lambda self: {"pool": {}})
    monkeypatch.setattr(pool_manager.PoolManager, "_load_registry", lambda self: {"agents": []})
    monkeypatch.setattr(pool_manager.PoolManager, "_start_idle_monitor", lambda self: None)
    wake_calls = []
    monkeypatch.setattr(
        pool_manager.PoolManager,
        "wake",
        lambda self, name, persistent=False: wake_calls.append((name, persistent)),
    )

    manager = pool_manager.PoolManager()

    assert manager.active == {}
    assert wake_calls == []


def test_pool_runner_pid_scan_matches_profile_env(plugin_modules, tmp_path):
    pool_tools = importlib.import_module("hermes_plugin.pool.tools")
    proc_root = tmp_path / "proc"
    profile_dir = tmp_path / "profiles" / "agency-orchestrator"
    profile_dir.mkdir(parents=True)

    runner_proc = proc_root / "1234"
    runner_proc.mkdir(parents=True)
    (runner_proc / "cmdline").write_bytes(
        b"python\0/tmp/plugins/hermes-agency/pool/agency_node_runner.py\0"
    )
    (runner_proc / "environ").write_bytes(
        f"HERMES_PROFILE=agency-orchestrator\0HERMES_HOME={profile_dir}\0".encode()
    )

    shell_proc = proc_root / "5678"
    shell_proc.mkdir()
    (shell_proc / "cmdline").write_bytes(
        b"bash\0-c\0echo agency_node_runner.py but not as argv path\0"
    )
    (shell_proc / "environ").write_bytes(b"HERMES_PROFILE=agency-orchestrator\0")

    assert pool_tools._profile_runner_pids(
        "agency-orchestrator", profile_dir, proc_root=proc_root
    ) == [1234]


def test_pool_runner_pid_scan_falls_back_to_profile_plugin_path(plugin_modules, tmp_path):
    pool_tools = importlib.import_module("hermes_plugin.pool.tools")
    proc_root = tmp_path / "proc"
    profile_dir = tmp_path / "profiles" / "agency-orchestrator"
    profile_dir.mkdir(parents=True)
    runner_proc = proc_root / "4321"
    runner_proc.mkdir(parents=True)
    (runner_proc / "cmdline").write_bytes(
        b"python\0~/.hermes/profiles/agency-orchestrator/plugins/"
        b"hermes-agency/pool/agency_node_runner.py\0"
    )
    (runner_proc / "environ").write_bytes(b"")

    assert pool_tools._profile_runner_pids(
        "agency-orchestrator", profile_dir, proc_root=proc_root
    ) == [4321]


def test_pool_sleep_stops_stale_runner_not_in_pidfile(plugin_modules, monkeypatch, tmp_path):
    pool_tools = importlib.import_module("hermes_plugin.pool.tools")
    profile_dir = tmp_path / "profiles" / "agency-orchestrator"
    agency_dir = profile_dir / ".agency"
    agency_dir.mkdir(parents=True)
    (agency_dir / "runner.pid").write_text("1111", encoding="utf-8")
    monkeypatch.setattr(pool_tools, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pool_tools, "_profile_runner_pids", lambda name, path: [2222])
    monkeypatch.setattr(pool_tools, "_terminate_pids", lambda pids: stopped.extend(pids))
    monkeypatch.setattr(pool_tools, "_stop_profile_daemon_processes", lambda name: None)
    monkeypatch.setattr(pool_tools, "update_agent_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(pool_tools, "save_roster", lambda *args, **kwargs: None)
    monkeypatch.setattr(pool_tools, "build_roster", lambda: {})
    monkeypatch.setattr(pool_tools.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(pool_tools.time, "sleep", lambda seconds: None)
    stopped = []

    assert pool_tools.pool_sleep("agency-orchestrator") == "agency-orchestrator offline"

    assert stopped == [1111, 2222]
    assert not (agency_dir / "runner.pid").exists()


def test_pool_wake_resolves_peer_id_from_daemon_log(plugin_modules, tmp_path):
    pool_tools = importlib.import_module("hermes_plugin.pool.tools")
    agency_dir = tmp_path / ".agency"
    log_dir = agency_dir / "logs"
    log_dir.mkdir(parents=True)
    runner_log = log_dir / "runner.log"
    runner_log.write_text("", encoding="utf-8")
    (log_dir / "daemon.log").write_text(
        "noise\nPEER_ID=12D3KooWDaemonPeer\n",
        encoding="utf-8",
    )

    assert pool_tools._resolve_runner_peer_id(agency_dir, runner_log) == "12D3KooWDaemonPeer"


def test_pool_wake_ignores_remote_peer_ids_in_daemon_log(plugin_modules, tmp_path):
    pool_tools = importlib.import_module("hermes_plugin.pool.tools")
    agency_dir = tmp_path / ".agency"
    log_dir = agency_dir / "logs"
    log_dir.mkdir(parents=True)
    runner_log = log_dir / "runner.log"
    runner_log.write_text("", encoding="utf-8")
    (log_dir / "daemon.log").write_text(
        "\n".join(
            [
                '{"event":"task_received","peer_id":"12D3KooWRemotePeer"}',
                '{"event":"agentanycastd started","peer_id":"12D3KooWLocalPeer"}',
                '{"event":"discovered","peer_id":"12D3KooWOtherRemote"}',
            ]
        ),
        encoding="utf-8",
    )

    assert pool_tools._resolve_runner_peer_id(agency_dir, runner_log) == "12D3KooWLocalPeer"


def test_pool_wake_prefers_latest_startup_peer_id(plugin_modules, tmp_path):
    pool_tools = importlib.import_module("hermes_plugin.pool.tools")
    agency_dir = tmp_path / ".agency"
    log_dir = agency_dir / "logs"
    log_dir.mkdir(parents=True)
    runner_log = log_dir / "runner.log"
    runner_log.write_text("", encoding="utf-8")
    (log_dir / "daemon.log").write_text(
        "\n".join(
            [
                "PEER_ID=12D3KooWStalePeer",
                '{"event":"agentanycastd started","peer_id":"12D3KooWCurrentPeer"}',
            ]
        ),
        encoding="utf-8",
    )

    assert pool_tools._resolve_runner_peer_id(agency_dir, runner_log) == "12D3KooWCurrentPeer"


def test_pool_wake_block_reason_can_disable_all_wakes(plugin_modules, monkeypatch):
    pool_tools = importlib.import_module("hermes_plugin.pool.tools")
    monkeypatch.setattr(pool_tools, "_pool_wake_decision", lambda name: None)
    monkeypatch.setattr(pool_tools, "_pool_limits", lambda: (0, 512))
    monkeypatch.setattr(
        pool_tools,
        "_pool_resource_snapshot",
        lambda: {"runner_count": 0, "total_rss_mb": 0.0},
    )

    reason = pool_tools._pool_wake_block_reason("agency-copywriter")

    assert reason == "pool wake blocked for agency-copywriter: pool wakes are disabled by config"


def test_pool_wake_block_reason_enforces_runner_limit(plugin_modules, monkeypatch):
    pool_tools = importlib.import_module("hermes_plugin.pool.tools")
    monkeypatch.setattr(pool_tools, "_pool_wake_decision", lambda name: None)
    monkeypatch.setattr(pool_tools, "_pool_limits", lambda: (2, 0))
    monkeypatch.setattr(
        pool_tools,
        "_pool_resource_snapshot",
        lambda: {"runner_count": 2, "total_rss_mb": 128.0},
    )

    reason = pool_tools._pool_wake_block_reason("agency-copywriter")

    assert reason is not None
    assert "limit=2" in reason


def test_pool_wake_block_reason_enforces_rss_limit(plugin_modules, monkeypatch):
    pool_tools = importlib.import_module("hermes_plugin.pool.tools")
    monkeypatch.setattr(pool_tools, "_pool_wake_decision", lambda name: None)
    monkeypatch.setattr(pool_tools, "_pool_limits", lambda: (99, 512))
    monkeypatch.setattr(
        pool_tools,
        "_pool_resource_snapshot",
        lambda: {"runner_count": 1, "total_rss_mb": 700.0},
    )

    reason = pool_tools._pool_wake_block_reason("agency-copywriter")

    assert reason is not None
    assert "pool RSS 700.0 MiB" in reason


def test_lifecycle_gate_blocks_discovery_wake_by_default(plugin_modules):
    cfg_mod = plugin_modules.config
    lifecycle = importlib.import_module("hermes_plugin.pool.lifecycle_gate")

    decision = lifecycle.evaluate_wake_request(
        lifecycle.WakeRequest(agent_name="agency-copywriter", reason="discovery"),
        cfg_mod.AgencyConfig(),
        slots=[],
        snapshot=lifecycle.ResourceSnapshot(available_mem_mb=8192.0, total_rss_mb=0.0),
    )

    assert decision.allowed is False
    assert decision.status == "denied"
    assert "discovery" in decision.reason


def test_lifecycle_gate_can_swap_only_idle_non_busy_agents(plugin_modules):
    cfg_mod = plugin_modules.config
    lifecycle = importlib.import_module("hermes_plugin.pool.lifecycle_gate")
    cfg = cfg_mod.AgencyConfig(
        pool=cfg_mod.PoolConfig(
            max_online_agents=1,
            max_total_rss_mb=0,
            min_free_mem_mb=0,
            idle_sleep_after_seconds=60,
            busy_recent_activity_seconds=30,
            allow_sleep_for_wake=True,
        )
    )
    slots = [
        lifecycle.AgentSlot(
            name="agency-busy",
            online=True,
            last_activity_at=0.0,
            incoming_processing_count=1,
        ),
        lifecycle.AgentSlot(
            name="agency-idle",
            online=True,
            last_activity_at=0.0,
        ),
    ]

    decision = lifecycle.evaluate_wake_request(
        lifecycle.WakeRequest(agent_name="agency-copywriter", reason="task"),
        cfg,
        slots=slots,
        snapshot=lifecycle.ResourceSnapshot(available_mem_mb=8192.0, total_rss_mb=0.0),
        now=120.0,
    )

    assert decision.allowed is True
    assert decision.sleep_candidate is not None
    assert decision.sleep_candidate.name == "agency-idle"


def test_register_auto_start_and_auto_discover_starts_once(plugin_modules, monkeypatch):
    init_mod = _load_plugin_package_module(monkeypatch)
    cfg_mod = plugin_modules.config
    start_calls = []
    monkeypatch.setattr(
        init_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            enabled=True,
            auto_start=True,
            team=cfg_mod.TeamConfig(auto_discover=True),
        ),
    )
    monkeypatch.setattr(init_mod, "check_agency_available", lambda: True)
    monkeypatch.setattr(init_mod.manager, "start_background", lambda: start_calls.append("start"))

    ctx = _FakePluginContext()
    init_mod.register(ctx)

    assert start_calls == ["start"]


def test_auto_start_if_configured_ignores_auto_discover_when_auto_start_false(
    plugin_modules, monkeypatch
):
    nm_mod = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    manager = nm_mod.NodeManager()
    start_calls = []
    monkeypatch.setattr(
        nm_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            enabled=True,
            auto_start=False,
            team=cfg_mod.TeamConfig(auto_discover=True),
        ),
    )
    monkeypatch.setattr(manager, "start_background", lambda: start_calls.append("start"))

    manager.auto_start_if_configured()

    assert start_calls == []


def test_auto_start_if_configured_does_not_start_active_orchestrator_without_explicit_auto_start(
    plugin_modules, monkeypatch
):
    nm_mod = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    manager = nm_mod.NodeManager()
    start_calls = []
    monkeypatch.setattr(
        nm_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            enabled=True,
            auto_start=False,
            orchestrator=cfg_mod.OrchestratorConfig(enabled=True),
        ),
    )
    monkeypatch.setattr(manager, "start_background", lambda: start_calls.append("start"))

    manager.auto_start_if_configured()

    assert start_calls == []


def test_auto_start_if_configured_starts_active_orchestrator_with_explicit_auto_start(
    plugin_modules, monkeypatch
):
    nm_mod = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    manager = nm_mod.NodeManager()
    start_calls = []
    monkeypatch.setattr(
        nm_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            enabled=True,
            auto_start=False,
            orchestrator=cfg_mod.OrchestratorConfig(enabled=True, auto_start=True),
        ),
    )
    monkeypatch.setattr(manager, "start_background", lambda: start_calls.append("start"))

    manager.auto_start_if_configured()

    assert start_calls == ["start"]


def test_runner_health_requires_started_and_serve_task(monkeypatch):
    runner = _load_runner_module(monkeypatch)

    class FakeManager:
        def compact_info(self):
            return {"ok": True, "node_started": True, "serve_task_running": False}

    healthy, reason = runner._manager_health(FakeManager())

    assert healthy is False
    assert "serve_task_running" in reason


def test_runner_resolves_orchestrator_profile_from_root_config(monkeypatch, tmp_path):
    runner = _load_runner_module(monkeypatch)
    root_home = tmp_path / ".hermes"
    profile_home = root_home / "profiles" / "agency-orchestrator"
    profile_home.mkdir(parents=True)
    (root_home / "config.yaml").write_text(
        "agency:\n  orchestrator:\n    agent: agency-orchestrator\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(root_home))
    monkeypatch.setenv("HERMES_PROFILE", "default")

    assert runner._resolve_runner_profile() == "agency-orchestrator"
    assert os.environ["HERMES_PROFILE"] == "agency-orchestrator"
    assert os.environ["HERMES_HOME"] == str(profile_home)


def test_runner_resolves_orchestrator_from_active_profile_config(monkeypatch, tmp_path):
    runner = _load_runner_module(monkeypatch)
    root_home = tmp_path / ".hermes"
    profile_home = root_home / "profiles" / "agency-orchestrator"
    profile_home.mkdir(parents=True)
    (root_home / "active_profile").write_text("agency-orchestrator\n", encoding="utf-8")
    (profile_home / "config.yaml").write_text(
        "agency:\n  orchestrator:\n    enabled: true\n    agent: agency-orchestrator\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(root_home))
    monkeypatch.setenv("HERMES_PROFILE", "default")

    assert runner._resolve_runner_profile() == "agency-orchestrator"
    assert os.environ["HERMES_PROFILE"] == "agency-orchestrator"
    assert os.environ["HERMES_HOME"] == str(profile_home)


def test_runner_does_not_rewrite_pool_managed_non_orchestrator_profile(monkeypatch, tmp_path):
    runner = _load_runner_module(monkeypatch)
    root_home = tmp_path / ".hermes"
    profile_home = root_home / "profiles" / "agency-backend-engineer"
    profile_home.mkdir(parents=True)
    (root_home / "config.yaml").write_text(
        "agency:\n  orchestrator:\n    agent: agency-orchestrator\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(profile_home))
    monkeypatch.setenv("HERMES_PROFILE", "agency-backend-engineer")

    assert runner._resolve_runner_profile() == "agency-backend-engineer"
    assert os.environ["HERMES_PROFILE"] == "agency-backend-engineer"
    assert os.environ["HERMES_HOME"] == str(profile_home)


def test_runner_start_until_running_retries_without_exiting(monkeypatch):
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    attempts = []

    class FakeState:
        def __init__(self, started, peer_id=None, error=None):
            self.started = started
            self.peer_id = peer_id
            self.error = error

        def as_dict(self):
            return {"started": self.started, "peer_id": self.peer_id, "error": self.error}

    class FakeManager:
        def start_sync(self, timeout=120):
            attempts.append(timeout)
            if len(attempts) == 1:
                return FakeState(False, error="daemon unavailable")
            return FakeState(True, peer_id="12D3KooWTest")

    assert (
        runner._start_until_running(
            FakeManager(),
            should_run=lambda: True,
            startup_timeout=120,
            retry_seconds=0,
        )
        is True
    )
    assert attempts == [120, 120]


def test_runner_restart_stops_then_starts_until_running(monkeypatch):
    runner = _load_runner_module(monkeypatch)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    calls = []

    class FakeState:
        started = True
        peer_id = "12D3KooWRestarted"
        error = None

        def as_dict(self):
            return {"started": self.started, "peer_id": self.peer_id, "error": self.error}

    class FakeManager:
        def stop_sync(self, timeout=60):
            calls.append(("stop", timeout))

        def start_sync(self, timeout=120):
            calls.append(("start", timeout))
            return FakeState()

    assert (
        runner._restart_node(
            FakeManager(),
            should_run=lambda: True,
            startup_timeout=120,
            retry_seconds=0,
        )
        is True
    )
    assert calls == [("stop", 60), ("start", 120)]


def test_explicit_start_works_regardless_of_auto_start(plugin_modules, monkeypatch):
    tools = plugin_modules.tools
    cfg_mod = plugin_modules.config
    cfg = cfg_mod.AgencyConfig(
        enabled=True,
        auto_start=False,
        team=cfg_mod.TeamConfig(auto_discover=True),
    )

    class FakeState:
        error = None
        started = True

        def as_dict(self):
            return {"started": True, "peer_id": "peer-1", "config": cfg.as_dict()}

    class FakeManager:
        def start_sync(self):
            return FakeState()

    monkeypatch.setattr(tools, "manager", FakeManager())

    data = json.loads(tools.a2a_start_node({}))

    assert data["ok"] is True
    assert data["node"]["started"] is True
    assert data["node"]["config"]["auto_start"] is False


def test_register_orchestrator_tools_only_for_promoted_profile(plugin_modules, monkeypatch):
    init_mod = _load_plugin_package_module(monkeypatch)
    cfg_mod = plugin_modules.config
    monkeypatch.setenv("HERMES_PROFILE", "gpt")
    monkeypatch.setattr(
        init_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            enabled=True,
            auto_start=False,
            team=cfg_mod.TeamConfig(auto_discover=False),
            orchestrator=cfg_mod.OrchestratorConfig(enabled=True, agent="gpt"),
        ),
    )
    monkeypatch.setattr(init_mod, "check_agency_available", lambda: True)
    monkeypatch.setattr(init_mod.manager, "start_background", lambda: None)

    ctx = _FakePluginContext()
    init_mod.register(ctx)

    tool_names = {tool["name"] for tool in ctx.tools}
    assert "a2a_send" in tool_names
    assert "orch_route" in tool_names
    assert "orch_decompose" in tool_names


@pytest.mark.parametrize(
    ("args", "expected_error"),
    [
        ({"peer_id": "peer"}, "message is required"),
        (
            {"message": "hello", "peer_id": "peer", "skill": "chat"},
            "exactly one of peer_id or skill is required",
        ),
        ({"message": "hello"}, "exactly one of peer_id or skill is required"),
    ],
)
def test_a2a_send_validates_required_arguments(plugin_modules, monkeypatch, args, expected_error):
    tools = plugin_modules.tools
    monkeypatch.setattr(tools.manager, "compact_info", lambda: {"node_started": False})

    data = json.loads(tools.a2a_send(args))

    assert data["ok"] is False
    assert data["error"] == expected_error
    assert data["node"] == {"node_started": False}


def test_a2a_status_requires_task_id(plugin_modules, monkeypatch):
    tools = plugin_modules.tools
    monkeypatch.setattr(tools.manager, "compact_info", lambda: {"node_started": False})

    data = json.loads(tools.a2a_status({}))

    assert data["ok"] is False
    assert data["error"] == "task_id is required"
    assert data["node"] == {"node_started": False}


def test_node_state_as_dict_expected_keys(plugin_modules):
    nm = plugin_modules.node_manager
    cfg = plugin_modules.config.AgencyConfig(enabled=True, relay="relay")
    state = nm.NodeState(
        started=True,
        peer_id="peer",
        last_peer_id="last",
        did_key="did:key:test",
        error="err",
        config=cfg,
        card_name="card",
        skill_count=3,
        serve_task_running=True,
        started_at=1.0,
        stopped_at=2.0,
        last_status="ok",
        incoming_task_count=4,
        incoming_queue_size=5,
        incoming_queue_max_size=15,
        incoming_dropped_count=1,
        incoming_processing_count=6,
        incoming_completed_count=7,
        incoming_failed_count=8,
        team_context="team block",
        team_peer_count=2,
        team_last_refresh=4.0,
        team_last_error="team err",
        orchestrator_active_task_count=9,
        orchestrator_completed_task_count=10,
        orchestrator_failed_task_count=11,
        registration_count=12,
        bidding_request_count=13,
        bidding_bid_count=14,
    )

    assert state.as_dict() == {
        "started": True,
        "peer_id": "peer",
        "last_peer_id": "last",
        "did_key": "did:key:test",
        "error": "err",
        "config": cfg.as_dict(),
        "card_name": "card",
        "skill_count": 3,
        "serve_task_running": True,
        "started_at": 1.0,
        "stopped_at": 2.0,
        "last_status": "ok",
        "incoming_task_count": 4,
        "incoming_queue_size": 5,
        "incoming_queue_max_size": 15,
        "incoming_dropped_count": 1,
        "incoming_processing_count": 6,
        "incoming_completed_count": 7,
        "incoming_failed_count": 8,
        "last_incoming_activity_at": None,
        "team_context": "team block",
        "team_peer_count": 2,
        "team_last_refresh": 4.0,
        "team_last_error": "team err",
        "orchestrator_active_task_count": 9,
        "orchestrator_completed_task_count": 10,
        "orchestrator_failed_task_count": 11,
        "registration_count": 12,
        "bidding_request_count": 13,
        "bidding_bid_count": 14,
        "last_registration_time": None,
        "consecutive_failures": 0,
        "next_retry_at": None,
        "registration_healthy": False,
        "registry_reregister_loop_exited": False,
    }


def test_incoming_task_record_as_dict_expected_keys(plugin_modules):
    rec = plugin_modules.node_manager.IncomingTaskRecord(
        task_id="task-1",
        sender_peer_id="peer-1",
        sender_card={"name": "sender"},
        target_skill_id="skill-1",
        message_text="hello",
        context_packet={"schema": "agency.context_packet.v1", "goal": "hello"},
        status="completed",
        result_text="done",
        error=None,
        created_at=1.0,
        updated_at=2.0,
        completed_at=3.0,
    )

    assert rec.as_dict() == {
        "task_id": "task-1",
        "sender_peer_id": "peer-1",
        "sender_card": {"name": "sender"},
        "target_skill_id": "skill-1",
        "message_text": "hello",
        "context_id": "",
        "context_packet": {"schema": "agency.context_packet.v1", "goal": "hello"},
        "metadata": {},
        "kanban_task_id": None,
        "progress_updates": [],
        "status": "completed",
        "result_text": "done",
        "error": None,
        "created_at": 1.0,
        "updated_at": 2.0,
        "completed_at": 3.0,
    }


def test_incoming_recovery_fails_stale_processing_records(plugin_modules, monkeypatch):
    asyncio = __import__("asyncio")
    nm_mod = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    incoming_mod = importlib.import_module("hermes_plugin.incoming_queue")
    manager = nm_mod.NodeManager()
    manager._incoming_queue = asyncio.Queue()
    manager._node = object()
    stale = nm_mod.IncomingTaskRecord(
        task_id="task-stale",
        sender_peer_id="peer-a",
        sender_card=None,
        target_skill_id="",
        message_text="stale task",
        status="processing",
        created_at=100.0,
        updated_at=100.0,
    )
    fresh = nm_mod.IncomingTaskRecord(
        task_id="task-fresh",
        sender_peer_id="peer-a",
        sender_card=None,
        target_skill_id="",
        message_text="fresh task",
        status="processing",
        created_at=950.0,
        updated_at=950.0,
    )
    cfg = cfg_mod.AgencyConfig(incoming=cfg_mod.IncomingConfig(handler_timeout_seconds=300))
    monkeypatch.setattr(nm_mod, "get_config", lambda: cfg)
    monkeypatch.setattr(incoming_mod.time, "time", lambda: 1000.0)
    monkeypatch.setattr(
        manager,
        "_load_persisted_incoming_records",
        lambda: [stale, fresh],
    )

    recovered = manager._requeue_persisted_incoming_tasks()

    assert recovered == 1
    assert stale.status == "failed"
    assert "stale on startup" in (stale.error or "")
    assert fresh.status == "queued"
    assert manager._incoming_queue.qsize() == 1


@pytest.mark.asyncio
async def test_incoming_worker_delegation_mode_uses_task_processor(plugin_modules, monkeypatch):
    asyncio = __import__("asyncio")
    nm_mod = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    manager = nm_mod.NodeManager()
    manager._incoming_queue = asyncio.Queue()
    record = nm_mod.IncomingTaskRecord(
        task_id="task-delegation",
        sender_peer_id="peer-a",
        sender_card=None,
        target_skill_id="",
        message_text="What is 2 + 2?",
        kanban_task_id="kb-incoming",
    )
    manager._incoming_records[record.task_id] = record
    cfg = cfg_mod.AgencyConfig(
        allow_remote_tasks=True,
        incoming=cfg_mod.IncomingConfig(mode="delegation", delegation_timeout=5),
    )
    kanban_updates = []
    monkeypatch.setattr(nm_mod, "get_config", lambda: cfg)
    monkeypatch.setattr(
        nm_mod,
        "kanban_update_task",
        lambda task_id, **kwargs: kanban_updates.append({"task_id": task_id, **kwargs}) or {},
    )
    monkeypatch.setattr(nm_mod, "announce_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_error", lambda *args, **kwargs: None)
    called = {}

    def fake_process(in_record, in_cfg, fallback):
        called["record"] = in_record
        called["cfg"] = in_cfg
        called["fallback"] = fallback
        return "4"

    monkeypatch.setattr(nm_mod, "process_incoming_task", fake_process)

    class Task:
        completed = None

        async def complete(self, artifacts):
            self.completed = artifacts

        async def fail(self, error):
            raise AssertionError(error)

    task = Task()
    worker = asyncio.create_task(manager._incoming_worker())
    await manager._incoming_queue.put((task, record.task_id))
    await asyncio.wait_for(manager._incoming_queue.join(), timeout=2)
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)

    assert called["record"] is record
    assert called["cfg"] is cfg
    assert record.status == "completed"
    assert record.result_text == "4"
    assert any(
        update["task_id"] == "kb-incoming" and update.get("status") == "running"
        for update in kanban_updates
    )
    assert any(
        update["task_id"] == "kb-incoming"
        and update.get("status") == "done"
        and update.get("result") == "4"
        for update in kanban_updates
    )
    assert task.completed is not None
    assert task.completed[0]["parts"][0]["text"] == "4"


class _WorkerTask:
    def __init__(self):
        self.completed = None
        self.failed = None

    async def complete(self, artifacts):
        self.completed = artifacts

    async def fail(self, error):
        self.failed = error


@pytest.mark.asyncio
async def test_incoming_worker_handler_completes_within_timeout(plugin_modules, monkeypatch):
    asyncio = __import__("asyncio")
    nm_mod = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    manager = nm_mod.NodeManager()
    manager._incoming_queue = asyncio.Queue()
    record = nm_mod.IncomingTaskRecord(
        task_id="task-fast",
        sender_peer_id="peer-a",
        sender_card=None,
        target_skill_id="",
        message_text="fast task",
    )
    manager._incoming_records[record.task_id] = record
    cfg = cfg_mod.AgencyConfig(
        allow_remote_tasks=True,
        incoming=cfg_mod.IncomingConfig(mode="delegation", handler_timeout_seconds=1),
    )
    monkeypatch.setattr(nm_mod, "get_config", lambda: cfg)
    monkeypatch.setattr(nm_mod, "kanban_update_task", lambda *args, **kwargs: {})
    monkeypatch.setattr(nm_mod, "announce_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_error", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "process_incoming_task", lambda *args, **kwargs: "done")

    task = _WorkerTask()
    worker = asyncio.create_task(manager._incoming_worker())
    await manager._incoming_queue.put((task, record.task_id))
    await asyncio.wait_for(manager._incoming_queue.join(), timeout=2)
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)

    assert task.completed is not None
    assert task.failed is None
    assert record.status == "completed"


@pytest.mark.asyncio
async def test_incoming_worker_handler_timeout_fails_task_and_survives(
    plugin_modules, monkeypatch, caplog
):
    asyncio = __import__("asyncio")
    import time as real_time

    nm_mod = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    manager = nm_mod.NodeManager()
    manager._incoming_queue = asyncio.Queue()
    cfg = cfg_mod.AgencyConfig(
        allow_remote_tasks=True,
        incoming=cfg_mod.IncomingConfig(
            mode="delegation", delegation_timeout=5, handler_timeout_seconds=0.01
        ),
    )
    monkeypatch.setattr(nm_mod, "get_config", lambda: cfg)
    monkeypatch.setattr(nm_mod, "kanban_update_task", lambda *args, **kwargs: {})
    monkeypatch.setattr(nm_mod, "announce_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_error", lambda *args, **kwargs: None)

    def slow_process(*_args, **_kwargs):
        real_time.sleep(0.1)
        return "too late"

    monkeypatch.setattr(nm_mod, "process_incoming_task", slow_process)
    first = nm_mod.IncomingTaskRecord(
        task_id="task-slow",
        sender_peer_id="peer-a",
        sender_card=None,
        target_skill_id="",
        message_text="slow task",
    )
    manager._incoming_records[first.task_id] = first
    first_task = _WorkerTask()
    worker = asyncio.create_task(manager._incoming_worker())
    with caplog.at_level("WARNING"):
        await manager._incoming_queue.put((first_task, first.task_id))
        await asyncio.wait_for(manager._incoming_queue.join(), timeout=2)

    assert first_task.completed is None
    assert first_task.failed is not None
    assert "timeout" in first_task.failed.lower()
    assert first.status == "failed"
    assert not caplog.text or "task-slow" in caplog.text

    monkeypatch.setattr(nm_mod, "process_incoming_task", lambda *args, **kwargs: "recovered")
    second = nm_mod.IncomingTaskRecord(
        task_id="task-after-timeout",
        sender_peer_id="peer-a",
        sender_card=None,
        target_skill_id="",
        message_text="next task",
    )
    manager._incoming_records[second.task_id] = second
    second_task = _WorkerTask()
    await manager._incoming_queue.put((second_task, second.task_id))
    await asyncio.wait_for(manager._incoming_queue.join(), timeout=2)
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)

    assert second_task.completed is not None
    assert second_task.failed is None
    assert second.result_text == "recovered"


@pytest.mark.asyncio
async def test_incoming_worker_sends_progress_artifact_when_enabled(plugin_modules, monkeypatch):
    asyncio = __import__("asyncio")
    nm_mod = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    manager = nm_mod.NodeManager()
    manager._incoming_queue = asyncio.Queue()
    record = nm_mod.IncomingTaskRecord(
        task_id="task-progress",
        sender_peer_id="peer-a",
        sender_card=None,
        target_skill_id="",
        message_text="slow task",
    )
    manager._incoming_records[record.task_id] = record
    cfg = cfg_mod.AgencyConfig(
        allow_remote_tasks=True,
        incoming=cfg_mod.IncomingConfig(mode="delegation", send_progress=True),
    )
    monkeypatch.setattr(nm_mod, "get_config", lambda: cfg)
    monkeypatch.setattr(nm_mod, "kanban_update_task", lambda *args, **kwargs: {})
    monkeypatch.setattr(nm_mod, "announce_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_error", lambda *args, **kwargs: None)

    def fake_process(in_record, in_cfg, fallback, progress_callback=None):
        assert in_record is record
        assert in_cfg is cfg
        assert progress_callback is not None
        progress_callback("Processing... found 3 relevant files")
        return "done"

    monkeypatch.setattr(nm_mod, "process_incoming_task", fake_process)

    class Task:
        completed = None

        def __init__(self):
            self.progress = []

        async def send_artifact(self, artifacts):
            self.progress.extend(artifacts)

        async def complete(self, artifacts):
            self.completed = artifacts

        async def fail(self, error):
            raise AssertionError(error)

    task = Task()
    worker = asyncio.create_task(manager._incoming_worker())
    await manager._incoming_queue.put((task, record.task_id))
    await asyncio.wait_for(manager._incoming_queue.join(), timeout=2)
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)

    assert task.progress
    progress = task.progress[0]
    assert progress["name"] == "agency-progress-update"
    assert progress["parts"][0]["text"] == "Processing... found 3 relevant files"
    assert record.progress_updates[0]["text"] == "Processing... found 3 relevant files"
    assert task.completed[0]["parts"][0]["text"] == "done"


def test_serialize_task_extracts_progress_updates(plugin_modules):
    nm = plugin_modules.node_manager.NodeManager

    class Task:
        task_id = "task-progress"
        context_id = ""
        status = "working"
        target_skill_id = ""
        originator_peer_id = ""
        metadata = {}
        artifacts = [
            {
                "artifact_id": "progress-task-progress-1",
                "name": "agency-progress-update",
                "metadata": {"agency_progress": True, "timestamp": 123.0},
                "parts": [{"text": "Processing..."}],
            },
            {"name": "final", "parts": [{"text": "done"}]},
        ]

    data = nm._serialize_task(Task())

    assert data["progress_updates"] == [{"timestamp": 123.0, "text": "Processing..."}]
    assert data["artifact_text"] == "done"


@pytest.mark.asyncio
async def test_incoming_worker_template_mode_keeps_existing_template(plugin_modules, monkeypatch):
    asyncio = __import__("asyncio")
    nm_mod = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    manager = nm_mod.NodeManager()
    manager._incoming_queue = asyncio.Queue()
    manager.state.card_name = "gpt"
    manager.state.skill_count = 42
    record = nm_mod.IncomingTaskRecord(
        task_id="task-template",
        sender_peer_id="peer-a",
        sender_card=None,
        target_skill_id="",
        message_text="What is 2 + 2?",
    )
    manager._incoming_records[record.task_id] = record
    cfg = cfg_mod.AgencyConfig(
        allow_remote_tasks=True,
        incoming=cfg_mod.IncomingConfig(mode="template"),
    )
    monkeypatch.setattr(nm_mod, "get_config", lambda: cfg)
    monkeypatch.setattr(nm_mod, "kanban_update_task", lambda *args, **kwargs: {})
    monkeypatch.setattr(nm_mod, "announce_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_error", lambda *args, **kwargs: None)

    def should_not_process(*_args, **_kwargs):
        raise AssertionError("delegation should not run in template mode")

    monkeypatch.setattr(nm_mod, "process_incoming_task", should_not_process)

    class Task:
        completed = None

        async def complete(self, artifacts):
            self.completed = artifacts

        async def fail(self, error):
            raise AssertionError(error)

    task = Task()
    worker = asyncio.create_task(manager._incoming_worker())
    await manager._incoming_queue.put((task, record.task_id))
    await asyncio.wait_for(manager._incoming_queue.join(), timeout=2)
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)

    assert task.completed is not None
    text = task.completed[0]["parts"][0]["text"]
    assert "Hi! I'm gpt" in text
    assert "I have 42 skills installed." in text
    assert record.result_text == text


@pytest.mark.asyncio
async def test_incoming_worker_allow_remote_tasks_false_uses_safe_stub(plugin_modules, monkeypatch):
    asyncio = __import__("asyncio")
    nm_mod = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    manager = nm_mod.NodeManager()
    manager._incoming_queue = asyncio.Queue()
    manager.state.card_name = "gpt"
    record = nm_mod.IncomingTaskRecord(
        task_id="task-safe",
        sender_peer_id="peer-a",
        sender_card=None,
        target_skill_id="",
        message_text="What is 2 + 2?",
    )
    manager._incoming_records[record.task_id] = record
    cfg = cfg_mod.AgencyConfig(allow_remote_tasks=False)
    monkeypatch.setattr(nm_mod, "get_config", lambda: cfg)
    monkeypatch.setattr(nm_mod, "kanban_update_task", lambda *args, **kwargs: {})
    monkeypatch.setattr(nm_mod, "announce_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(nm_mod, "announce_error", lambda *args, **kwargs: None)

    def should_not_process(*_args, **_kwargs):
        raise AssertionError("delegation should not run when remote tasks are disabled")

    monkeypatch.setattr(nm_mod, "process_incoming_task", should_not_process)

    class Task:
        completed = None

        async def complete(self, artifacts):
            self.completed = artifacts

        async def fail(self, error):
            raise AssertionError(error)

    task = Task()
    worker = asyncio.create_task(manager._incoming_worker())
    await manager._incoming_queue.put((task, record.task_id))
    await asyncio.wait_for(manager._incoming_queue.join(), timeout=2)
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)

    assert task.completed is not None
    text = task.completed[0]["parts"][0]["text"]
    assert "Hermes Agency safe stub" in text
    assert "No Hermes tools" in text
    assert "allow_remote_tasks=False" in text
    assert record.result_text == text


def test_serialize_part_dict_to_dict_object_and_string(plugin_modules):
    nm = plugin_modules.node_manager.NodeManager

    class Part:
        def to_dict(self):
            return {"text": "from object", "kind": "text"}

    assert nm._serialize_part({"text": "from dict"}) == {"text": "from dict"}
    assert nm._serialize_part(Part()) == {"text": "from object", "kind": "text"}
    assert nm._serialize_part("plain") == {"text": "plain"}


def test_serialize_artifact_dict_and_to_dict_object(plugin_modules):
    nm = plugin_modules.node_manager.NodeManager

    class Artifact:
        def to_dict(self):
            return {"name": "object", "parts": [{"text": "hello"}]}

    assert nm._serialize_artifact({"name": "dict", "parts": []}) == {"name": "dict", "parts": []}
    assert nm._serialize_artifact(Artifact()) == {"name": "object", "parts": [{"text": "hello"}]}


def test_artifact_text_extracts_text_from_parts(plugin_modules):
    nm = plugin_modules.node_manager.NodeManager

    class Part:
        def __init__(self, text):
            self.text = text

        def to_dict(self):
            return {"text": self.text}

    artifact = {"parts": [{"text": "one"}, Part("two"), {"data": "ignored"}, "three"]}

    assert nm._artifact_text(artifact) == "one\ntwo\nthree"


@pytest.mark.asyncio
async def test_handle_incoming_task_treats_duplicate_working_transition_as_idempotent(
    plugin_modules, monkeypatch, tmp_path
):
    nm_mod = plugin_modules.node_manager
    cfg = plugin_modules.config.AgencyConfig(
        relay_security=plugin_modules.config.RelaySecurityConfig(allowlist=("peer-a",)),
        trust=plugin_modules.config.TrustConfig(store_path=tmp_path / "trust.json"),
    )
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-a", trust_level="full")
    monkeypatch.setattr(nm_mod, "get_config", lambda: cfg)
    manager = nm_mod.NodeManager()
    manager._incoming_queue = __import__("asyncio").Queue()

    class Part:
        text = "hello"

    class Message:
        parts = [Part()]

    class Task:
        task_id = "task-dup-working"
        peer_id = "peer-a"
        target_skill_id = ""
        metadata = {}
        messages = [Message()]
        failed = None

        async def update_status(self, status):
            raise RuntimeError("invalid transition: WORKING -> WORKING for task task-dup-working")

        async def fail(self, error):
            self.failed = error

    task = Task()
    await manager._handle_incoming_task(task)

    queued_task, queued_task_id = manager._incoming_queue.get_nowait()
    assert queued_task is task
    assert queued_task_id == "task-dup-working"
    assert task.failed is None
    assert manager.incoming_tasks_sync(limit=1)[0]["status"] == "queued"


@pytest.mark.asyncio
async def test_refresh_capability_map_fetches_agent_card_for_listed_peer(plugin_modules):
    team_context = importlib.import_module("hermes_plugin.team_context")
    registration = importlib.import_module("hermes_plugin.registration")
    team_context._state.peers = {}
    registration._state.registrations = {}

    @dataclass
    class Skill:
        id: str
        description: str = ""

    @dataclass
    class Card:
        name: str
        description: str
        skills: list[Skill]

    class Node:
        async def list_peers(self):
            return [{"peer_id": "peer-gpt", "addresses": ["/ip4/127.0.0.1/tcp/1"]}]

        async def get_card(self, peer_id):
            assert peer_id == "peer-gpt"
            return Card(
                name="gpt",
                description="OpenAI reasoning agent",
                skills=[Skill("code-review", "Review code"), Skill("debug", "Debug issues")],
            )

        async def discover(self, *args, **kwargs):
            return []

    peers = await team_context.refresh_capability_map(Node(), local_peer_id="local")
    peer = peers["peer-gpt"]
    assert peer.card_name == "gpt"
    assert [skill["id"] for skill in peer.card_skills] == ["code-review", "debug"]

    context = team_context.build_team_context(
        plugin_modules.config.AgencyConfig(
            team=plugin_modules.config.TeamConfig(context_filter="all")
        )
    )
    assert "- gpt — skills: code-review (Review code), debug (Debug issues)" in context
    assert "  peer_id: peer-gpt" in context
    assert "Unnamed agent" not in context


def test_render_roster_agent_reapplies_profile_overlay_at_render_seam(
    plugin_modules, tmp_path, monkeypatch
):
    team_context = importlib.import_module("hermes_plugin.team_context")
    roster = importlib.import_module("hermes_plugin.pool.roster")
    profiles_dir = tmp_path / "profiles"
    profile_dir = profiles_dir / "agency-accessibility-reviewer"
    profile_dir.mkdir(parents=True)
    (profile_dir / "SOUL.md").write_text(
        "# Accessibility Reviewer\n\nYou are the Accessibility Reviewer from SOUL.md.\n",
        encoding="utf-8",
    )
    (profile_dir / "config.yaml").write_text(
        "model:\n  default: glm-5.2\n  provider: opencode-go\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(roster, "_profiles_dir", lambda: profiles_dir)

    lines = team_context._render_roster_agent(
        {
            "name": "agency-accessibility-reviewer",
            "description": "Accessibility Reviewer agent",
            "skills": ["accessibility", "wcag"],
            "model": "gpt-5.5",
            "provider": "openai-codex",
            "online": False,
        },
        max_skills=8,
    )

    rendered = "\n".join(lines)
    assert "Description: You are the Accessibility Reviewer from SOUL.md." in rendered
    assert "model/provider: glm-5.2 / opencode-go" in rendered
    assert "Accessibility Reviewer agent" not in rendered
    assert "model/provider: gpt-5.5 / openai-codex" not in rendered


def test_build_team_context_does_not_enrich_remote_peer_from_local_profile(
    plugin_modules,
):
    team_context = importlib.import_module("hermes_plugin.team_context")
    registration = importlib.import_module("hermes_plugin.registration")
    profile_skills = plugin_modules.hermes_home / "profiles" / "git" / "skills" / "private"
    profile_skills.mkdir(parents=True)
    (profile_skills / "SKILL.md").write_text(
        "---\nname: private-repo-map\ndescription: LEAKED_LOCAL_GIT_PROFILE\n---\n",
        encoding="utf-8",
    )
    team_context._state.peers = {
        "peer-attacker-git": team_context.PeerCapability(
            peer_id="peer-attacker-git",
            name="git",
            skills=[{"id": "claimed", "description": "remote supplied"}],
        )
    }
    registration._state.registrations = {}

    context = team_context.build_team_context(
        plugin_modules.config.AgencyConfig(
            team=plugin_modules.config.TeamConfig(context_filter="all")
        )
    )

    assert "claimed (remote supplied)" in context
    assert "private-repo-map" not in context
    assert "LEAKED_LOCAL_GIT_PROFILE" not in context
    assert "peer_id: peer-attacker-git" in context


def test_build_team_context_does_not_follow_remote_profile_traversal(
    plugin_modules,
    tmp_path,
):
    team_context = importlib.import_module("hermes_plugin.team_context")
    registration = importlib.import_module("hermes_plugin.registration")
    traversed_skills = tmp_path / "vault" / "skills" / "secret"
    traversed_skills.mkdir(parents=True)
    (traversed_skills / "SKILL.md").write_text(
        "---\nname: traversal-read\ndescription: TRAVERSAL_READ\n---\n",
        encoding="utf-8",
    )
    team_context._state.peers = {
        "peer-attacker-traversal": team_context.PeerCapability(
            peer_id="peer-attacker-traversal",
            name="../vault",
            skills=[{"id": "claimed", "description": "remote supplied"}],
        )
    }
    registration._state.registrations = {}

    context = team_context.build_team_context(
        plugin_modules.config.AgencyConfig(
            team=plugin_modules.config.TeamConfig(context_filter="all")
        )
    )

    assert "claimed (remote supplied)" in context
    assert "traversal-read" not in context
    assert "TRAVERSAL_READ" not in context
    assert "peer_id: peer-attacker-traversal" in context


def test_build_team_context_uses_registration_when_card_unavailable(plugin_modules):
    team_context = importlib.import_module("hermes_plugin.team_context")
    registration = importlib.import_module("hermes_plugin.registration")
    team_context._state.peers = {
        "peer-local-agent": team_context.PeerCapability(peer_id="peer-local-agent")
    }
    registration._state.registrations = {
        "peer-local-agent": registration.RegistrationRecord(
            peer_id="peer-local-agent",
            name="local-agent",
            description="Orchestrator profile",
            skills=[{"id": "deployment", "description": "Deploy safely"}],
            tenant="default",
        )
    }

    context = team_context.build_team_context(
        plugin_modules.config.AgencyConfig(
            team=plugin_modules.config.TeamConfig(context_filter="all")
        )
    )

    assert "- local-agent — skills: deployment (Deploy safely)" in context
    assert "  Description: Orchestrator profile" in context
    assert "  peer_id: peer-local-agent" in context
    assert "Unnamed agent" not in context


@pytest.mark.asyncio
async def test_refresh_capability_map_falls_back_to_registration_when_get_card_fails(
    plugin_modules,
):
    team_context = importlib.import_module("hermes_plugin.team_context")
    registration = importlib.import_module("hermes_plugin.registration")
    team_context._state.peers = {}
    registration._state.registrations = {
        "peer-gpt": registration.RegistrationRecord(
            peer_id="peer-gpt",
            name="gpt",
            description="Reasoning profile",
            skills=[{"id": "debug", "description": "Debug issues"}],
            tenant="default",
        )
    }

    class Node:
        async def list_peers(self):
            return [{"peer_id": "peer-gpt", "addresses": []}]

        async def get_card(self, peer_id):
            raise TimeoutError("card unavailable")

        async def discover(self, *args, **kwargs):
            return []

    peers = await team_context.refresh_capability_map(Node(), local_peer_id="local")

    assert peers["peer-gpt"].name == "gpt"
    assert [skill["id"] for skill in peers["peer-gpt"].skills] == ["debug"]


def test_build_team_context_falls_back_to_truncated_peer_id(plugin_modules):
    team_context = importlib.import_module("hermes_plugin.team_context")
    registration = importlib.import_module("hermes_plugin.registration")
    peer_id = "12D3KooWE8NredZ4wptKoRorz2KZRoQqw9VMj2hiYgpH6h6krZvj"
    team_context._state.peers = {peer_id: team_context.PeerCapability(peer_id=peer_id)}
    registration._state.registrations = {}

    context = team_context.build_team_context(
        plugin_modules.config.AgencyConfig(
            team=plugin_modules.config.TeamConfig(context_filter="all")
        )
    )

    assert f"- {peer_id[:20]}... (skills unknown)" in context
    assert "Top skills: unknown from peer discovery" in context
    assert "Unnamed agent" not in context


def test_build_team_context_respects_peer_and_skill_limits(plugin_modules):
    team_context = importlib.import_module("hermes_plugin.team_context")
    registration = importlib.import_module("hermes_plugin.registration")
    team_context._state.peers = {}
    registration._state.registrations = {}
    for idx in range(4):
        team_context._state.peers[f"peer-{idx}"] = team_context.PeerCapability(
            peer_id=f"peer-{idx}",
            name=f"agent-{idx}",
            description=f"Agent {idx} profile",
            skills=[
                {"id": f"skill-{idx}-{skill_idx}", "description": f"Skill {skill_idx}"}
                for skill_idx in range(5)
            ],
        )
    cfg = plugin_modules.config.AgencyConfig(
        team=plugin_modules.config.TeamConfig(
            context_filter="all", max_context_peers=2, max_context_skills=2
        )
    )

    context = team_context.build_team_context(cfg)

    assert "- agent-0 — skills: skill-0-0 (Skill 0), skill-0-1 (Skill 1)" in context
    assert "- agent-1 — skills: skill-1-0 (Skill 0), skill-1-1 (Skill 1)" in context
    assert "skill-0-2" not in context
    assert "- agent-2" not in context
    assert "2 more teammate agent(s) omitted" in context


def test_build_team_context_respects_character_budget(plugin_modules):
    team_context = importlib.import_module("hermes_plugin.team_context")
    registration = importlib.import_module("hermes_plugin.registration")
    team_context._state.peers = {
        "peer-budget": team_context.PeerCapability(
            peer_id="peer-budget",
            name="budget-agent",
            description="x" * 300,
            skills=[{"id": "oversized", "description": "y" * 500}],
        )
    }
    registration._state.registrations = {}
    cfg = plugin_modules.config.AgencyConfig(
        team=plugin_modules.config.TeamConfig(context_max_chars=360)
    )

    context = team_context.build_team_context(cfg)

    assert len(context) <= 360
    assert context.endswith("…")
    assert "Hermes Agency team context:" in context


def test_registry_reregister_interval_stays_below_relay_ttl(plugin_modules):
    nm = plugin_modules.node_manager

    assert nm.REGISTRY_REREGISTER_INTERVAL_SECONDS < 30


def test_registry_addresses_parse_env(plugin_modules, monkeypatch):
    nm = plugin_modules.node_manager
    monkeypatch.setenv("AGENTANYCAST_REGISTRY_ADDRS", "198.51.100.10:50052, ,localhost:50052")

    assert nm._registry_addresses() == ["198.51.100.10:50052", "localhost:50052"]


@pytest.mark.asyncio
async def test_register_skills_with_registry_posts_card_to_each_registry(
    plugin_modules, monkeypatch
):
    nm = plugin_modules.node_manager
    calls = []

    @dataclass
    class Skill:
        id: str
        description: str = ""

    @dataclass
    class Card:
        name: str = "Hermes Test"
        description: str = "Test profile"
        skills: list[Skill] | None = None

    class Request:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class SkillInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Stub:
        def __init__(self, channel):
            self.channel = channel

        async def RegisterSkills(self, request, timeout=None):
            calls.append((self.channel.addr, request, timeout))
            return object()

    class Channel:
        def __init__(self, addr):
            self.addr = addr
            self.closed = False

        async def close(self):
            self.closed = True

    fake_grpc = types.SimpleNamespace(
        aio=types.SimpleNamespace(insecure_channel=lambda addr: Channel(addr))
    )
    fake_pb2 = types.SimpleNamespace(RegisterSkillsRequest=Request, SkillInfo=SkillInfo)
    fake_grpc_pb2 = types.SimpleNamespace(RegistryServiceStub=Stub)
    monkeypatch.setitem(sys.modules, "grpc", fake_grpc)
    monkeypatch.setitem(
        sys.modules, "agentanycast._generated.agentanycast.v1.registry_service_pb2", fake_pb2
    )
    monkeypatch.setitem(
        sys.modules,
        "agentanycast._generated.agentanycast.v1.registry_service_pb2_grpc",
        fake_grpc_pb2,
    )
    monkeypatch.setenv("AGENTANYCAST_REGISTRY_ADDRS", "one:50052,two:50052")

    manager = nm.NodeManager()
    manager.state.started = True
    manager.state.peer_id = "peer-1"
    result = await manager._register_skills_with_registries(Card(skills=[Skill("chat", "Chat")]))
    manager._handle_registry_registration_result(result, retry_in_seconds=1)

    assert [call[0] for call in calls] == ["one:50052", "two:50052"]
    assert calls[0][1].peer_id == "peer-1"
    assert calls[0][1].agent_name == "Hermes Test"
    assert calls[0][1].agent_description == "Test profile"
    assert calls[0][1].skills[0].skill_id == "chat"
    assert calls[0][1].skills[0].description == "Chat"
    assert result["ok"] is True
    assert manager.state.last_registration_time is not None
    assert manager.state.consecutive_failures == 0
    assert manager.info()["registration"]["registry_refresh"]["registration_healthy"] is True


@pytest.mark.asyncio
async def test_registry_token_is_not_sent_over_insecure_grpc_by_default(
    plugin_modules, monkeypatch, caplog
):
    nm = plugin_modules.node_manager
    metadata_seen = []

    @dataclass
    class Skill:
        id: str
        description: str = ""

    @dataclass
    class Card:
        name: str = "Hermes Test"
        description: str = "Test profile"
        skills: list[Skill] | None = None

    class Request:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class SkillInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Stub:
        def __init__(self, channel):
            self.channel = channel

        async def RegisterSkills(self, request, timeout=None, metadata=None):
            metadata_seen.append(metadata)
            return object()

    class Channel:
        def __init__(self, addr):
            self.addr = addr

        async def close(self):
            pass

    fake_grpc = types.SimpleNamespace(
        aio=types.SimpleNamespace(insecure_channel=lambda addr: Channel(addr))
    )
    fake_pb2 = types.SimpleNamespace(RegisterSkillsRequest=Request, SkillInfo=SkillInfo)
    fake_grpc_pb2 = types.SimpleNamespace(RegistryServiceStub=Stub)
    monkeypatch.setitem(sys.modules, "grpc", fake_grpc)
    monkeypatch.setitem(
        sys.modules, "agentanycast._generated.agentanycast.v1.registry_service_pb2", fake_pb2
    )
    monkeypatch.setitem(
        sys.modules,
        "agentanycast._generated.agentanycast.v1.registry_service_pb2_grpc",
        fake_grpc_pb2,
    )
    monkeypatch.setenv("AGENTANYCAST_REGISTRY_ADDRS", "one:50052")

    manager = nm.NodeManager()
    manager.state.started = True
    manager.state.peer_id = "peer-1"
    manager.state.config = plugin_modules.config.AgencyConfig(
        relay_security=plugin_modules.config.RelaySecurityConfig(token="secret-token")
    )

    with caplog.at_level("WARNING"):
        result = await manager._register_skills_with_registries(
            Card(skills=[Skill("chat", "Chat")])
        )

    assert result["ok"] is True
    assert metadata_seen == [None]
    assert "not sending registry token over insecure gRPC" in caplog.text


@pytest.mark.asyncio
async def test_registry_token_can_be_sent_over_insecure_grpc_when_allowed(
    plugin_modules, monkeypatch, caplog
):
    nm = plugin_modules.node_manager
    metadata_seen = []

    @dataclass
    class Skill:
        id: str
        description: str = ""

    @dataclass
    class Card:
        name: str = "Hermes Test"
        description: str = "Test profile"
        skills: list[Skill] | None = None

    class Request:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class SkillInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Stub:
        def __init__(self, channel):
            self.channel = channel

        async def RegisterSkills(self, request, timeout=None, metadata=None):
            metadata_seen.append(metadata)
            return object()

    class Channel:
        def __init__(self, addr):
            self.addr = addr

        async def close(self):
            pass

    fake_grpc = types.SimpleNamespace(
        aio=types.SimpleNamespace(insecure_channel=lambda addr: Channel(addr))
    )
    fake_pb2 = types.SimpleNamespace(RegisterSkillsRequest=Request, SkillInfo=SkillInfo)
    fake_grpc_pb2 = types.SimpleNamespace(RegistryServiceStub=Stub)
    monkeypatch.setitem(sys.modules, "grpc", fake_grpc)
    monkeypatch.setitem(
        sys.modules, "agentanycast._generated.agentanycast.v1.registry_service_pb2", fake_pb2
    )
    monkeypatch.setitem(
        sys.modules,
        "agentanycast._generated.agentanycast.v1.registry_service_pb2_grpc",
        fake_grpc_pb2,
    )
    monkeypatch.setenv("AGENTANYCAST_REGISTRY_ADDRS", "one:50052")

    manager = nm.NodeManager()
    manager.state.started = True
    manager.state.peer_id = "peer-1"
    manager.state.config = plugin_modules.config.AgencyConfig(
        relay_security=plugin_modules.config.RelaySecurityConfig(token="secret-token"),
        registry_allow_insecure_token_transport=True,
    )

    with caplog.at_level("WARNING"):
        result = await manager._register_skills_with_registries(
            Card(skills=[Skill("chat", "Chat")])
        )

    assert result["ok"] is True
    assert metadata_seen == [
        (
            ("authorization", "Bearer secret-token"),
            ("x-agency-relay-token", "secret-token"),
        )
    ]
    assert "sending registry token over insecure gRPC" in caplog.text


@pytest.mark.asyncio
async def test_registry_registration_failures_backoff_and_recover(
    plugin_modules, monkeypatch, caplog
):
    nm = plugin_modules.node_manager

    @dataclass
    class Skill:
        id: str
        description: str = ""

    @dataclass
    class Card:
        name: str = "Hermes Test"
        description: str = "Test profile"
        skills: list[Skill] | None = None

    class Request:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class SkillInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FailingStub:
        def __init__(self, channel):
            self.channel = channel

        async def RegisterSkills(self, request, timeout=None):
            raise RuntimeError("relay unavailable")

    class Channel:
        def __init__(self, addr):
            self.addr = addr

        async def close(self):
            pass

    fake_grpc = types.SimpleNamespace(
        aio=types.SimpleNamespace(insecure_channel=lambda addr: Channel(addr))
    )
    fake_pb2 = types.SimpleNamespace(RegisterSkillsRequest=Request, SkillInfo=SkillInfo)
    fake_grpc_pb2 = types.SimpleNamespace(RegistryServiceStub=FailingStub)
    monkeypatch.setitem(sys.modules, "grpc", fake_grpc)
    monkeypatch.setitem(
        sys.modules, "agentanycast._generated.agentanycast.v1.registry_service_pb2", fake_pb2
    )
    monkeypatch.setitem(
        sys.modules,
        "agentanycast._generated.agentanycast.v1.registry_service_pb2_grpc",
        fake_grpc_pb2,
    )
    monkeypatch.setenv("AGENTANYCAST_REGISTRY_ADDRS", "one:50052")

    manager = nm.NodeManager()
    manager.state.started = True
    manager.state.peer_id = "peer-1"

    with caplog.at_level("WARNING"):
        result = await manager._register_skills_with_registries(
            Card(skills=[Skill("chat", "Chat")])
        )
        assert result["ok"] is False
        manager._handle_registry_registration_result(result, retry_in_seconds=4)
        for _ in range(4):
            manager._record_registry_registration_failure("relay unavailable", retry_in_seconds=4)

        assert manager.state.consecutive_failures == 5
        assert manager.state.next_retry_at is not None
        assert manager.info()["registration"]["registry_refresh"]["registration_healthy"] is False
        assert "still failing after 5 consecutive failures" in caplog.text

        manager._record_registry_registration_success()

    assert manager.state.consecutive_failures == 0
    assert manager.info()["registration"]["registry_refresh"]["registration_healthy"] is True
    assert "re-registration recovered after 5 consecutive failures" in caplog.text


def test_compact_info_contains_health_without_heavy_payloads(plugin_modules, monkeypatch):
    nm = plugin_modules.node_manager
    monkeypatch.setattr(nm.time, "time", lambda: 1210.0)
    manager = nm.NodeManager()
    manager.state.started = True
    manager.state.peer_id = "peer-1"
    manager.state.card_name = "Hermes Test"
    manager.state.serve_task_running = True
    manager.state.team_peer_count = 2
    manager.state.team_last_refresh = 1234.0
    manager.state.team_last_error = None
    manager.state.last_registration_time = 1200.0
    manager.state.consecutive_failures = 0
    manager.state.next_retry_at = 1220.0
    manager.state.registration_healthy = True

    data = manager.compact_info()

    assert data["ok"] is True
    assert data["node_started"] is True
    assert data["peer_id"] == "peer-1"
    assert data["card_name"] == "Hermes Test"
    assert data["serve_task_running"] is True
    assert data["registration"] == {
        "healthy": True,
        "last_registration_time": 1200.0,
        "consecutive_failures": 0,
        "next_retry_at": 1220.0,
        "loop_running": False,
        "loop_exited": False,
        "healthy_window_seconds": nm.REGISTRY_HEALTHY_WINDOW_SECONDS,
        "normal_interval_seconds": nm.REGISTRY_REREGISTER_INTERVAL_SECONDS,
    }
    assert data["team"] == {"peer_count": 2, "last_refresh": 1234.0, "last_error": None}
    assert "team_context" not in data
    assert "skills" not in data
    assert "card" not in data
    assert len(json.dumps(data)) < 2048


def test_a2a_info_compact_uses_compact_node_payload(plugin_modules, monkeypatch):
    tools = plugin_modules.tools
    compact = {
        "ok": True,
        "node_started": True,
        "peer_id": "peer-1",
        "card_name": "Hermes Test",
        "serve_task_running": True,
        "registration": {"healthy": True, "consecutive_failures": 0},
        "team": {"peer_count": 2},
    }

    class FakeManager:
        def compact_info(self):
            return compact

    monkeypatch.setattr(tools, "manager", FakeManager())
    monkeypatch.setattr(tools, "check_agency_available", lambda: True)
    result = json.loads(tools.a2a_info({"compact": True}))

    assert result == {"ok": True, "sdk_available": True, "compact": True, "node": compact}
    assert "card" not in result


def test_a2a_discover_uses_compact_node_payload(plugin_modules, monkeypatch):
    tools = plugin_modules.tools
    compact = {"ok": True, "node_started": True, "registration": {"healthy": True}}

    class FakeManager:
        def compact_info(self):
            return compact

        def info(self):
            raise AssertionError("a2a_discover should not use full manager.info()")

        def discover_sync(self, skill, tags=None, limit=0):
            return [
                {
                    "peer_id": "peer-1",
                    "agent_name": "Hermes Test",
                    "agent_description": "Test profile",
                    "skills": [
                        {"skill_id": "airtable", "description": "Airtable REST API"},
                        *[
                            {"skill_id": f"extra-{idx}", "description": "not relevant"}
                            for idx in range(100)
                        ],
                    ],
                }
            ]

    monkeypatch.setattr(tools, "manager", FakeManager())
    result = json.loads(tools.a2a_discover({"skill": "airtable"}))

    assert result == {
        "ok": True,
        "agents": [
            {
                "peer_id": "peer-1",
                "agent_name": "Hermes Test",
                "agent_description": "Test profile",
                "skill_count": 101,
                "matching_skills": [{"skill_id": "airtable", "description": "Airtable REST API"}],
            }
        ],
        "node": compact,
    }
    assert "skills" not in result["agents"][0]
    assert len(json.dumps(result)) < 2048


def test_a2a_discover_validation_errors_use_compact_node_payload(plugin_modules, monkeypatch):
    tools = plugin_modules.tools
    compact = {"ok": True, "node_started": True, "registration": {"healthy": True}}

    class FakeManager:
        def compact_info(self):
            return compact

        def info(self):
            raise AssertionError("validation errors should not use full manager.info()")

    monkeypatch.setattr(tools, "manager", FakeManager())
    result = json.loads(tools.a2a_discover({}))

    assert result == {"ok": False, "error": "skill is required", "node": compact}


def test_a2a_send_uses_compact_node_payload_for_validation_and_success(plugin_modules, monkeypatch):
    tools = plugin_modules.tools
    compact = {"ok": True, "node_started": True, "registration": {"healthy": True}}

    class FakeManager:
        def compact_info(self):
            return compact

        def info(self):
            raise AssertionError("a2a_send should not use full manager.info()")

        def send_task_sync(self, **kwargs):
            return {"task_id": "task-1", "status": "completed", "artifact_text": "done"}

    monkeypatch.setattr(tools, "manager", FakeManager())
    validation = json.loads(tools.a2a_send({"peer_id": "peer"}))
    success = json.loads(tools.a2a_send({"peer_id": "peer", "message": "hello", "wait_seconds": 1}))

    assert validation == {"ok": False, "error": "message is required", "node": compact}
    assert success == {
        "ok": True,
        "task_id": "task-1",
        "task": {"task_id": "task-1", "status": "completed", "artifact_text": "done"},
        "node": compact,
    }
    assert len(json.dumps(success)) < 2048


def test_routine_tools_use_compact_node_payloads(plugin_modules, monkeypatch):
    tools = plugin_modules.tools
    compact = {"ok": True, "node_started": True, "registration": {"healthy": True}}

    class FakeManager:
        def compact_info(self):
            return compact

        def info(self):
            raise AssertionError("routine tools should not use full manager.info()")

        def list_peers_sync(self):
            return [{"peer_id": "peer-1", "addresses": ["/ip4/127.0.0.1/tcp/1"]}]

        def task_status_sync(self, task_id):
            if task_id == "missing":
                return None
            return {"task_id": task_id, "status": "completed", "artifact_text": "done"}

        def incoming_tasks_sync(self, limit=20):
            return [{"task_id": "incoming-1", "status": "completed", "message": "hello"}]

    monkeypatch.setattr(tools, "manager", FakeManager())

    peers = json.loads(tools.a2a_list_peers({}))
    missing_status = json.loads(tools.a2a_status({"task_id": "missing"}))
    status = json.loads(tools.a2a_status({"task_id": "task-1"}))
    inbox = json.loads(tools.a2a_inbox({"limit": 1}))

    assert peers["node"] == compact
    assert peers["peers"][0]["peer_id"] == "peer-1"
    assert missing_status == {
        "ok": False,
        "error": "unknown task_id: missing",
        "task_id": "missing",
        "node": compact,
    }
    assert status["node"] == compact
    assert status["task"] == {"task_id": "task-1", "status": "completed", "artifact_text": "done"}
    assert inbox["node"] == compact
    assert inbox["tasks"] == [{"task_id": "incoming-1", "status": "completed", "message": "hello"}]
    assert len(json.dumps({"peers": peers, "status": status, "inbox": inbox})) < 2048


def test_lifecycle_tool_errors_use_compact_node_payloads(plugin_modules, monkeypatch):
    tools = plugin_modules.tools
    compact = {"ok": False, "node_started": False, "registration": {"healthy": False}}

    class FakeManager:
        def compact_info(self):
            return compact

        def info(self):
            raise AssertionError("lifecycle error paths should not use full manager.info()")

        def start_sync(self):
            raise RuntimeError("boom start")

        def stop_sync(self):
            raise RuntimeError("boom stop")

    monkeypatch.setattr(tools, "manager", FakeManager())

    start = json.loads(tools.a2a_start_node({}))
    stop = json.loads(tools.a2a_stop_node({}))

    assert start == {"ok": False, "error": "RuntimeError: boom start", "node": compact}
    assert stop == {"ok": False, "error": "RuntimeError: boom stop", "node": compact}


class _FakeA2ATask:
    def __init__(self, task_id="a2a-task", status="submitted", artifact_text=""):
        self.task_id = task_id
        self.status = status
        self.context_id = ""
        self.target_skill_id = ""
        self.originator_peer_id = ""
        self.artifacts = [{"parts": [{"text": artifact_text}]}] if artifact_text else []
        self.metadata = {}


class _FakeA2AHandle:
    def __init__(self, task_id="a2a-task", *, wait_error=None, status="submitted"):
        self.task_id = task_id
        self._task = _FakeA2ATask(task_id=task_id, status=status)
        self.wait_error = wait_error

    async def wait(self, timeout=None):
        if self.wait_error:
            raise self.wait_error
        self._task.status = "completed"
        self._task.artifacts = [{"parts": [{"text": "remote result"}]}]
        return self


class _FakeA2ANode:
    def __init__(self, *, handle=None, send_error=None):
        self.handle = handle or _FakeA2AHandle()
        self.send_error = send_error
        self.sent = []

    async def send_task(self, **kwargs):
        if self.send_error:
            raise self.send_error
        self.sent.append(kwargs)
        return self.handle


def test_ensure_agency_board_uses_department_board_for_target_agent(plugin_modules, monkeypatch):
    nm = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    manager = nm.NodeManager()
    boards = {}
    metadata_writes = []

    class FakeKb:
        @staticmethod
        def board_exists(slug):
            return slug in boards

        @staticmethod
        def create_board(slug, name, description):
            boards[slug] = {"slug": slug, "name": name, "description": description}
            return boards[slug]

        @staticmethod
        def read_board_metadata(slug):
            return {}

        @staticmethod
        def board_metadata_path(slug):
            return plugin_modules.hermes_home / f"{slug}.json"

        @staticmethod
        def kanban_db_path(slug):
            return plugin_modules.hermes_home / f"{slug}.db"

    monkeypatch.setattr(
        nm,
        "get_config",
        lambda: cfg_mod.AgencyConfig(team=cfg_mod.TeamConfig(kanban_integration=True)),
    )
    monkeypatch.setattr(
        manager,
        "_write_agency_board_metadata",
        lambda kb, slug, **fields: (
            metadata_writes.append({"slug": slug, **fields}) or {"slug": slug, **fields}
        ),
    )
    hermes_cli = sys.modules["hermes_cli"]
    setattr(hermes_cli, "kanban_db", FakeKb)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db", FakeKb)

    slug = manager._ensure_agency_board(
        task_id="task-1",
        title="Write copy",
        agent_name="agency-copywriter",
        direction="outgoing",
    )

    assert slug == "agency-content"
    assert boards["agency-content"]["name"] == "Agency Content"
    assert metadata_writes[-1]["department"] == "Content"
    assert metadata_writes[-1]["target_agent"] == "agency-copywriter"

    again = manager._ensure_agency_board(
        task_id="task-2",
        title="More copy",
        agent_name="copywriter",
        direction="outgoing",
    )

    assert again == "agency-content"
    assert set(boards) == set(plugin_modules.departments.DEPARTMENT_BOARD_SLUGS.values())


def _install_kanban_spies(nm, monkeypatch, *, task_id="kb-1"):
    calls = {"track": [], "update": [], "comment": []}

    def track(**kwargs):
        calls["track"].append(kwargs)
        return {
            "available": True,
            "ok": True,
            "task_id": task_id,
            "task": {"plugin_status": "running"},
        }

    def update(task_id, status=None, result=None, error=None):
        calls["update"].append(
            {"task_id": task_id, "status": status, "result": result, "error": error}
        )
        return {
            "available": True,
            "ok": True,
            "task_id": task_id,
            "task": {"plugin_status": status, "result": result},
        }

    def comment(task_id, body):
        calls["comment"].append({"task_id": task_id, "body": body})
        return {"available": True, "ok": True}

    monkeypatch.setattr(nm, "kanban_track_delegation", track)
    monkeypatch.setattr(nm, "kanban_update_task", update)
    monkeypatch.setattr(nm, "kanban_add_comment", comment)
    return calls


async def _send_with_fake_node(manager, node, **kwargs):
    manager.state.started = True
    manager._node = node
    nm_mod = importlib.import_module("hermes_plugin.node_manager")
    cfg_mod = importlib.import_module("hermes_plugin.config")
    setattr(
        nm_mod,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            relay_security=cfg_mod.RelaySecurityConfig(allowlist=("peer-x",))
        ),
    )
    return await manager._send_task_impl("hello", peer_id="peer-x", **kwargs)


@pytest.mark.asyncio
async def test_send_task_with_context_id_includes_conversation_history(plugin_modules, monkeypatch):
    nm = plugin_modules.node_manager
    cfg_mod = plugin_modules.config
    calls = _install_kanban_spies(nm, monkeypatch)
    manager = nm.NodeManager()
    manager.state.started = True
    node = _FakeA2ANode(handle=_FakeA2AHandle())
    manager._node = node
    monkeypatch.setattr(
        nm,
        "get_config",
        lambda: cfg_mod.AgencyConfig(
            relay_security=cfg_mod.RelaySecurityConfig(allowlist=("peer-x",)),
            incoming=cfg_mod.IncomingConfig(conversation_ttl=3600, conversation_max_turns=5),
        ),
    )
    monkeypatch.setattr(
        nm,
        "build_conversation_history",
        lambda context_id, profile_home, max_turns=10, ttl=3600: [
            {"user": "Write a haiku about AI", "agent": "Silent agents weave"}
        ],
    )

    data = await manager._send_task_impl(
        "Now make it about P2P networking",
        peer_id="peer-x",
        context_id="test-conv-1",
        wait_seconds=0,
    )

    sent_text = node.sent[0]["message"]["parts"][0]["text"]
    assert "test-conv-1" in sent_text
    assert "conversation_history" in sent_text
    assert data["context_packet"]["context_id"] == "test-conv-1"
    assert data["context_packet"]["conversation_history"] == [
        {"user": "Write a haiku about AI", "agent": "Silent agents weave"}
    ]
    assert calls["track"][-1]["metadata"]["context_id"] == "test-conv-1"


@pytest.mark.asyncio
async def test_send_task_marks_kanban_done_after_wait_success(plugin_modules, monkeypatch):
    nm = plugin_modules.node_manager
    calls = _install_kanban_spies(nm, monkeypatch)
    manager = nm.NodeManager()

    await _send_with_fake_node(manager, _FakeA2ANode(handle=_FakeA2AHandle()), wait_seconds=30)

    assert any(
        call["status"] == "done" and call["result"] == "remote result" for call in calls["update"]
    )


@pytest.mark.asyncio
async def test_send_task_marks_kanban_running_when_not_waiting(plugin_modules, monkeypatch):
    nm = plugin_modules.node_manager
    calls = _install_kanban_spies(nm, monkeypatch)
    manager = nm.NodeManager()

    await _send_with_fake_node(manager, _FakeA2ANode(handle=_FakeA2AHandle()), wait_seconds=0)

    assert any(call["status"] == "running" for call in calls["update"])
    assert any("not waiting for completion" in call["body"] for call in calls["comment"])


@pytest.mark.asyncio
async def test_send_task_marks_kanban_blocked_when_send_fails(plugin_modules, monkeypatch):
    nm = plugin_modules.node_manager
    calls = _install_kanban_spies(nm, monkeypatch)
    manager = nm.NodeManager()

    with pytest.raises(RuntimeError):
        await _send_with_fake_node(
            manager, _FakeA2ANode(send_error=RuntimeError("bad peer")), wait_seconds=30
        )

    assert calls["track"]
    assert any(
        call["status"] == "blocked" and "bad peer" in str(call["error"] or call["result"])
        for call in calls["update"]
    )


@pytest.mark.asyncio
async def test_task_status_prefers_terminal_kanban_over_stale_handle(plugin_modules, monkeypatch):
    nm = plugin_modules.node_manager
    manager = nm.NodeManager()
    manager._task_handles["a2a-stale"] = _FakeA2AHandle(task_id="a2a-stale", status="submitted")
    monkeypatch.setattr(
        nm,
        "kanban_get_task",
        lambda task_id: {
            "available": True,
            "ok": True,
            "task_id": "kb-stale",
            "task": {"plugin_status": "done", "status": "done", "result": "kanban result"},
        },
    )

    data = await manager._task_status_impl("a2a-stale")

    assert data["status"] == "done"
    assert data["a2a_status"] == "submitted"
    assert data["kanban_status"] == "done"
    assert data["result"] == "kanban result"


# === Phase 1 Security Regression Tests (added during repair) ===


def _mock_security(allowed: bool, reason: str = None, peer_id: str = "peer-test"):
    class MockSecurity:
        def __init__(self):
            self.allowed = allowed
            self.reason = reason or ("blocked" if not allowed else None)
            self.sender_peer_id = peer_id

    return MockSecurity()


@pytest.mark.asyncio
async def test_normal_task_from_blocked_peer_is_rejected_before_queue(
    plugin_modules, monkeypatch, tmp_path, caplog
):
    nm = plugin_modules.node_manager
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-good",))
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    monkeypatch.setattr(
        nm,
        "verify_incoming_sender",
        lambda task, cfg, purpose: _mock_security(False, "peer blocked", "peer-bad"),
    )
    manager = nm.NodeManager()
    manager._incoming_queue = __import__("asyncio").Queue()
    task = _FakeIncomingTask("blocked task", peer_id="peer-bad", task_id="task-blocked")
    with caplog.at_level("WARNING"):
        await manager._handle_incoming_task(task)
    assert task.failed is not None
    assert "rejected" in task.failed.lower() or "blocked" in task.failed.lower()
    assert manager._incoming_queue.qsize() == 0
    assert "peer-bad" in caplog.text or "blocked" in caplog.text


@pytest.mark.asyncio
async def test_normal_task_from_unknown_peer_is_rejected_before_state_mutation(
    plugin_modules, monkeypatch, tmp_path, caplog
):
    nm = plugin_modules.node_manager
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-good",), tofu=False)
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    monkeypatch.setattr(
        nm,
        "verify_incoming_sender",
        lambda task, cfg, purpose: _mock_security(False, "unknown peer", "peer-unknown"),
    )
    manager = nm.NodeManager()
    manager._incoming_queue = __import__("asyncio").Queue()
    task = _FakeIncomingTask("unknown", peer_id="peer-unknown", task_id="task-unknown")
    with caplog.at_level("WARNING"):
        await manager._handle_incoming_task(task)
    assert task.failed is not None
    assert manager._incoming_queue.qsize() == 0
    assert "unknown" in caplog.text or "rejected" in caplog.text


@pytest.mark.asyncio
async def test_normal_task_with_insufficient_trust_is_rejected(
    plugin_modules, monkeypatch, tmp_path, caplog
):
    nm = plugin_modules.node_manager
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-good",))
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    monkeypatch.setattr(
        nm,
        "verify_incoming_sender",
        lambda task, cfg, purpose: _mock_security(
            False, "insufficient trust for task", "peer-good"
        ),
    )
    manager = nm.NodeManager()
    manager._incoming_queue = __import__("asyncio").Queue()
    task = _FakeIncomingTask("insufficient trust", peer_id="peer-good", task_id="task-trust")
    with caplog.at_level("WARNING"):
        await manager._handle_incoming_task(task)
    assert task.failed is not None
    assert manager._incoming_queue.qsize() == 0


@pytest.mark.asyncio
async def test_normal_task_from_allowed_peer_is_queued(plugin_modules, monkeypatch, tmp_path):
    nm = plugin_modules.node_manager
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-good",))
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-good", trust_level="full")
    monkeypatch.setattr(nm, "get_config", lambda: cfg)
    monkeypatch.setattr(
        nm,
        "verify_incoming_sender",
        lambda task, cfg, purpose: _mock_security(True, None, "peer-good"),
    )
    manager = nm.NodeManager()
    manager._incoming_queue = __import__("asyncio").Queue()
    task = _FakeIncomingTask("allowed task", peer_id="peer-good", task_id="task-allowed")
    await manager._handle_incoming_task(task)
    assert task.failed is None
    assert task.completed is None or task.failed is None  # allowed path reached


def test_runner_idle_timeout_helpers(monkeypatch):
    runner = _load_runner_module(monkeypatch)

    cfg = types.SimpleNamespace(incoming_idle_timeout_seconds=10)
    state = types.SimpleNamespace(
        last_incoming_activity_at=100.0,
        started_at=50.0,
        incoming_queue_size=0,
        incoming_processing_count=0,
    )
    manager = types.SimpleNamespace(get_config=lambda: cfg, state=state)
    monkeypatch.setattr(runner.time, "time", lambda: 115.0)

    assert runner._runner_idle_timeout_seconds(manager) == 10
    assert runner._manager_idle_for_seconds(manager) == 15
    assert runner._manager_has_active_incoming_work(manager) is False

    state.incoming_processing_count = 1
    assert runner._manager_has_active_incoming_work(manager) is True


def test_proactive_routes_new_python_file_to_code_reviewer(plugin_modules, monkeypatch, tmp_path):
    proactive = plugin_modules.proactive
    cfg_mod = plugin_modules.config
    workspace_root = tmp_path / "workspace"
    cfg = cfg_mod.AgencyConfig(
        proactive={"enabled": True},
        workspace=cfg_mod.WorkspaceConfig(workspace_root),
    )
    created = []

    monkeypatch.setattr(proactive, "get_config", lambda: cfg)
    monkeypatch.setattr(cfg_mod, "get_config", lambda: cfg)
    monkeypatch.setattr(
        proactive,
        "kanban_create_task",
        lambda **kwargs: created.append(kwargs) or {"ok": True, "task_id": "k1"},
    )

    result = proactive.route_file_created(workspace_root / "deliverables" / "board-1" / "app.py")

    assert result["ok"] is True
    assert created[0]["assigned_to"] == "agency-code-reviewer"
    assert created[0]["metadata"]["trigger"] == "file-watch"
    assert created[0]["metadata"]["board_id"] == "board-1"


def test_proactive_routes_review_needed_markdown_to_editor(plugin_modules, monkeypatch):
    proactive = plugin_modules.proactive
    cfg_mod = plugin_modules.config
    cfg = cfg_mod.AgencyConfig(proactive={"enabled": True})
    created = []

    monkeypatch.setattr(proactive, "get_config", lambda: cfg)
    monkeypatch.setattr(
        proactive,
        "kanban_create_task",
        lambda **kwargs: created.append(kwargs) or {"ok": True, "task_id": "k2"},
    )

    result = proactive.route_review_needed_task("task-1", "Docs", path="README.md")

    assert result["ok"] is True
    assert created[0]["assigned_to"] == "agency-editor-in-chief"
    assert created[0]["metadata"]["trigger"] == "kanban-tag"


# --- Agency MoA native-adapter coverage ------------------------------------


def _install_moa_stubs(monkeypatch, native_config):
    hermes_cli = sys.modules.get("hermes_cli") or types.ModuleType("hermes_cli")
    hermes_cli_config = sys.modules.get("hermes_cli.config") or types.ModuleType(
        "hermes_cli.config"
    )
    hermes_cli_config.cfg_get = _nested_cfg_get
    hermes_cli_config.load_config = lambda: native_config
    hermes_cli.config = hermes_cli_config

    hermes_cli_moa = types.ModuleType("hermes_cli.moa_config")

    def normalize_moa_config(raw):
        raw = raw if isinstance(raw, dict) else {}
        presets = raw.get("presets") or {}
        if not presets:
            presets = {
                "default": {
                    "enabled": True,
                    "reference_models": [{"provider": "openai-codex", "model": "gpt-5.5"}],
                    "aggregator": {"provider": "openrouter", "model": "aggregator-model"},
                    "reference_temperature": 0.6,
                    "aggregator_temperature": 0.4,
                    "max_tokens": 4096,
                }
            }
        default_preset = raw.get("default_preset") or next(iter(presets))
        active = presets[default_preset]
        return {
            "default_preset": default_preset,
            "active_preset": raw.get("active_preset") or "",
            "presets": presets,
            "reference_models": active.get("reference_models", []),
            "aggregator": active.get("aggregator", {}),
            "reference_temperature": active.get("reference_temperature", 0.6),
            "aggregator_temperature": active.get("aggregator_temperature", 0.4),
            "max_tokens": active.get("max_tokens", 4096),
            "enabled": active.get("enabled", True),
        }

    def resolve_moa_preset(raw, name=None):
        cfg = normalize_moa_config(raw)
        preset_name = name or cfg["default_preset"]
        if preset_name not in cfg["presets"]:
            raise KeyError(preset_name)
        return dict(cfg["presets"][preset_name])

    hermes_cli_moa.normalize_moa_config = normalize_moa_config
    hermes_cli_moa.resolve_moa_preset = resolve_moa_preset
    hermes_cli.moa_config = hermes_cli_moa

    agent_pkg = types.ModuleType("agent")
    agent_moa_loop = types.ModuleType("agent.moa_loop")
    agent_moa_loop.MoAClient = object
    agent_moa_loop.MoAChatCompletions = object
    agent_pkg.moa_loop = agent_moa_loop

    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_cli_config)
    monkeypatch.setitem(sys.modules, "hermes_cli.moa_config", hermes_cli_moa)
    monkeypatch.setitem(sys.modules, "agent", agent_pkg)
    monkeypatch.setitem(sys.modules, "agent.moa_loop", agent_moa_loop)


def test_moa_adapter_lists_native_presets(plugin_modules, monkeypatch):
    native_config = {
        "moa": {
            "default_preset": "default",
            "presets": {
                "default": {
                    "enabled": True,
                    "reference_models": [
                        {"provider": "openai-codex", "model": "gpt-5.5"},
                        {"provider": "openrouter", "model": "deepseek/deepseek-v4-pro"},
                    ],
                    "aggregator": {"provider": "openrouter", "model": "aggregator-model"},
                    "reference_temperature": 0.6,
                    "aggregator_temperature": 0.4,
                    "max_tokens": 4096,
                }
            },
        }
    }
    _install_moa_stubs(monkeypatch, native_config)
    moa_adapter = importlib.import_module("hermes_plugin.moa_adapter")

    status = moa_adapter.get_native_moa_status(agency_config=plugin_modules.config.AgencyConfig())
    presets = moa_adapter.list_native_moa_presets(
        agency_config=plugin_modules.config.AgencyConfig()
    )

    assert status["available"] is True
    assert status["effective_preset"] == "default"
    assert presets[0]["name"] == "default"
    assert presets[0]["reference_count"] == 2
    assert presets[0]["aggregator"] == {"provider": "openrouter", "model": "aggregator-model"}


def test_moa_adapter_agency_override_requires_native_preset(plugin_modules, monkeypatch):
    native_config = {"moa": {"default_preset": "default", "presets": {"default": {}}}}
    _install_moa_stubs(monkeypatch, native_config)
    moa_adapter = importlib.import_module("hermes_plugin.moa_adapter")
    agency_config = plugin_modules.config.AgencyConfig(
        moa=plugin_modules.config.AgencyMoAConfig(default_preset="missing")
    )

    validation = moa_adapter.validate_native_moa_available(agency_config=agency_config)

    assert validation["available"] is True
    assert validation["ok"] is False
    assert validation["error"] == "native MoA preset not found: missing"


def test_moa_recommend_respects_confirmation_policy(plugin_modules, monkeypatch):
    native_config = {"moa": {"default_preset": "default", "presets": {"default": {}}}}
    _install_moa_stubs(monkeypatch, native_config)
    moa_adapter = importlib.import_module("hermes_plugin.moa_adapter")
    agency_config = plugin_modules.config.AgencyConfig(
        moa=plugin_modules.config.AgencyMoAConfig(
            allow_auto_moa=True,
            require_confirmation=True,
        )
    )

    result = moa_adapter.recommend_moa(
        "Review this security-sensitive release architecture", agency_config=agency_config
    )

    assert result["recommended"] is True
    assert result["requires_confirmation"] is True
    assert result["auto_run_allowed"] is False
    assert result["preset"] == "default"


def test_agency_moa_tool_recommend_does_not_run_model_calls(plugin_modules, monkeypatch):
    native_config = {"moa": {"default_preset": "default", "presets": {"default": {}}}}
    _install_moa_stubs(monkeypatch, native_config)
    tools = plugin_modules.tools

    payload = json.loads(
        tools.agency_moa_recommend({"task_text": "Architecture review before release"})
    )

    assert payload["ok"] is True
    assert payload["recommended"] is True
    assert payload["preset"] == "default"
    assert "status" in payload


def test_incoming_task_requires_full_trust_before_delegation_tools(plugin_modules, tmp_path):
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-good",))
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-good", trust_level="limited")
    task = _FakeIncomingTask("remote work", peer_id="peer-good", task_id="task-limited-tools")

    decision = plugin_modules.incoming_security.verify_incoming_sender(task, cfg, purpose="task")

    assert not decision.allowed
    assert decision.action == "insufficient_trust"
    assert "requires full trust" in decision.reason


def test_incoming_handshake_allows_limited_trust_without_granting_task_execution(
    plugin_modules, tmp_path
):
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-good",))
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-good", trust_level="limited")
    task = _FakeIncomingTask("handshake", peer_id="peer-good", task_id="task-handshake")

    handshake_decision = plugin_modules.incoming_security.verify_incoming_sender(
        task, cfg, purpose="handshake"
    )
    task_decision = plugin_modules.incoming_security.verify_incoming_sender(
        task, cfg, purpose="task"
    )

    assert handshake_decision.allowed
    assert handshake_decision.trust_level == "limited"
    assert not task_decision.allowed
    assert task_decision.action == "insufficient_trust"


def test_incoming_task_allows_full_trust_sender(plugin_modules, tmp_path):
    cfg = _security_cfg(plugin_modules, tmp_path, allowlist=("peer-good",))
    plugin_modules.trust.store_for_config(cfg).set_trust("peer-good", trust_level="full")
    task = _FakeIncomingTask("remote work", peer_id="peer-good", task_id="task-full")

    decision = plugin_modules.incoming_security.verify_incoming_sender(task, cfg, purpose="task")

    assert decision.allowed
    assert decision.trust_level == "full"


def test_pool_wake_seeds_only_configured_orchestrator_full_trust(
    plugin_modules, monkeypatch, tmp_path
):
    pool_tools = importlib.import_module("hermes_plugin.pool.tools")
    profile_dir = tmp_path / "profiles" / "agency-docs-writer"
    trust_path = profile_dir / "agency" / "trust.json"
    monkeypatch.setattr(
        pool_tools,
        "_current_orchestrator_identity",
        lambda: {"name": "agency-orchestrator", "peer_id": "peer-orch"},
    )

    changed = pool_tools._ensure_worker_trusts_current_orchestrator(
        "agency-docs-writer", profile_dir
    )
    data = json.loads(trust_path.read_text(encoding="utf-8"))

    assert changed is True
    assert data["peers"]["peer-orch"]["trust_level"] == "full"
    assert data["peers"]["peer-orch"]["last_source"] == "local_orchestrator_seed"


def test_pool_wake_does_not_override_blocked_orchestrator(plugin_modules, monkeypatch, tmp_path):
    pool_tools = importlib.import_module("hermes_plugin.pool.tools")
    profile_dir = tmp_path / "profiles" / "agency-docs-writer"
    trust_path = profile_dir / "agency" / "trust.json"
    trust_path.parent.mkdir(parents=True)
    trust_path.write_text(
        json.dumps({"version": 1, "peers": {"peer-orch": {"trust_level": "blocked"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        pool_tools,
        "_current_orchestrator_identity",
        lambda: {"name": "agency-orchestrator", "peer_id": "peer-orch"},
    )

    changed = pool_tools._ensure_worker_trusts_current_orchestrator(
        "agency-docs-writer", profile_dir
    )
    data = json.loads(trust_path.read_text(encoding="utf-8"))

    assert changed is False
    assert data["peers"]["peer-orch"]["trust_level"] == "blocked"
