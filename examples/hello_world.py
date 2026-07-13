"""Hermes Agency / Keryx hello world — two nodes on loopback.

This example shows the Keryx Python SDK used as Hermes Agency's primary
transport: register a skill, serve with ``on_task`` / ``serve_forever``, and
send a task that returns a terminal artifact.

Prerequisites:

1. Install this repo (vendors the Keryx Python SDK)::

     python -m pip install -e ".[dev]"

2. Build Keryx runtime binaries from the separate hermes-keryx repository
   (``keryxd``, ``keryx-relay`` / edge node as required by your dual-run setup).

3. Start local Keryx daemon (and relay/registry if required) on loopback.
   Typical dual-run daemon gRPC endpoint: ``127.0.0.1:50051``.

Run in two terminals (use placeholder peer IDs only in docs/logs)::

  # Terminal 1 — echo server
  python examples/hello_world.py server --daemon 127.0.0.1:50051

  # Terminal 2 — client (paste peer id from server output)
  python examples/hello_world.py client --daemon 127.0.0.1:50051 --peer <peer-id>

Legacy AgentAnycast demos remain under other ``examples/*`` files and are not
the recommended production path. Prefer Agency operator surfaces
(``hermes-agency doctor``, ``hermes-agency start``) for real staff profiles.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running from a source checkout without install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from keryx.card import AgentCard, Skill  # noqa: E402
from keryx.node import KeryxNode  # noqa: E402
from keryx.task import Message, Part  # noqa: E402


async def run_server(*, daemon_endpoint: str) -> None:
    card = AgentCard(
        name="EchoAgent",
        description="Echo agent for local Keryx / Hermes Agency transport checks",
        skills=[Skill(id="echo", description="Echo the input message back")],
    )
    node = KeryxNode(card=card, daemon_endpoint=daemon_endpoint)
    await node.start()
    try:
        peer = getattr(node, "peer_id", None) or "(peer id unavailable until connected)"
        print("Echo agent started")
        print(f"  daemon: {daemon_endpoint}")
        print(f"  peer:   {peer}")
        print("  waiting for tasks (Ctrl+C to stop)")
        print(
            "  client: python examples/hello_world.py client "
            f"--daemon {daemon_endpoint} --peer <peer-id>"
        )

        @node.on_task
        async def handle(task) -> None:  # type: ignore[no-untyped-def]
            text = "no message"
            messages = getattr(task, "messages", None) or []
            if messages:
                for part in getattr(messages[-1], "parts", []) or []:
                    if getattr(part, "text", None):
                        text = part.text
                        break
            print(f"  received: {text!r}")
            if hasattr(task, "update_status"):
                await task.update_status("working")
            response = f"Echo: {text}"
            if hasattr(task, "complete"):
                await task.complete(
                    artifacts=[{"name": "echo_result", "parts": [{"text": response}]}]
                )
            elif hasattr(task, "send_artifact"):
                await task.send_artifact(
                    [{"name": "echo_result", "parts": [{"text": response}]}]
                )

        await node.serve_forever()
    finally:
        close = getattr(node, "close", None) or getattr(node, "stop", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


async def run_client(*, daemon_endpoint: str, peer_id: str, message: str) -> None:
    card = AgentCard(
        name="ClientAgent",
        description="Client for local Keryx hello world",
        skills=[],
    )
    node = KeryxNode(card=card, daemon_endpoint=daemon_endpoint)
    await node.start()
    try:
        handle = await node.send_task(
            peer_id,
            Message(parts=[Part(text=message)]),
            skill_id="echo",
        )
        if hasattr(handle, "wait"):
            result = await handle.wait(timeout=60)
            print(f"result: {result!r}")
        else:
            print(f"submitted: {handle!r}")
    finally:
        close = getattr(node, "close", None) or getattr(node, "stop", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes Agency / Keryx hello world")
    parser.add_argument("role", choices=("server", "client"))
    parser.add_argument(
        "--daemon",
        default="127.0.0.1:50051",
        help="Keryx daemon gRPC endpoint (loopback recommended)",
    )
    parser.add_argument("--peer", default="", help="Target peer id (client mode)")
    parser.add_argument("--message", default="hello from Hermes Agency", help="Client message")
    args = parser.parse_args()

    if args.role == "server":
        asyncio.run(run_server(daemon_endpoint=args.daemon))
        return 0
    if not args.peer:
        parser.error("client mode requires --peer <peer-id>")
    asyncio.run(
        run_client(daemon_endpoint=args.daemon, peer_id=args.peer, message=args.message)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
