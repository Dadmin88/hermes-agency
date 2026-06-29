# Hermes Agency Plugin

This directory contains the Hermes Agency Hermes Agent plugin. The plugin turns a Hermes profile into a participant in a managed multi-agent agency: it builds a public AgentCard, starts a per-profile P2P node, exposes `agency_*` model tools, registers `hermes agency ...` and `/agency ...` commands, injects bounded team context, routes work through Kanban-aware delegation, and uses the bundled AgentAnycast transport layer for peer discovery and encrypted task exchange.

Hermes Agency is the product layer. AgentAnycast is the transport layer beneath it.

## What this plugin does

- **Profile AgentCards** — builds profile-safe AgentCards from `SOUL.md`, installed skills, and a strict non-secret config allowlist.
- **Node lifecycle** — starts/stops per-profile P2P nodes with persistent Ed25519 identity and daemon state under the profile’s `.agency/` directory.
- **Peer discovery** — discovers agents by skill through LAN discovery plus relay/registry-backed anycast routing when configured.
- **Task send/receive** — sends tasks to peers by `peer_id` or skill, receives incoming tasks, and returns artifacts/status to the sender.
- **Safe incoming handler** — remote task execution is disabled/safe by default and requires explicit configuration before dangerous tool access is available.
- **Kanban tracking** — outbound/inbound work can reconcile with Hermes Kanban when the bridge is available.
- **Team context** — compact teammate/orchestrator context can be injected through Hermes plugin hooks within configured budgets.
- **Autonomous helpers** — registry, bidding, workflow, proactive task, autonomy, and routing-correction helpers live behind Agency tools.
- **Model sets** — applies provider/model strategies across installed `agency-*` staff profiles without hand-editing each profile.
- **GPT bridge** — queues blocked or high-leverage work for a live ChatGPT session to claim and complete.
- **Discord intake** — polls configured Discord channels for `!agency` tasks when enabled.
- **CLI and slash command** — registers `hermes agency ...` and `/agency ...` for status, start/stop, discovery, staff, model sets, doctor, bridge, and intake operations.

## Requirements

- Python 3.11+
- Hermes Agent with user-plugin support
- `hermes-agent>=0.17.0` through the package dependency
- AgentAnycast transport package/bundle available when actually starting nodes or sending tasks
- Optional relay and registry services for cross-network discovery

The transport SDK is optional at plugin load time. If it is absent, plugin discovery must still succeed and Agency tools should report unavailable rather than crashing Hermes.

## Install into a Hermes profile

Development symlink:

```bash
mkdir -p ~/.hermes/profiles/<profile-name>/plugins
ln -s <workspace>/hermes-agency ~/.hermes/profiles/<profile-name>/plugins/hermes-agency
```

Copy-based install:

```bash
mkdir -p ~/.hermes/profiles/<profile-name>/plugins
cp -r hermes-agency ~/.hermes/profiles/<profile-name>/plugins/hermes-agency
```

Bulk profile setup from this repository/package:

```bash
hermes-agency setup-plugins
# or, from a Hermes plugin CLI context:
hermes agency setup-plugins
```

## Configuration

Add Agency configuration to the active Hermes profile’s `config.yaml`:

```yaml
plugins:
  enabled:
    - agency

agency:
  enabled: true                 # runtime gate after the plugin itself is loaded
  auto_start: false             # true = start node on session/plugin load
  relay: null                   # libp2p relay multiaddr for cross-network transport
  skills_from_profile: true     # generate AgentCard skills from installed Hermes skills
  allow_remote_tasks: false     # false = safe stub / no real execution
  trusted_peers: []             # peer_id allowlist, reserved for stricter policies
  incoming_queue_limit: 100
  card_name: null               # optional public display name override
  daemon_bin: null              # optional explicit daemon path
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
  models:
    active_set: openai-codex-only
  orchestrator:
    enabled: false
    agent: null
    auto_decompose: true
  routing: {}
```

For relay-backed skill discovery, configure the registry separately:

```bash
export AGENTANYCAST_REGISTRY_ADDRS=<registry-address>
```

Relay/bootstrap and skill registry are separate: `agency.relay` connects libp2p peers; `AGENTANYCAST_REGISTRY_ADDRS` enables anycast skill discovery.

## Staff profiles

Hermes Agency ships packaged `agency-*` staff profiles. Install them into the local Hermes profiles directory with:

```bash
hermes-agency staff list
hermes-agency staff install --dry-run
hermes-agency staff install --force
```

In a Hermes plugin CLI context, use the same verbs through `hermes agency staff ...`.

## Model sets

Model sets let you choose a provider/model strategy once and apply it across installed staff profiles.

```bash
hermes-agency models list
hermes-agency models show openai-codex-only
hermes-agency models validate openai-codex-only --strict
hermes-agency models resolve agency-backend-engineer --set openai-codex-only
hermes-agency models plan openai-codex-only
hermes-agency models apply openai-codex-only --dry-run
hermes-agency models apply openai-codex-only --yes --backup
```

