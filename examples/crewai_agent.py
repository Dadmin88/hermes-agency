"""Expose a CrewAI Crew as a P2P agent using AgentAnycast.

Prerequisites:
    pip install agentanycast[crewai]

Run:
    python examples/crewai_agent.py
"""

import asyncio

from crewai import Agent, Crew, Task

from agentanycast import AgentCard, Skill
from agentanycast.adapters.crewai import serve_crew


def build_crew() -> Crew:
    researcher = Agent(
        role="Researcher",
        goal="Find accurate information about the given topic",
        backstory="You are an expert researcher with deep analytical skills.",
    )
    task = Task(
        description="{input}",
        expected_output="A concise summary of findings",
        agent=researcher,
    )
    return Crew(agents=[researcher], tasks=[task])


async def main():
    crew = build_crew()
    card = AgentCard(
        name="Research Agent",
        description="Researches topics and provides concise summaries",
        skills=[
            Skill(id="research", description="Research any topic and summarize findings"),
        ],
    )

    print("Starting CrewAI agent on P2P network...")
    await serve_crew(crew, card=card, home="/tmp/agentanycast-crewai")


if __name__ == "__main__":
    asyncio.run(main())
