# Hermes Agency

**Hermes Agency is a P2P collaboration layer for Hermes Agent profiles, backed by its bundled P2P SDK/runtime.** It lets local and remote Hermes profiles discover each other, advertise skills, send A2A tasks, return artifacts, and coordinate multi-agent work across LAN or relay-backed networks.

This repository currently contains two related pieces:

1. **Hermes plugin** — `hermes-agency/`, a standalone Hermes user plugin that registers the `agency` toolset, `a2a_*` tools, `hermes agency` CLI command, and `/agency` slash command.
2. **Bundled P2P SDK** — `src/agentanycast/`, the lower-level Python package used by the plugin. Some compatibility names are still `agentanycast` because the runtime and generated protocol namespace have not been renamed yet.

> Naming note: the Hermes-facing product/plugin is **Hermes Agency**. Some lower-level compatibility names still use `agentanycast`, including the Python import, daemon binary (`agentanycastd`), and registry env var (`AGENTANYCAST_REGISTRY_ADDRS`). Public Hermes-facing docs and commands should say Hermes Agency.

[![CI](https://github.com/DeployFaith/Hermes_Agency/actions/workflows/ci.yml/badge.svg)](https://github.com/DeployFaith/Hermes_Agency/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](LICENSE)

---

## What Hermes Agency Does

- **Per-profile nodes** — each Hermes profile can run its own persistent P2P node and identity.
- **Profile-derived AgentCards** — cards are generated from `SOUL.md`, installed Hermes skills, and a non-secret config allowlist.
- **Skill discovery** — find teammate agents by skill over LAN discovery and/or relay-backed registry lookup.
- **A2A task delegation** — send tasks to a peer ID or skill and receive artifacts back.
- **Incoming task processing** — receive remote A2A tasks with conservative safe defaults.
- **Team context injection** — optionally inject compact teammate summaries into Hermes turns using plugin context hooks.
- **Kanban bridge** — reconcile outbound/inbound A2A tasks with Hermes Kanban when available.
- **Autonomous collaboration helpers** — self-registration, bidding, workflows, proactive tasks, autonomy checks, and routing-correction feedback.

---

## Quick Start: Hermes Plugin

### 1. Clone this repository

```bash
git clone https://github.com/DeployFaith/Hermes_Agency.git
cd Hermes_Agency
```

### 2. Install or expose the SDK

For local development, install the bundled SDK package from this checkout into the same Python environment Hermes uses:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Hermes installations often use their own venv. If you want the plugin available inside a specific Hermes install, use that Hermes venv's Python instead of the example `.venv` above.

### 3. Install the plugin into a Hermes profile

Development symlink:

```bash
mkdir -p ~/.hermes/profiles/<profile>/plugins
ln -s /path/to/Hermes_Agency/hermes-agency ~/.hermes/profiles/<profile>/plugins/hermes-agency
```

Standalone copy:

```bash
mkdir -p ~/.hermes/profiles/<profile>/plugins
cp -r hermes-agency ~/.hermes/profiles/<profile>/plugins/hermes-agency
```

### 4. Enable the plugin

Add this to the target profile's `config.yaml`:

```yaml
plugins:
  enabled:
    - hermes-agency

agency:
  enabled: true
  auto_start: false
  relay: null
  skills_from_profile: true
  allow_remote_tasks: false
```

Then start a fresh Hermes session or restart the gateway/desktop process for the plugin and tool surface to reload.

### 5. Verify

```bash
hermes -p <profile> agency status
```

Inside a Hermes session:

```text
/agency status
```

---

## Core Hermes Tool Surface

The model-facing tool names intentionally remain `a2a_*` because A2A is the protocol surface, not the plugin name.

| Tool | Description |
|---|---|
| `a2a_info` | Show plugin/SDK/card/node status; accepts `compact: true` for health checks |
| `a2a_start_node` | Start this profile's P2P node |
| `a2a_stop_node` | Stop this profile's P2P node |
| `a2a_list_peers` | List connected P2P peers |
| `a2a_discover` | Find agents by skill through anycast routing |
| `a2a_send` | Send a task to a `peer_id` or skill and optionally wait for completion |
| `a2a_status` | Check locally tracked task status/artifacts |
| `a2a_inbox` | Inspect recent incoming tasks |
| `a2a_registry` | List live self-registration records |
| `a2a_bid_task` | Record/simulate bids and optionally assign the best bidder |
| `a2a_execute_workflow` | Create dependency-linked Kanban tasks from configured workflows |
| `a2a_create_proactive_task` | Create proactive tasks when enabled |
| `a2a_check_autonomy` | Check autonomy policy for a proposed action |
| `a2a_log_routing_correction` | Record routing-correction feedback when learning is enabled |

Orchestrator-only tools are registered only for the configured orchestrator profile:

- `orch_route`
- `orch_decompose`
- `orch_status`
- `orch_list_tasks`
- `orch_escalate`

---

## CLI / Slash Commands

```bash
hermes agency status
hermes agency start
hermes agency stop
hermes agency discover <skill>
hermes agency registry
hermes agency promote <profile>
hermes agency demote <profile>
```

In a Hermes session:

```text
/agency status
/agency start
/agency stop
/agency discover <skill>
/agency registry
```

Legacy pre-rename CLI/slash names are not registered as the public Hermes Agency command surface. The `a2a_*` model tools remain unchanged.

---

## Configuration Reference

Full example:

```yaml
plugins:
  enabled:
    - hermes-agency

agency:
  enabled: true                 # runtime gate after the plugin itself is enabled
  auto_start: false             # true = start node on session/plugin load
  relay: null                   # libp2p relay multiaddr for cross-network transport
  skills_from_profile: true     # generate AgentCard skills from installed Hermes skills
  allow_remote_tasks: false     # false = safe stub / no real execution
  trusted_peers: []
  incoming_queue_limit: 100
  card_name: null               # optional public display name override
  home: null                    # default: $HERMES_HOME/.agency
  daemon_bin: null              # optional explicit agentanycastd path
  incoming:
    mode: delegation            # template, delegation, subprocess
    delegation_timeout: 120
    tool_access: safe           # safe, none, full
    max_iterations: 25
    subprocess_profile: null
    reject_unmatched_skills: false
    send_progress: false
    conversation_ttl: 3600
    conversation_max_turns: 20
  team:
    auto_discover: true
    auto_register: true
    inject_context: true
    kanban_integration: true
    self_serve: true
    announce_progress: false
    tenant: default
    context_refresh_minutes: 5
    max_context_peers: 5
    max_context_skills: 5
    context_max_chars: 4000
  orchestrator:
    enabled: false
    agent: null
    auto_decompose: true
  routing: {}
  autonomy: {}
  workflows: {}
```

Relay/bootstrap and skill registry are separate:

- `agency.relay` configures the libp2p relay/bootstrap multiaddr.
- `AGENTANYCAST_REGISTRY_ADDRS=<host>:50052` configures the current anycast skill registry used by the underlying runtime.

Example:

```bash
export AGENTANYCAST_REGISTRY_ADDRS=100.123.57.115:50052
```

---

## Bundled SDK Quick Start

Low-level SDK imports currently use the compatibility package name:

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

Task addressing modes:

```python
await node.send_task(peer_id="12D3KooW...", message=msg)       # direct peer
await node.send_task(skill="translate", message=msg)           # skill/anycast routing
await node.send_task(url="https://agent.example.com", message=msg)  # HTTP bridge
```

## Architecture

```text
Hermes profile
├── config.yaml          → agency.* settings
├── SOUL.md              → AgentCard name/description source
├── skills/**/SKILL.md   → AgentCard skill source
└── plugins/hermes-agency/
    ├── plugin.yaml      → plugin metadata
    ├── __init__.py      → tool/CLI/slash/hook registration
    ├── config.py        → profile-safe config resolver
    ├── card_builder.py  → AgentCard builder with secret-safe metadata
    ├── node_manager.py  → daemon/node lifecycle, incoming queue, registry refresh
    ├── tools.py         → a2a_* model tools
    ├── orchestrator.py  → orch_* model tools
    └── *_bridge.py      → Kanban/team/context helpers
```

Transport/runtime:

```text
Hermes Agency plugin
        │
        ▼
bundled P2P SDK
        │ gRPC over Unix socket
        ▼
agentanycastd Go daemon
        │ libp2p + Noise encryption
        ▼
LAN peers / relay-backed peers / registry discovery
```

Each Hermes profile gets an isolated default daemon home:

```text
$HERMES_HOME/.agency/
```

The lower-level SDK default remains `~/.agentanycast` when used outside Hermes Agency.

---

## Security Model

- Plugin loading is opt-in via `plugins.enabled`.
- Runtime operation is gated by `agency.enabled`.
- Remote task execution defaults to conservative safe behavior.
- Incoming task processing uses delegation/subprocess modes only when explicitly configured.
- AgentCards expose only non-secret metadata: model/provider names, configured booleans, and skill/profile summaries.
- AgentCards must not expose API keys, tokens, Discord channel IDs, raw env vars, local daemon paths, or profile-private data.
- The daemon and relay are external runtime components; do not vendor daemon/relay binaries into a Hermes upstream PR.

---

## Development / Validation

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

python -m py_compile hermes-agency/*.py
pytest hermes-agency/tests/test_unit.py -q
pytest tests/ -q
ruff check .
ruff format --check .
mypy src/ --exclude '_generated'
```

Manual/live P2P checks:

```bash
python hermes-agency/tests/test_e2e.py
python hermes-agency/tests/test_e2e_full.py
```

The lightweight `hermes-agency/tests/test_e2e.py` script uses isolated temporary daemon homes and does not use a registry/relay unless `AGENTANYCAST_E2E_REGISTRY` / `AGENTANYCAST_E2E_RELAY` are explicitly set. The full e2e script still exercises live profile/Kanban/relay assumptions and should remain explicit manual validation until those assumptions are converted to fixtures or skips.

---

## Repository Layout

```text
hermes-agency/         Hermes Agent plugin
src/agentanycast/      Bundled SDK package (compatibility import path)
examples/              SDK examples
tests/                 SDK tests
.github/               GitHub workflows/templates
docs/                  Development notes and historical patch notes
```

---

## License

[Apache License, Version 2.0](LICENSE)

If the Hermes plugin is proposed for `NousResearch/hermes-agent`, call out the license compatibility story explicitly and let maintainers decide whether a bundled plugin needs MIT relicensing or dual licensing.
