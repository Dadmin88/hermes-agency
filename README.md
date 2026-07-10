# Hermes Agency

**A Hermes Agent plugin and local operations layer for running a managed multi-agent team.**

Hermes Agency turns a Hermes installation into an agency-style operating system: packaged specialist profiles, skill-based task routing, team context injection, Kanban-backed task tracking, model-set controls, orchestration helpers, and safe P2P delegation. Keryx is the primary transport for AgentCards, skill discovery, task messages, and encrypted P2P networking; AgentAnycast remains available for legacy/fallback deployments.

Hermes Agency is the product in this repository. Keryx is the primary transport; AgentAnycast is the legacy compatibility path.

[![CI](https://github.com/DeployFaith/Hermes_Agency/actions/workflows/ci.yml/badge.svg)](https://github.com/DeployFaith/Hermes_Agency/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/hermes-agency?color=3776AB)](https://pypi.org/project/hermes-agency/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](LICENSE)

## What this repository contains

| Area | Purpose |
|---|---|
| `hermes-agency/` | The Hermes Agency plugin: CLI/slash commands, model tools, config, staff installation, node management, orchestration, Kanban bridges, and pool delegation. |
| `hermes-agency/default_staff/` | Packaged `agency-*` Hermes profiles that form the default specialist roster. |
| `hermes-agency/model_sets/` | Packaged provider/model strategies such as balanced/economic/premium-style profile mappings. |
| `src/keryx/` | Vendored Keryx Python SDK (`import keryx`) used by the primary transport path. Runtime daemons/relays still come from the separate Keryx runtime deployment. |
| `src/agentanycast/` | Legacy AgentAnycast compatibility transport retained for rollback/fallback only. |
| `docker/`, `Dockerfile`, `docker-compose.yml` | Headless setup/node runtime for local or server deployment. |
| `scripts/` | Operational helpers such as batch agent wake scripts. |
| `docs/` | Focused implementation and operations notes. |

## Install

Hermes Agency is packaged as `hermes-agency` and requires Python 3.11+.

```bash
python -m pip install hermes-agency
```

For development from this repository:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

This installs the plugin and the vendored Keryx Python SDK from `src/keryx/`.
Do **not** install a sibling `Hermes_Keryx/sdk/python` checkout for normal Agency
development. External Keryx binaries (`keryxd`, `keryx-relay`) still come from
the separate [`hermes-keryx`](https://github.com/DeployFaith/hermes-keryx)
repository or your runtime deployment.

## Command surfaces

Hermes Agency has three related command surfaces. Keep them distinct:

| Surface | Where it runs | Example |
|---|---|---|
| `hermes-agency ...` | Standalone package console script from `pyproject.toml`. | `hermes-agency status` |
| `hermes agency ...` | Hermes Agent plugin CLI after the plugin is loaded. | `hermes agency status` |
| `/agency ...` | Slash command inside a Hermes session. | `/agency status` |

Useful standalone/plugin CLI commands:

```bash
hermes-agency doctor
hermes-agency status --extended
hermes-agency staff list
hermes-agency staff install --dry-run
hermes-agency models list
hermes-agency models plan openai-codex-only
hermes-agency setup-plugins
hermes-agency start
hermes-agency registry
hermes-agency discover <skill>
```

The same verbs are available through `hermes agency ...` when Hermes Agent has loaded the plugin. In-session slash commands use `/agency ...`.

## Quick start with Docker

The current Docker setup is a headless agency runtime. It prepares a Hermes home, installs packaged staff profiles, configures the active model set, initializes agency Kanban boards when the bridge is available, and starts the local Hermes Agency node manager.

```bash
docker compose up --build
```

Common overrides:

```bash
HERMES_AGENCY_MODEL_SET=<model-set> docker compose up --build
HERMES_AGENCY_START_NODE=0 docker compose --profile tools run --rm setup
```

Keryx endpoints live under `agency.keryx.*` in Hermes config and are also read by
the vendored SDK from `HERMES_KERYX_*` / `KERYX_*` environment variables when
those variables are present in the runtime environment. `AGENTANYCAST_*` relay
and registry variables are legacy fallback settings, not the primary Keryx path.

Advanced modes use the same image:

```bash
docker compose --profile tools run --rm setup      # setup only
docker compose --profile split up node              # node service only
```

The compose file uses a named volume for runtime data so examples do not rely on maintainer-local paths.

## Server deployment (systemd)

For headless VPS or server deployments, use the bundled systemd service template:

```bash
# Copy and customize for your user/paths
cp deploy/systemd/hermes-gateway.service.example ~/.config/systemd/user/hermes-gateway.service
${EDITOR:-vi} ~/.config/systemd/user/hermes-gateway.service

# Enable and start
systemctl --user daemon-reload
systemctl --user enable --now hermes-gateway

# Check status and logs
systemctl --user status hermes-gateway
journalctl --user -u hermes-gateway -f
```

Key settings to review in the service file:

| Setting | Default | Purpose |
|---|---|---|
| `ExecStart` | `<user>/.hermes/...` | Path to your Hermes venv |
| `MemoryMax` | `5G` | Hard kill limit (gateway + node runners can spike during multi-agent dispatch) |
| `MemoryHigh` | `4G` | Soft reclaim limit — triggers GC before hitting MemoryMax |
| `Restart` | `on-failure` | Auto-restart after crashes, OOM kills, or signal exits |
| `TimeoutStopSec` | `210` | Drain timeout — active sessions can take ~50s to flush |

To adjust limits at runtime without editing the unit file:

```bash
systemctl --user edit hermes-gateway
# Add overrides, e.g.:
#   [Service]
#   MemoryMax=8G
#   MemoryHigh=6G
systemctl --user daemon-reload
systemctl --user restart hermes-gateway
```

## How Hermes Agency works

```text
Hermes Agent profile
├── SOUL.md + skills/              → public AgentCard source
├── config.yaml                    → agency.* policy and model-set choice
├── plugins/hermes-agency/         → plugin entry point, CLI, model tools, hooks
└── .agency/                       → per-profile node identity, queue, runtime state

Hermes Agency
├── installs specialist agency-* profiles
├── builds profile-safe AgentCards
├── starts/stops per-profile P2P nodes
├── discovers peers by skill through Keryx transport
├── sends, receives, queues, and tracks tasks
├── reconciles work with Hermes Kanban when available
├── injects compact team/orchestrator context into Hermes calls
├── applies model-set strategies across installed staff profiles
└── coordinates optional private escalation paths when configured
```

Keryx supplies the primary lower-level P2P machinery: daemon/relay connectivity, AgentCards, skills, identity, A2A-style task messages, and encrypted peer transport. The Python SDK surface is vendored in this repository under `src/keryx/`; runtime daemons/relays are external services. Operators should usually interact with Hermes Agency commands and tools, not the transport API directly. Set `agency.transport_backend: agentanycast` only for legacy rollback.

## Core capabilities

- **Specialist staff roster** — packaged `agency-*` profiles for engineering, design, content, marketing, operations, QA, product, research, management, and business workflows.
- **Skill-based delegation** — send work directly to a peer or by requested skill, with compact status/artifact tracking.
- **Kanban integration** — create and reconcile agency task boards when Hermes Kanban is available.
- **Team context injection** — bounded summaries of known teammates and orchestrator state can be injected into Hermes calls.
- **Model sets** — choose a provider/model strategy once and apply it across installed staff profiles.
- **Orchestrator promotion** — expose `orch_*` tools only for the configured orchestrator profile.
- **P2P transport** — encrypted local/WAN agent communication through Keryx, with AgentAnycast retained as a legacy fallback.

## Model sets

Model sets let you choose a provider/model strategy once and apply it across installed agency staff profiles.

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

See `docs/agency-model-sets.md` for implementation details and rollout rules.

## Hermes Agent MoA integration

Hermes Agency can inspect native Hermes Agent Mixture-of-Agents availability and recommend MoA presets for high-leverage agency work. Native presets remain under top-level `moa:` in the active Hermes `config.yaml`; Agency policy lives under `agency.moa:`.

The MoA integration is exposed through model tools such as `agency_moa_status`, `agency_moa_presets`, `agency_moa_show`, and `agency_moa_recommend`. See `docs/agency-moa.md` for the integration contract and policy semantics.

## Security model

Hermes Agency should be safe by default:

- Plugin loading is opt-in through Hermes plugin configuration.
- Runtime operation is gated by `agency.enabled`.
- Remote task execution defaults to disabled: `allow_remote_tasks: false`.
- Tool access for incoming remote tasks should default to `safe`, not `full`.
- AgentCards must expose only non-secret metadata: no API keys, raw environment variables, private relay addresses, local paths, peer IDs that should remain private, Discord channel IDs, or maintainer-local details.
- Keryx relay/registry endpoints live under `agency.keryx.*`; legacy AgentAnycast relay/bootstrap and `AGENTANYCAST_REGISTRY_ADDRS` remain separate fallback settings.

## Development checks

Run the fastest relevant checks for your change, then the broader checks before pushing:

```bash
ruff check .
ruff format --check .
make test-agency
make test-sdk
python -m pytest
python -m pip check
```

Manual/live checks:

```bash
make integration-agency
make integration-agency-full
```

The default pytest configuration skips tests marked `integration`.

## Requirements

- Python 3.11+
- Hermes Agent 0.17.0+
- Vendored Keryx Python SDK at `src/keryx/` (package/import name `keryx`) for node startup and task transport
- Optional Keryx daemon/relay/registry services for cross-network discovery
- AgentAnycast package/daemon only for `agency.transport_backend: agentanycast` legacy fallback

## License

[Apache License, Version 2.0](LICENSE)
