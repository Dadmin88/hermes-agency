"""Skill-based anycast routing — send tasks by capability, not by address.

This example starts multiple agents with different skills, then demonstrates
how a client can find and reach them by skill name without knowing their PeerID.

Prerequisites:
    pip install agentanycast

Run three terminals:
    python examples/anycast_routing.py translate
    python examples/anycast_routing.py summarize
    python examples/anycast_routing.py client
"""

import argparse
import asyncio
from pathlib import Path

from agentanycast import AgentCard, Node, Skill

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DAEMON_BIN = _REPO_ROOT / "agentanycast-node" / "agentanycastd"
DAEMON_PATH = str(_DAEMON_BIN) if _DAEMON_BIN.exists() else None


async def run_translate_agent():
    card = AgentCard(
        name="TranslateAgent",
        description="Translates text to Spanish",
        skills=[Skill(id="translate", description="Translate text to Spanish")],
    )
    async with Node(card=card, daemon_path=DAEMON_PATH, home="/tmp/aa-translate") as node:
        print(f"Translate Agent started: {node.peer_id}")

        @node.on_task
        async def handle(task):
            text = task.messages[-1].parts[0].text if task.messages else ""
            await task.complete(
                artifacts=[{"parts": [{"text": f"[Spanish translation of: {text}]"}]}]
            )

        await node.serve_forever()


async def run_summarize_agent():
    card = AgentCard(
        name="SummarizeAgent",
        description="Summarizes long text",
        skills=[Skill(id="summarize", description="Summarize text into key points")],
    )
    async with Node(card=card, daemon_path=DAEMON_PATH, home="/tmp/aa-summarize") as node:
        print(f"Summarize Agent started: {node.peer_id}")

        @node.on_task
        async def handle(task):
            text = task.messages[-1].parts[0].text if task.messages else ""
            await task.complete(artifacts=[{"parts": [{"text": f"[Summary of: {text[:50]}...]"}]}])

        await node.serve_forever()


async def run_client():
    card = AgentCard(name="Client", description="Client", skills=[])
    async with Node(card=card, daemon_path=DAEMON_PATH, home="/tmp/aa-client") as node:
        print(f"Client started: {node.peer_id}\n")

        # Discover agents by skill
        for skill_name in ["translate", "summarize"]:
            agents = await node.discover(skill_name)
            print(f"Found {len(agents)} agent(s) for '{skill_name}': {agents}")

        # Send by skill — the network finds the right agent
        print("\nSending task by skill 'translate'...")
        task = await node.send_task(
            skill="translate",
            message={"role": "user", "parts": [{"text": "Hello, world!"}]},
        )
        result = await task.wait(timeout=30)
        print(f"Result: {result.artifacts[0].parts[0].text}")

        print("\nSending task by skill 'summarize'...")
        task = await node.send_task(
            skill="summarize",
            message={"role": "user", "parts": [{"text": "A very long document..."}]},
        )
        result = await task.wait(timeout=30)
        print(f"Result: {result.artifacts[0].parts[0].text}")


def main():
    parser = argparse.ArgumentParser(description="Anycast routing example")
    parser.add_argument("role", choices=["translate", "summarize", "client"])
    args = parser.parse_args()

    runners = {
        "translate": run_translate_agent,
        "summarize": run_summarize_agent,
        "client": run_client,
    }
    try:
        asyncio.run(runners[args.role]())
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
