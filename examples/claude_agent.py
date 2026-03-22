"""Expose a Claude Agent SDK agent as a P2P agent using AgentAnycast.

Prerequisites:
    pip install agentanycast[claude]

Run:
    python examples/claude_agent.py
"""

import asyncio

from agentanycast import AgentCard, Skill
from agentanycast.adapters.claude_agent import serve_claude_agent


async def main():
    card = AgentCard(
        name="Claude Translator",
        description="Translates text between languages using Claude",
        skills=[
            Skill(id="translate", description="Translate text between any languages"),
        ],
    )

    print("Starting Claude Agent on P2P network...")
    await serve_claude_agent(
        prompt_template=(
            "You are a professional translator. "
            "Translate the following text as requested. "
            "Return only the translated text, no explanations."
        ),
        card=card,
        home="/tmp/agentanycast-claude",
    )


if __name__ == "__main__":
    asyncio.run(main())
