"""Expose an AWS Strands Agent as a P2P agent using AgentAnycast.

Prerequisites:
    pip install agentanycast[strands]

Run:
    python examples/strands_agent.py
"""

import asyncio

from strands import Agent

from agentanycast import AgentCard, Skill
from agentanycast.adapters.strands import serve_strands_agent


async def main():
    agent = Agent(
        system_prompt="You are a helpful coding assistant that writes clean, well-documented code.",
    )

    card = AgentCard(
        name="Code Helper",
        description="Helps with coding questions and generates code snippets",
        skills=[
            Skill(id="code-help", description="Answer coding questions and generate code"),
        ],
    )

    print("Starting Strands Agent on P2P network...")
    await serve_strands_agent(agent, card=card, home="/tmp/agentanycast-strands")


if __name__ == "__main__":
    asyncio.run(main())