Packaged presets live in `hermes-agency/model_sets/`. User presets live in `~/.hermes/agency/model_sets/` and override packaged presets by name. Presets must never contain API keys, tokens, passwords, or provider credentials.

See `docs/agency-model-sets.md` for implementation details and rollout procedure.

## GPT bridge

The GPT bridge is a pull-based escalation inbox for routing blocked or high-leverage agency work to a live ChatGPT session.

```bash
hermes-agency gpt-bridge status
hermes-agency gpt-bridge inbox
hermes-agency gpt-bridge claim <task-id>
hermes-agency gpt-bridge complete <task-id> "Result text"
```

Agents can queue work with `orch_escalate_to_gpt`. See `docs/gpt-bridge.md` for the full flow.

## Monitoring and Discord intake

Extended status:

```bash
hermes-agency status --extended
```

Discord channel intake:

```bash
hermes-agency discord poll
```

Discord messages beginning with `!agency` are queued for `agency-orchestrator` when intake is configured. See `docs/agency-discord-intake.md` for setup and operations.

## Model tools

| Tool | Description |
|------|-------------|
| `agency_info` | Show plugin/SDK/card/node status; use `compact: true` for health checks. |
| `agency_start_node` | Start this profile’s P2P node. |
| `agency_stop_node` | Stop the node cleanly. |
| `agency_list_peers` | List connected P2P peers. |
| `agency_discover` | Find agents by skill through anycast routing. |
| `agency_send` | Send a task to a `peer_id` or skill and optionally wait for completion. |
| `agency_status` | Check latest tracked status/artifacts for a sent task. |
| `agency_inbox` | Inspect recent incoming tasks. |
| `agency_moa_status` | Show Agency MoA policy and native Hermes Agent MoA availability. |
| `agency_moa_presets` | List native Hermes Agent MoA presets through the Agency adapter. |
| `agency_moa_show` | Show one native MoA preset through the Agency adapter. |
| `agency_moa_recommend` | Recommend native MoA for high-leverage Agency tasks without running model calls. |
| `agency_registry` | List live self-registration records. |
| `agency_bid_task` | Record/simulate bids and optionally assign the best bidder. |
| `agency_execute_workflow` | Create dependency-linked Kanban tasks from configured workflows. |
| `agency_create_proactive_task` | Create proactive tasks when enabled. |
| `agency_check_autonomy` | Check autonomy policy for a proposed action. |
| `agency_log_routing_correction` | Record routing-correction feedback when learning is enabled. |

Legacy `a2a_*` tool names are still registered as deprecated aliases for protocol/backward compatibility. New prompts and docs should use `agency_*` names.

Orchestrator-only tools are exposed only for the promoted/configured orchestrator profile:

- `orch_route`
- `orch_decompose`
- `orch_status`
- `orch_list_tasks`
- `orch_escalate`

## CLI and slash commands

Standalone package command:

```bash
hermes-agency status
hermes-agency start
hermes-agency stop
hermes-agency discover <skill>
hermes-agency registry
hermes-agency doctor
hermes-agency doctor --json
hermes-agency promote <profile-name>
hermes-agency demote <profile-name>
```

Hermes plugin CLI command:

```bash
hermes agency status
hermes agency start
hermes agency stop
hermes agency discover <skill>
hermes agency registry
hermes agency doctor
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

## Security model

- Plugin loading is opt-in via `plugins.enabled`.
- Runtime operation is gated by `agency.enabled`.
- Remote task execution defaults to safe behavior; no terminal/file access is granted by default.
- The incoming processor can use delegation/subprocess modes only when explicitly configured.
- AgentCards expose only a non-secret metadata allowlist: provider/model names, configured booleans, and profile/toolset summaries.
- AgentCards, logs, docs, and tests must not expose API keys, raw environment variables, Discord channel IDs, local daemon paths, local profile paths, private hostnames, or profile-private data.
- Daemon and relay components are runtime dependencies/foundations. Do not vendor daemon or relay binaries into a Hermes upstream plugin proposal.

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

Each profile gets its own daemon/runtime home:

```text
~/.hermes/profiles/<profile-name>/.agency/
```

## Validation

See `docs/troubleshooting.md` for symptom → cause → fix guidance for daemon, discovery, relay, registry, trust, and auto-start issues.

From the repo root, after installing dev dependencies:

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

`test_e2e.py` starts real SDK nodes with isolated temporary daemon homes and does not use a registry/relay unless `AGENTANYCAST_E2E_REGISTRY` or `AGENTANYCAST_E2E_RELAY` are explicitly set. Full live profile/Kanban/relay validation should remain explicit/manual until those assumptions are converted into fixtures or skips.
