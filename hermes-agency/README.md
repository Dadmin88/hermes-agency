# Hermes Agency Hermes Plugin

P2P agent communication for [Hermes Agent](https://github.com/NousResearch/hermes-agent) profiles via the AgentAnycast Python SDK/runtime.

AgentAnycast is the SDK/runtime; Hermes Agency is this optional Hermes Agent plugin built on top of it.

Each Hermes profile gets its own Hermes Agency node with a persistent identity, an auto-generated AgentCard from `SOUL.md` + installed skills, and encrypted P2P communication with other agents.

> Status: local testing / PR-prep. Do not open upstream PRs from this checkout without explicit maintainer approval.

## What It Does

- **Profile AgentCards** — generated from `SOUL.md`, installed skills, and a non-secret config allowlist.
- **Node lifecycle** — start/stop per-profile P2P nodes with persistent Ed25519 identity.
- **Peer discovery** — find agents by skill through LAN peer discovery plus relay-backed anycast registry.
- **Team context** — compact teammate summaries injected through plugin context, bounded by config budgets.
- **Task send/receive** — send tasks to peers, receive tasks from remote agents, return artifacts to the sender.
- **Safe incoming handler** — remote tasks default to safe/no-dangerous-tool behavior unless explicitly enabled.
- **Kanban tracking** — outbound and inbound Hermes Agency tasks reconcile with Hermes Kanban when available.
- **Autonomous collaboration helpers** — self-registration, bidding, workflows, proactive tasks, autonomy checks, and routing-correction logging.
- **CLI and slash command** — `hermes agency ...` and `/agency ...` for status/start/stop/discovery.
- **Model sets** — switch the whole agency between `balanced`, `economic`, `premium`, `go-plan`, or custom profile/model strategies without hand-editing every staff profile.

## Requirements

- Python 3.10+
- Hermes Agent with user-plugin support
- Optional: `agentanycast` Python SDK (`pip install agentanycast` or editable install from this fork)
- Optional for cross-network discovery: an Hermes Agency relay with registry service

The SDK is optional at plugin load time. If it is absent, the plugin must load cleanly and its tool check functions should gate Hermes Agency tools off.

## Install

### Option A: Symlink (development)

```bash
ln -s ~/src/hermes-agentanycast/hermes-agency ~/.hermes/profiles/<profile>/plugins/hermes-agency
```

### Option B: Copy (standalone testing)

```bash
mkdir -p ~/.hermes/profiles/<profile>/plugins
cp -r hermes-agency ~/.hermes/profiles/<profile>/plugins/hermes-agency
```

### Option C: Bundled plugin (future upstream shape)

If this is ever upstreamed to `NousResearch/hermes-agent`, the plugin should remain optional and live under a bundled plugin directory such as `plugins/hermes-agency/`. The daemon/relay binaries should **not** be vendored into Hermes.

## Model Sets

Model sets let you choose a provider/model strategy once and apply it across installed `agency-*` staff profiles safely.

```bash
hermes agency models list
hermes agency models show economic
hermes agency models validate economic --strict
hermes agency models resolve agency-backend-engineer --set economic
hermes agency models plan economic
hermes agency models apply economic --dry-run
hermes agency models apply economic --yes --backup
```

Packaged presets live in `hermes-agency/model_sets/`. User presets live in `~/.hermes/agency/model_sets/` and override packaged presets by name. Presets must never contain API keys, tokens, passwords, or provider credentials.

See `docs/agency-model-sets.md` for the implementation details and rollout procedure.

## GPT Bridge

The GPT Bridge is a pull-based escalation inbox for routing blocked or high-leverage agency work to a live ChatGPT session.

```bash
hermes agency gpt-bridge status
hermes agency gpt-bridge inbox
hermes agency gpt-bridge claim <task-id>
hermes agency gpt-bridge complete <task-id> "Result text"
```

Agents can queue work with `orch_escalate_to_gpt`. See `docs/gpt-bridge.md` for the full flow.

## Configuration

Add to the active profile's `config.yaml`:

```yaml
plugins:
  enabled:
    - agency

agency:
  enabled: true                 # runtime gate after the plugin itself is enabled
  auto_start: false             # true = start node on session/plugin load
  relay: null                   # libp2p relay multiaddr for cross-network transport
  skills_from_profile: true     # generate AgentCard skills from installed Hermes skills
  allow_remote_tasks: false     # false = safe stub / no real execution
  trusted_peers: []             # peer_id allowlist, reserved for stricter policies
  incoming_queue_limit: 100
  card_name: null               # optional public display name override
  daemon_bin: null              # optional explicit daemon path; prevents SDK auto-download/overwrite
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
```

For relay-backed skill discovery, set the daemon environment separately:

```bash
export AGENTANYCAST_REGISTRY_ADDRS=<registry-host>:50052
```

Relay/bootstrap and skill registry are separate: `agency.relay` connects libp2p; `AGENTANYCAST_REGISTRY_ADDRS` enables anycast skill discovery.

## Tools

| Tool | Description |
|------|-------------|
| `agency_info` | Show plugin/SDK/card/node status; use `compact: true` for health checks |
| `agency_start_node` | Start this profile's P2P node |
| `agency_stop_node` | Stop the node cleanly |
| `agency_list_peers` | List connected P2P peers |
| `agency_discover` | Find agents by skill through anycast routing |
| `agency_send` | Send a task to a `peer_id` or skill and optionally wait for completion |
| `agency_status` | Check latest tracked status/artifacts for a sent task |
| `agency_inbox` | Inspect recent incoming tasks |
| `agency_registry` | List live self-registration records |
| `agency_bid_task` | Record/simulate bids and optionally assign the best bidder |
| `agency_execute_workflow` | Create dependency-linked Kanban tasks from configured workflows |
| `agency_create_proactive_task` | Create proactive tasks when enabled |
| `agency_check_autonomy` | Check autonomy policy for a proposed action |
| `agency_log_routing_correction` | Record routing-correction feedback when learning is enabled |

The legacy `a2a_*` tool names are still registered as deprecated aliases for protocol/backward compatibility. New prompts and docs should use `agency_*` names.

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
hermes agency doctor
hermes agency doctor --json
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
/agency doctor
```

## Security Model

- Plugin loading is opt-in via `plugins.enabled`.
- Runtime operation is gated by `agency.enabled`.
- Remote task execution defaults to safe behavior; no terminal/file access is granted by default.
- The incoming processor can use delegation/subprocess modes only when explicitly configured.
- AgentCards expose only a non-secret metadata allowlist: provider/model names, configured booleans, and profile/toolset summaries. They must not expose API keys, raw env vars, Discord channel IDs, local daemon paths, or profile-private data.
- The daemon and relay are external Hermes Agency runtime components. Do not vendor daemon/relay binaries into an upstream Hermes PR.

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
    ├── tools.py         → agency_* model tools; a2a_* deprecated compatibility aliases
    ├── orchestrator.py  → orch_* model tools
    └── *_bridge.py      → Kanban/team/context helpers
```

Each profile gets its own daemon home:

```text
~/.hermes/profiles/<profile>/.agency/
```

## Validation

See [`docs/troubleshooting.md`](../docs/troubleshooting.md) for symptom → cause → fix guidance for daemon, discovery, relay, registry, trust, and auto-start issues.

From repo root, after installing dev dependencies with `python -m pip install -e ".[dev]"`:

```bash
make test-agency
make lint-agency
python -m pip check
```

Equivalent direct commands:

```bash
python -m pytest hermes-agency/tests/test_unit.py -q -m "not integration"
python -m ruff check hermes-agency/
python -m ruff format --check hermes-agency/
```

Manual/live P2P checks:

```bash
make integration-agency
make integration-agency-full
```

The lightweight `test_e2e.py` script starts real SDK nodes with isolated temporary daemon homes and does not use a registry/relay unless `AGENTANYCAST_E2E_REGISTRY` / `AGENTANYCAST_E2E_RELAY` are explicitly set. The full Phase 7 script still exercises live profile/Kanban/relay assumptions and should remain explicit manual validation until those assumptions are converted to fixtures or test skips.

## License Notes

- This repository and the Python SDK are Apache-2.0.
- The Hermes Agency daemon/relay are external runtime components with their own license terms and should not be bundled here.
- If the plugin is proposed for Hermes upstream, call out the license compatibility story explicitly and let maintainers decide whether a bundled plugin needs MIT relicensing or dual licensing.
