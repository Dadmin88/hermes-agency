# AgentAnycast Python SDK

**Build P2P agents in Python.** Discover, communicate, and collaborate with AI agents across any network -- encrypted, decentralized, NAT-traversing.

[![CI](https://github.com/AgentAnycast/agentanycast-python/actions/workflows/ci.yml/badge.svg)](https://github.com/AgentAnycast/agentanycast-python/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agentanycast?color=3776AB)](https://pypi.org/project/agentanycast/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](LICENSE)

```bash
pip install agentanycast
```

**Try it now** -- start a demo agent in one command:

```bash
agentanycast demo
```

The daemon downloads automatically on first run. The demo prints the exact command to test it from another terminal.

## Quick Start

**Create an agent:**

```python
from agentanycast import Node, AgentCard, Skill

card = AgentCard(
    name="EchoAgent",
    description="Echoes back any message",
    skills=[Skill(id="echo", description="Echo the input")],
)

async with Node(card=card) as node:
    @node.on_task
    async def handle(task):
        text = task.messages[-1].parts[0].text
        await task.complete(artifacts=[{"parts": [{"text": f"Echo: {text}"}]}])

    print(f"Agent running — Peer ID: {node.peer_id}")
    await node.serve_forever()
```

**Send a task to another agent:**

```python
async with Node(card=card) as node:
    handle = await node.send_task(
        peer_id="12D3KooW...",
        message={"role": "user", "parts": [{"text": "Hello!"}]},
    )
    result = await handle.wait()
    print(result.artifacts[0].parts[0].text)  # "Echo: Hello!"
```

## Three Ways to Send a Task

```python
# Direct — by Peer ID
await node.send_task(peer_id="12D3KooW...", message=msg)

# Anycast — by skill (relay resolves the target)
await node.send_task(skill="translate", message=msg)

# HTTP Bridge — to standard HTTP A2A agents
await node.send_task(url="https://agent.example.com", message=msg)
```

## CLI

Add `--verbose` (or `-v`) before any command for debug output:

```bash
agentanycast --verbose demo
```

```bash
agentanycast demo                        # Start an echo agent
agentanycast discover translate          # Find agents by skill
agentanycast send 12D3KooW... "Hello!"   # Send a task
agentanycast status                      # Check node status
agentanycast info                        # Show Peer ID, DID, version
```

## How It Works

```
┌─────────────┐         mDNS / Relay         ┌─────────────┐
│  Agent A    │<------------------------------>│  Agent B    │
│  (Python)   │     E2E encrypted (Noise)     │  (Python)   │
└──────┬──────┘                               └──────┬──────┘
       | gRPC                                        | gRPC
┌──────┴──────┐                               ┌──────┴──────┐
│ agentanycastd│                               │ agentanycastd│
│  (Go daemon)│<---------- libp2p ------------>│  (Go daemon) │
└─────────────┘                               └──────────────┘
```

- **LAN** -- agents discover each other via mDNS. Zero configuration.
- **WAN** -- deploy a [self-hosted relay](https://github.com/AgentAnycast/agentanycast-relay) and point agents to it.
- The Go daemon is **auto-downloaded and managed** by the SDK. No manual setup.

## Framework Adapters

Turn existing frameworks into P2P agents with one function call:

```bash
pip install agentanycast[crewai]         # CrewAI
pip install agentanycast[langgraph]      # LangGraph
pip install agentanycast[google-adk]     # Google ADK
pip install agentanycast[openai-agents]  # OpenAI Agents SDK
pip install agentanycast[claude]         # Claude Agent SDK
pip install agentanycast[strands]        # AWS Strands Agents
```

```python
from agentanycast.adapters.crewai import serve_crew
from agentanycast.adapters.langgraph import serve_graph
from agentanycast.adapters.adk import serve_adk_agent
from agentanycast.adapters.openai_agents import serve_openai_agent
from agentanycast.adapters.claude_agent import serve_claude_agent
from agentanycast.adapters.strands import serve_strands_agent

await serve_crew(crew, card=card, relay="...")
await serve_graph(graph, card=card, relay="...")
await serve_adk_agent(agent, card=card, relay="...")
await serve_openai_agent(agent, card=card, relay="...")
await serve_claude_agent(prompt_template="...", card=card)
await serve_strands_agent(agent, card=card)
```

## Skill Discovery

```python
agents = await node.discover("translate")
agents = await node.discover("translate", tags={"lang": "fr"})
```

## Interoperability

```python
# W3C DID
from agentanycast.did import peer_id_to_did_key, did_key_to_peer_id
did = peer_id_to_did_key("12D3KooW...")      # "did:key:z6Mk..."
pid = did_key_to_peer_id("did:key:z6Mk...")  # "12D3KooW..."

# MCP Tool <-> A2A Skill mapping
from agentanycast.mcp import mcp_tools_to_agent_card
card = mcp_tools_to_agent_card(mcp_tools, name="MCPAgent")

# A2A v1.0 JSON format
from agentanycast.compat.a2a_v1 import task_to_a2a_json, task_from_a2a_json

# OASF / AGNTCY Directory
from agentanycast.compat.oasf import card_to_oasf_record
from agentanycast.compat.agntcy import AGNTCYDirectory
```

## API Reference

### Node

| Method | Description |
|---|---|
| `Node(card, relay?, home?, ...)` | Create a node with an AgentCard and optional config |
| `async with Node(...) as node` | Context manager -- starts/stops daemon automatically |
| `send_task(peer_id?, skill?, url?, message=)` | Send a task using any addressing mode |
| `discover(skill, tags?)` | Find agents by skill with optional tag filtering |
| `on_task(handler)` | Register handler for incoming tasks |
| `serve_forever()` | Block and process incoming tasks until stopped |

### Core Types

| Class | Description |
|---|---|
| `AgentCard` | Agent identity, capabilities, and metadata |
| `Skill` | A single capability an agent can perform |
| `TaskHandle` | Returned by `send_task()`. Call `wait()` for the result. |
| `IncomingTask` | Passed to task handlers. Provides message data and response methods. |

### Node Options

| Parameter | Description | Default |
|---|---|---|
| `card` | Agent's `AgentCard` | Required |
| `relay` | Relay multiaddr for cross-network communication | `None` (LAN only) |
| `daemon_path` | Path to a local `agentanycastd` binary | Auto-download |
| `daemon_addr` | Address of an externally managed daemon | Auto-managed |
| `key_path` | Path to Ed25519 identity key file | `<home>/key` |
| `home` | Data directory. Use different values for multiple nodes. | `~/.agentanycast` |
| `status_callback` | Optional callback for progress messages (download, startup) | `None` |

## Development

```bash
pip install -e ".[dev]"    # Install in editable mode with dev deps
pytest                     # Run all tests
ruff check .               # Lint
ruff format .              # Format
mypy src/                  # Type check (strict)
```

## Requirements

- Python 3.10+
- The [agentanycastd](https://github.com/AgentAnycast/agentanycast-node) daemon (auto-managed by the SDK)

---

**Part of [AgentAnycast](https://github.com/AgentAnycast/agentanycast)** -- see the main repo for architecture docs, protocol reference, and examples.

## License

[Apache License, Version 2.0](LICENSE)
