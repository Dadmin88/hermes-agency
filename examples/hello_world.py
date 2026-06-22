"""AgentAnycast Hello World — Two agents on the same machine, zero configuration.

This example demonstrates how two AI agents discover each other via mDNS
and exchange A2A tasks — no public IP, no relay, no configuration.

┌─────────────────────────────────────────────────┐
│  Prerequisites:                                 │
│                                                 │
│  1. Build the Go daemon:                        │
│     cd agentanycast-node                        │
│     go build -o agentanycastd ./cmd/agentanycastd/
│                                                 │
│  2. Install the Python SDK:                     │
│     cd agentanycast-python                      │
│     pip install -e .                            │
└─────────────────────────────────────────────────┘

Run in two terminals:

  # Terminal 1 — Start the Echo Agent (server)
  python examples/hello_world.py server

  # Terminal 2 — Send a task to it (client)
  python examples/hello_world.py client <PEER_ID from Terminal 1>
"""

import argparse
import asyncio
from pathlib import Path

from agentanycast import AgentCard, Node, Skill

# ── Resolve the daemon binary path ──────────────────────────
# Look for the binary in the sibling agentanycast-node directory,
# or fall back to finding it on PATH.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DAEMON_BIN = _REPO_ROOT / "agentanycast-node" / "agentanycastd"
DAEMON_PATH = str(_DAEMON_BIN) if _DAEMON_BIN.exists() else None


async def run_server():
    """Run the Echo Agent — listens for tasks and echoes them back."""
    card = AgentCard(
        name="EchoAgent",
        description="A simple agent that echoes back any message it receives",
        skills=[Skill(id="echo", description="Echo the input message back")],
    )

    # Use a dedicated home directory so server and client don't collide.
    async with Node(card=card, daemon_path=DAEMON_PATH, home="/tmp/agentanycast-server") as node:
        print()
        print("╔══════════════════════════════════════════════════════════╗")
        print("║  Echo Agent started!                                    ║")
        print("╠══════════════════════════════════════════════════════════╣")
        print(f"║  Peer ID: {node.peer_id}  ║")
        print("║                                                          ║")
        print("║  Waiting for tasks... (Ctrl+C to stop)                   ║")
        print("║                                                          ║")
        print("║  In another terminal, run:                               ║")
        print(f"║  python examples/hello_world.py client {node.peer_id}  ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print()

        @node.on_task
        async def handle(task):
            # Extract the text from the incoming message
            text = "no message"
            if task.messages:
                for part in task.messages[-1].parts:
                    if part.text:
                        text = part.text
                        break

            print(f"  ← Received task from {task.peer_id[:16]}...")
            print(f'    Message: "{text}"')

            # Process and respond
            await task.update_status("working")
            response = f"Echo: {text}"
            await task.complete(artifacts=[{"name": "echo_result", "parts": [{"text": response}]}])
            print(f'    Response: "{response}"')
            print("  Task completed.\n")

        await node.serve_forever()


async def run_client(peer_id: str):
    """Run the Client Agent — sends a task and waits for the result."""
    card = AgentCard(
        name="ClientAgent",
        description="Sends tasks to other agents",
        skills=[],
    )

    # Use a separate home directory from the server.
    async with Node(card=card, daemon_path=DAEMON_PATH, home="/tmp/agentanycast-client") as node:
        print()
        print(f"  Client started. My Peer ID: {node.peer_id}")
        print(f"  Connecting to {peer_id[:16]}...")
        print()

        # Discover the remote agent's capabilities
        try:
            remote_card = await node.get_card(peer_id)
            print(f"  Remote agent: {remote_card.name}")
            print(f"  Description:  {remote_card.description}")
            print(f"  Skills:       {[s.id for s in remote_card.skills]}")
            print()
        except Exception:
            print("  (Could not fetch remote card -- sending task anyway)")
            print()

        # Send a task
        message_text = "Hello from AgentAnycast!"
        print(f'  → Sending: "{message_text}"')

        task = await node.send_task(
            peer_id=peer_id,
            message={
                "role": "user",
                "parts": [{"text": message_text}],
            },
        )

        print(f"    Task ID: {task.task_id}")
        print("    Waiting for response...")

        # Wait for the result
        result = await task.wait(timeout=30)

        # Display the result
        for artifact in result.artifacts:
            for part in artifact.parts:
                if part.text:
                    print(f'  ← Response: "{part.text}"')

        print()
        print("  ✓ Round-trip complete!")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="AgentAnycast Hello World — two agents communicating via P2P",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python examples/hello_world.py server
  python examples/hello_world.py client 12D3KooW...
        """,
    )
    parser.add_argument(
        "role",
        choices=["server", "client"],
        help="'server' to start the Echo Agent, 'client' to send a task",
    )
    parser.add_argument(
        "peer",
        nargs="?",
        help="Peer ID of the server (required for client role)",
    )
    args = parser.parse_args()

    if args.role == "client" and not args.peer:
        parser.error("client role requires a Peer ID argument")

    try:
        if args.role == "server":
            asyncio.run(run_server())
        else:
            asyncio.run(run_client(args.peer))
    except KeyboardInterrupt:
        print("\n  Stopped.")


if __name__ == "__main__":
    main()
