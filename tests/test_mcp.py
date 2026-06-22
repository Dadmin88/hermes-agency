"""Tests for MCP Tool <-> A2A Skill mapping utilities."""

import json

from agentanycast import AgentCard, Skill
from agentanycast.mcp import MCPTool, mcp_tool_to_skill, mcp_tools_to_agent_card, skill_to_mcp_tool


class TestMCPToolToSkill:
    def test_basic_conversion(self):
        tool = MCPTool(
            name="get_weather",
            description="Get current weather for a location",
            input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
        )
        skill = mcp_tool_to_skill(tool)
        assert skill.id == "get_weather"
        assert skill.description == "Get current weather for a location"
        assert skill.input_schema is not None
        schema = json.loads(skill.input_schema)
        assert schema["type"] == "object"
        assert "city" in schema["properties"]

    def test_empty_schema(self):
        tool = MCPTool(name="ping", description="Ping the server")
        skill = mcp_tool_to_skill(tool)
        assert skill.id == "ping"
        assert skill.input_schema is None

    def test_empty_description(self):
        tool = MCPTool(name="noop")
        skill = mcp_tool_to_skill(tool)
        assert skill.description == ""


class TestSkillToMCPTool:
    def test_basic_conversion(self):
        skill = Skill(
            id="analyze_csv",
            description="Analyze CSV data",
            input_schema=json.dumps({"type": "object", "properties": {"path": {"type": "string"}}}),
        )
        tool = skill_to_mcp_tool(skill)
        assert tool.name == "analyze_csv"
        assert tool.description == "Analyze CSV data"
        assert tool.input_schema["type"] == "object"

    def test_no_schema(self):
        skill = Skill(id="simple", description="Simple skill")
        tool = skill_to_mcp_tool(skill)
        assert tool.input_schema == {}

    def test_empty_string_schema(self):
        skill = Skill(id="empty", description="Empty schema", input_schema="")
        tool = skill_to_mcp_tool(skill)
        assert tool.input_schema == {}


class TestRoundTrip:
    def test_tool_to_skill_and_back(self):
        original = MCPTool(
            name="translate",
            description="Translate text",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "target_lang": {"type": "string"},
                },
                "required": ["text", "target_lang"],
            },
        )
        skill = mcp_tool_to_skill(original)
        recovered = skill_to_mcp_tool(skill)
        assert recovered.name == original.name
        assert recovered.description == original.description
        assert recovered.input_schema == original.input_schema

    def test_skill_to_tool_and_back(self):
        original = Skill(
            id="summarize",
            description="Summarize text",
            input_schema=json.dumps({"type": "object", "properties": {"text": {"type": "string"}}}),
        )
        tool = skill_to_mcp_tool(original)
        recovered = mcp_tool_to_skill(tool)
        assert recovered.id == original.id
        assert recovered.description == original.description
        assert json.loads(recovered.input_schema) == json.loads(original.input_schema)


class TestMCPToolsToAgentCard:
    def test_creates_agent_card(self):
        tools = [
            MCPTool(name="read_file", description="Read a file"),
            MCPTool(name="write_file", description="Write a file"),
        ]
        card = mcp_tools_to_agent_card("FileServer", tools, description="File operations")
        assert isinstance(card, AgentCard)
        assert card.name == "FileServer"
        assert card.description == "File operations"
        assert card.version == "1.0.0"
        assert len(card.skills) == 2
        assert card.skills[0].id == "read_file"
        assert card.skills[1].id == "write_file"

    def test_empty_tools(self):
        card = mcp_tools_to_agent_card("Empty", [])
        assert card.skills == []

    def test_custom_version(self):
        card = mcp_tools_to_agent_card("Test", [], version="2.0.0")
        assert card.version == "2.0.0"
