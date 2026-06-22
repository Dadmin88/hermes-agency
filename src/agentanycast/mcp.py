"""MCP Tool to A2A Skill mapping utilities.

Provides bidirectional conversion between MCP (Model Context Protocol) Tool
definitions and A2A Skill definitions, reducing the switching cost for
developers moving between the two ecosystems.

MCP Tool mapping::

    MCP tool.name        -> Skill.id
    MCP tool.description -> Skill.description
    MCP tool.inputSchema -> Skill.input_schema (JSON string)

Example::

    from agentanycast.mcp import mcp_tool_to_skill, MCPTool

    tool = MCPTool(
        name="get_weather",
        description="Get current weather for a location",
        input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
    )
    skill = mcp_tool_to_skill(tool)
    # skill.id == "get_weather"
    # skill.description == "Get current weather for a location"
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agentanycast.card import AgentCard, Skill


@dataclass
class MCPTool:
    """Represents an MCP Tool definition (MCP v2.x compatible)."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


def mcp_tool_to_skill(tool: MCPTool) -> Skill:
    """Convert an MCP Tool definition to an A2A Skill.

    Args:
        tool: An MCP Tool definition.

    Returns:
        An equivalent A2A Skill.
    """
    input_schema_str = json.dumps(tool.input_schema) if tool.input_schema else None
    return Skill(
        id=tool.name,
        description=tool.description,
        input_schema=input_schema_str,
    )


def skill_to_mcp_tool(skill: Skill) -> MCPTool:
    """Convert an A2A Skill to an MCP Tool definition.

    Args:
        skill: An A2A Skill.

    Returns:
        An equivalent MCP Tool definition.
    """
    input_schema: dict[str, Any] = {}
    if skill.input_schema:
        input_schema = json.loads(skill.input_schema)

    return MCPTool(
        name=skill.id,
        description=skill.description,
        input_schema=input_schema,
    )


def mcp_tools_to_agent_card(
    server_name: str,
    tools: list[MCPTool],
    *,
    description: str = "",
    version: str = "1.0.0",
) -> AgentCard:
    """Create an AgentCard from a list of MCP Tool definitions.

    Useful for wrapping an MCP server's capabilities as an A2A agent.

    Args:
        server_name: Name for the agent card.
        tools: List of MCP Tool definitions from the server.
        description: Optional agent description.
        version: Agent version string.

    Returns:
        An AgentCard with skills derived from the tools.
    """
    skills = [mcp_tool_to_skill(t) for t in tools]
    return AgentCard(
        name=server_name,
        description=description,
        version=version,
        skills=skills,
    )
