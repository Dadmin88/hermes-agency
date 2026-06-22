# Hermes Agency Hermes Plugin

P2P agent communication for [Hermes Agent](https://github.com/NousResearch/hermes-agent) profiles via the **Hermes Agency** plugin and bundled P2P SDK/runtime.

Each Hermes profile gets its own node with a persistent identity, an auto-generated AgentCard from `SOUL.md` + installed skills, and encrypted P2P communication with other agents.

> Naming note: this Hermes plugin is named `hermes-agency`, uses the `agency.*` config prefix, and registers `hermes agency` plus `/agency`. Some lower-level compatibility names remain `agentanycast` / `agentanycastd` because the runtime namespace has not been renamed yet.

## What It Does

- **Profile AgentCards** — generated from `SOUL.md`, installed skills, and a non-secret config allowlist.
- **Node lifecycle** — start/stop per-profile P2P nodes with persistent Ed25519 identity.
- **Peer discovery** — find agents by skill through LAN peer discovery plus relay-backed anycast registry.
- **Team context** — compact teammate summaries injected through plugin context, bounded by config budgets.
- **Task send/receive** — send tasks to peers, receive tasks from remote agents, return artifacts to the sender.
- **Safe incoming handler** — remote tasks default to safe/no-dangerous-tool behavior unless explicitly enabled.
- **Kanban tracking** — outbound and inbound A2A tasks reconcile with Hermes Kanban when available.
- **Autonomous collaboration helpers** — self-registration, bidding, workflows, proactive tasks, autonomy checks, and routing-correction logging.
- **CLI and slash command** — `hermes agency ...` and `/agency ...` for status/start/stop/discovery.

## Requirements

- Python 3.10+
- Hermes Agent with user-plugin support
- Optional at plugin-load time, required for live networking: the bundled SDK package (`pip install -e .` from this repo, or another compatible install)
- Optional for cross-network discovery: relay plus registry service reachable by the runtime daemon

The SDK is optional at plugin discovery time. If it is absent, the plugin should load cleanly and its tool check functions should gate A2A tools off.

## Install

### Option A: Symlink (development)

```bash
git clone https://github.com/DeployFaith/Hermes_Agency.git
mkdir -p ~/.hermes/profiles/<profile>/plugins
ln -s /path/to/Hermes_Agency/hermes-agency ~/.hermes/profiles/<profile>/plugins/hermes-agency
```

### Option B: Copy (standalone testing)

```bash
git clone https://github.com/DeployFaith/Hermes_Agency.git
cd Hermes_Agency
mkdir -p ~/.hermes/profiles/<profile>/plugins
cp -r hermes-agency ~/.hermes/profiles/<profile>/plugins/hermes-agency
```

### Option C: Bundled plugin (future upstream shape)

If this is ever upstreamed to `NousResearch/hermes-agent`, the plugin should remain optional and live under a bundled plugin directory such as `plugins/hermes-agency/`. The daemon/relay binaries should **not** be vendored into Hermes.

## Configuration

Add to the active profile's `config.yaml`:

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

For relay-backed skill discovery, set the daemon environment separately:

```bash
export AGENTANYCAST_REGISTRY_ADDRS=100.123.57.115:50052
```

Relay/bootstrap and skill registry are separate: `agency.relay` connects libp2p; `AGENTANYCAST_REGISTRY_ADDRS` enables anycast skill discovery in the current underlying runtime.

## Tools

| Tool | Description |
|------|-------------|
| `a2a_info` | Show plugin/SDK/card/node status; use `compact: true` for health checks |
| `a2a_start_node` | Start this profile's P2P node |
| `a2a_stop_node` | Stop the node cleanly |
| `a2a_list_peers` | List connected P2P peers |
| `a2a_discover` | Find agents by skill through anycast routing |
| `a2a_send` | Send a task to a `peer_id` or skill and optionally wait for completion |
| `a2a_status` | Check latest tracked status/artifacts for a sent task |
| `a2a_inbox` | Inspect recent incoming tasks |
| `a2a_registry` | List live self-registration records |
| `a2a_bid_task` | Record/simulate bids and optionally assign the best bidder |
| `a2a_execute_workflow` | Create dependency-linked Kanban tasks from configured workflows |
| `a2a_create_proactive_task` | Create proactive tasks when enabled |
| `a2a_check_autonomy` | Check autonomy policy for a proposed action |
| `a2a_log_routing_correction` | Record routing-correction feedback when learning is enabled |

Orchestrator-only tools are exposed only for the promoted/configured orchestrator profile:

- `orch_route`
- `orch_decompose`
- `orch_status`
- `orch_list_tasks`
- `orch_escalate`

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

Legacy pre-rename CLI/slash names are intentionally not the public command names after the rename. Model tool names remain `a2a_*`.

## Security Model

- Plugin loading is opt-in via `plugins.enabled`.
- Runtime operation is gated by `agency.enabled`.
- Remote task execution defaults to safe behavior; no terminal/file access is granted by default.
- The incoming processor can use delegation/subprocess modes only when explicitly configured.
- AgentCards expose only a non-secret metadata allowlist: provider/model names, configured booleans, and profile/toolset summaries. They must not expose API keys, raw env vars, Discord channel IDs, local daemon paths, or profile-private data.
- The daemon and relay are external runtime components. Do not vendor daemon/relay binaries into an upstream Hermes PR.

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

Each profile gets its own default daemon home:

```text
$HERMES_HOME/.agency/
```

The underlying standalone SDK default remains `~/.agentanycast`.

## Validation

From repo root:

```bash
python -m py_compile hermes-agency/*.py
pytest hermes-agency/tests/test_unit.py -q
python -m pip check
```

Manual/live P2P checks:

```bash
python hermes-agency/tests/test_e2e.py
python hermes-agency/tests/test_e2e_full.py
```

The lightweight `test_e2e.py` script starts real SDK nodes with isolated temporary daemon homes and does not use a registry/relay unless `AGENTANYCAST_E2E_REGISTRY` / `AGENTANYCAST_E2E_RELAY` are explicitly set. The full e2e script still exercises live profile/Kanban/relay assumptions and should remain explicit manual validation until those assumptions are converted to fixtures or test skips.

## License Notes

- This repository and the Python SDK are Apache-2.0.
- The daemon/relay are external runtime components with their own license terms and should not be bundled here.
- If the plugin is proposed for Hermes upstream, call out the license compatibility story explicitly and let maintainers decide whether a bundled plugin needs MIT relicensing or dual licensing.
