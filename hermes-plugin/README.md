# AgentAnycast Hermes Plugin

P2P agent communication for [Hermes Agent](https://github.com/NousResearch/hermes-agent) profiles via [AgentAnycast](https://github.com/AgentAnycast/agentanycast).

Each Hermes profile gets its own AgentAnycast node with a persistent identity, auto-generated AgentCard from SOUL.md + installed skills, and encrypted P2P communication with other agents.

## What It Does

- **Profile AgentCards** — auto-generated from SOUL.md, installed skills, and config
- **Node lifecycle** — start/stop per-profile P2P nodes with persistent Ed25519 identity
- **Peer discovery** — find agents by skill via LAN (mDNS) or relay (anycast)
- **Task send/receive** — send tasks to peers, receive tasks from remote agents
- **Safe incoming handler** — queue + safe stub for inbound tasks (default deny execution)
- **8 tools** — `a2a_discover`, `a2a_send`, `a2a_status`, `a2a_inbox`, `a2a_start_node`, `a2a_stop_node`, `a2a_list_peers`, `a2a_info`

## Requirements

- Python 3.10+
- Hermes Agent (recent build with plugin support)
- `agentanycast` Python SDK (`pip install agentanycast` or editable install from this fork)

## Install

### Option A: Symlink (development)

```bash
# From this repo's hermes-plugin/ directory:
ln -s ~/src/hermes-agentanycast/hermes-plugin ~/.hermes/profiles/<profile>/plugins/agentanycast
```

### Option B: Copy (standalone)

```bash
cp -r hermes-plugin/ ~/.hermes/profiles/<profile>/plugins/agentanycast
```

### Option C: Bundled plugin (upstream PR)

For a PR to NousResearch/hermes-agent, the plugin would go into `plugins/agentanycast/` in the Hermes source tree.

## Configuration

Add to your profile's `config.yaml`:

```yaml
plugins:
  enabled:
    - agentanycast

agentanycast:
  enabled: true
  auto_start: false           # true = start node on session start
  relay: null                 # relay multiaddr for cross-network (e.g. "/ip4/...")
  skills_from_profile: true   # auto-generate skills from installed Hermes skills
  allow_remote_tasks: false   # true = allow remote agents to queue tasks (safe stub)
  trusted_peers: []           # peer_id allowlist (future)
  incoming_queue_limit: 100   # max incoming task records
```

## Tools

| Tool | Description |
|------|-------------|
| `a2a_info` | Show plugin status, generated AgentCard, node state |
| `a2a_start_node` | Start this profile's P2P node |
| `a2a_stop_node` | Stop the node cleanly |
| `a2a_list_peers` | List connected P2P peers |
| `a2a_discover` | Find agents by skill (requires relay for cross-network) |
| `a2a_send` | Send a task to a peer_id or skill |
| `a2a_status` | Check status/artifacts for a sent task |
| `a2a_inbox` | Inspect recent incoming tasks |

## Security Model

- **Default deny** — remote tasks are processed by a safe stub, not real Hermes execution
- `allow_remote_tasks: false` (default) — no terminal, file, or tool access for remote tasks
- `trusted_peers: []` — peer_id allowlist (future enforcement)
- Safe stub returns an acknowledgement with metadata, no side effects

## Architecture

```
Hermes Profile (e.g. "gpt")
├── config.yaml          → agentanycast.* settings
├── SOUL.md              → AgentCard description
├── skills/**/SKILL.md   → AgentCard skills
└── plugins/agentanycast/
    ├── plugin.yaml      → plugin metadata
    ├── __init__.py      → register() with tools + hooks
    ├── config.py        → reads agentanycast.* from config
    ├── card_builder.py  → builds AgentCard from profile
    ├── node_manager.py  → Node lifecycle + incoming queue
    └── tools.py         → 8 Hermes tool definitions

Each profile gets its own AgentAnycast node:
~/.hermes/profiles/<name>/.agentanycast/  → daemon home, Ed25519 key, state
```

## License

- Plugin code (hermes-plugin/): Apache 2.0 (matching the SDK)
- AgentAnycast SDK: Apache 2.0
- AgentAnycast daemon (agentanycastd): FSL-1.1-ALv2 — external binary dependency, not bundled
