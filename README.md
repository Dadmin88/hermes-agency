# Hermes Agency

**The complete P2P multi-agent orchestration system for Hermes Agent.**

Hermes Agency provides an 83-agent specialized roster, intelligent orchestration, department-based Kanban routing, team context injection, and autonomous workflows — all running over a secure P2P network.

The AgentAnycast Python SDK (`src/agentanycast/`) is the underlying transport layer (daemon, Node API, A2A protocol). Hermes Agency is the star of this repository.

[![CI](https://github.com/DeployFaith/Hermes_Agency/actions/workflows/ci.yml/badge.svg)](https://github.com/DeployFaith/Hermes_Agency/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/hermes-agency?color=3776AB)](https://pypi.org/project/hermes-agency/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](LICENSE)

```bash
pip install hermes-agency
```

**Try the dashboard:**

```bash
hermes agency dashboard
```

Or start the full system:

## Quick Start

See the [Hermes Agency documentation](https://github.com/DeployFaith/Hermes_Agency/tree/main/hermes-agency) for full usage.

The underlying AgentAnycast SDK is available for advanced transport-level work.


# Anycast — by skill (relay resolves the target)
await node.send_task(skill="translate", message=msg)

# HTTP Bridge — to standard HTTP A2A agents
await node.send_task(url="https://agent.example.com", message=msg)
```

## CLI

Add `--verbose` (or `-v`) before any command for debug output:

```bash
hermes agency dashboard
```

```bash
hermes agency dashboard                        # Start an echo agent
hermes agency discover translate          # Find agents by skill
hermes agency send 12D3KooW... "Hello!"   # Send a task
hermes agency status                      # Check node status
hermes agency info                        # Show Peer ID, DID, version
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
- **WAN** -- deploy a [self-hosted relay](https://github.com/DeployFaith/agentanycast-relay (or original AgentAnycast relay)) and point agents to it.
- The Go daemon is **auto-downloaded and managed** by the SDK. No manual setup.

## MoA Integration

Hermes Agency can recommend and run native Hermes Agent Mixture-of-Agents presets for high-leverage Agency tasks, with Kanban tracking when available.

Hermes Agency integrates native Hermes Agent MoA. Native presets remain under top-level `moa:` in the active Hermes `config.yaml`; Agency policy lives separately under `agency.moa:`. Agency status, tools, dashboard endpoints, and orchestrator recommendations delegate to native Hermes Agent MoA instead of implementing an Agency-owned fan-out or aggregator runtime.

Useful commands:

```bash
hermes moa ls                         # Native Hermes Agent presets
hermes moa configure [name]           # Native preset editor
hermes agency moa status              # Agency policy + native status
hermes agency moa presets             # Native presets as seen by Agency
hermes agency moa show default        # Show one native preset
hermes agency moa recommend "Review this release architecture"
```

See `docs/agency-moa.md` for the integration contract, policy semantics, dashboard endpoints, and trace limits.

## Framework Adapters

Turn existing frameworks into P2P agents with one function call:

```bash
pip install hermes-agency[crewai]         # CrewAI
pip install hermes-agency[langgraph]      # LangGraph
pip install hermes-agency[google-adk]     # Google ADK
pip install hermes-agency[openai-agents]  # OpenAI Agents SDK
pip install hermes-agency[claude]         # Claude Agent SDK
pip install hermes-agency[strands]        # AWS Strands Agents
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

## Auto-Update

Hermes Agency ships with an auto-update system that keeps your installation current with every push to `main`. Any Hermes gateway on the machine is automatically restarted after an update.

**One-command install** (systemd timer, polls every 5 minutes):

```bash
./scripts/setup-auto-update.sh
```

This sets up a systemd user timer that:
- Polls `origin/main` every 5 minutes (configurable via `POLL_SECONDS=600`)
- Pulls new commits (with auto-stash if you have local changes)
- Discovers and restarts **all** running Hermes gateways on the machine
- Works for any configured gateway service name without hard-coded profile assumptions

**Manual run:**

```bash
./scripts/auto-update.sh               # pull + restart gateways
DRY_RUN=1 ./scripts/auto-update.sh     # check only, no changes
```

**Logs:** `~/.hermes/agency-update/update.log`

**Uninstall:**

```bash
./scripts/setup-auto-update.sh --remove
```

For headless servers without systemd --user, the setup script falls back to cron automatically.

## Docker

Run the full Hermes Agency stack with Docker Compose:

```bash
docker compose up --build
```

The default `agency` service performs setup, installs the packaged agency staff into a named Docker volume, initializes agency Kanban boards, starts the local agency node manager, and serves the dashboard at `http://127.0.0.1:8765`.

A session token is printed in the container logs unless `HERMES_DASHBOARD_TOKEN` is provided.

Optional environment variables:

```bash
HERMES_DASHBOARD_TOKEN=change-me \
HERMES_AGENCY_MODEL_SET=balanced \
AGENTANYCAST_RELAY=<relay-multiaddr> \
AGENTANYCAST_REGISTRY_ADDRS=<registry-address> \
docker compose up --build
```

Advanced modes use the same image:

```bash
docker compose --profile tools run --rm setup      # setup only
docker compose --profile split up node dashboard   # split node/dashboard services
```

The compose file uses a named Docker volume for runtime data, so no machine-specific host paths are required.

### Instant VPS Deploy (GitHub Actions)

For instant deploys to a VPS on every push, add a `deploy-vps.yml` workflow with your SSH secrets. The workflow uses the same `auto-update.sh` script — no duplicated logic.

Required secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`.

## Development

Prerequisite:

```bash
python -m pip install -e ".[dev]"    # Install in editable mode with dev deps
```

Canonical local checks:

```bash
make test-agency                     # Hermes Agency plugin unit tests (87 tests)
make lint-agency                     # Ruff check/format for the plugin
make test                            # SDK tests + Hermes Agency unit tests
mypy src/                            # Type check SDK (strict)
```

The default pytest configuration skips tests marked `integration`. Run live daemon/relay checks manually with:

```bash
make integration-agency              # isolated local daemon homes; optional relay via env vars
make integration-agency-full         # live profile/Kanban/relay validation
```

## Requirements

- Python 3.10+
- The [agentanycastd](https://github.com/DeployFaith/agentanycast-node (or original)) daemon (auto-managed by the SDK)

---

**Hermes Agency** (this repo) is the primary project. The AgentAnycast Python SDK is the P2P foundation included here. See `hermes-agency/AGENTS.md` and the roster of 83 specialized agents.

## License

[Apache License, Version 2.0](LICENSE)
