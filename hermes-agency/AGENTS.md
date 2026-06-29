# Hermes Agency Plugin — Contributor Notes

This directory contains the Hermes Agency Hermes Agent plugin. It is the main product area of the repository and should be treated as the operator-facing layer for specialist staff profiles, skill routing, Kanban-backed delegation, model sets, orchestration helpers, GPT bridge, Discord intake, and P2P task exchange.

AgentAnycast is the transport foundation used by this plugin. Keep transport-specific work in `src/agentanycast/` unless a plugin change explicitly requires a transport change.

## Current status

- This plugin is usable as a local Hermes Agent plugin and as the `hermes-agency` package command surface.
- Some integrations remain environment-dependent, especially live relay/registry discovery, full Kanban profile workflows, and Discord intake.
- Keep changes profile-safe: CI tests must not depend on real Hermes homes, real peer IDs, private relays, messaging channels, local daemon sockets, private hostnames, or machine-specific paths.

## Plugin shape

- `plugin.yaml` declares the standalone Hermes plugin.
- `__init__.py` registers the `/agency` slash command, `hermes agency` CLI command, model tools, and lifecycle hooks.
- `cli.py` implements the standalone `hermes-agency` command and the Hermes plugin CLI/slash verbs.
- `card_builder.py` builds an AgentCard from profile `SOUL.md`, installed `skills/**/SKILL.md`, and a strict non-secret config allowlist.
- `node_manager.py` owns the async Hermes Agency SDK node, daemon lifecycle, incoming task queue, compact health, registry refresh, and Kanban reconciliation.
- `tools.py` exposes primary `agency_*` tools and deprecated `a2a_*` compatibility aliases.
- `orchestrator.py` exposes `orch_*` tools only for the promoted/configured orchestrator profile.
- `autonomous_tools.py` exposes registry, bidding, workflow, proactive, autonomy, and learning helpers.
- `default_staff/` contains packaged `agency-*` staff profiles.
- `model_sets/` contains packaged model-routing presets.
- `pool/` contains pool-based staff setup, roster, wake/sleep, and delegation helpers.

## Safety rules

- All SDK/transport imports must stay lazy so Hermes can load the plugin when `agentanycast` is not installed.
- Plugin discovery must not start daemon processes when the SDK is absent or `agency.enabled: false`.
- Remote task execution is conservative by default:
  - `allow_remote_tasks: false`
  - `incoming.tool_access: safe`
  - progress artifacts are opt-in via `incoming.send_progress: true`
- Never expose API keys, tokens, private channel IDs, raw environment variables, daemon paths, local profile paths, private hostnames, machine names, maintainer identity details, real peer IDs, or gateway logs in AgentCards, docs, committed logs, tests, or fixtures.
- Treat relay configuration and anycast registry configuration as separate concerns: relay/bootstrap connects libp2p; `AGENTANYCAST_REGISTRY_ADDRS=<host>:50052` enables skill discovery.
- Always transition incoming tasks through `WORKING` before `COMPLETED`; daemon builds reject direct `SUBMITTED -> COMPLETED`.
- Keep routine model-tool responses compact. Use full `agency_info` only for troubleshooting; health checks should call `agency_info({"compact": true})` or `NodeManager.compact_info()`.
- Do not document or expose a dashboard command unless the branch actually includes the dashboard server/routes and CLI command. Current Docker compose runs setup/node, not a web dashboard.

## Install and use expectations

From the repository root, install development dependencies with:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

For containerized work, prefer the repository Docker Compose setup:

```bash
docker compose up --build
```

The default service is the headless agency stack: config bootstrap, packaged staff install, model-set config, Kanban board initialization when available, and local agency node manager. Use `docker compose --profile tools run --rm setup` for setup-only and `docker compose --profile split up node` for the node service.

Keep all examples generic. Use placeholders for relay, registry, profile, peer, and workspace values.

## Test expectations

Run from the repo root after `python -m pip install -e ".[dev]"`:

```bash
# Unit / PR-prep checks
make test-agency
make lint-agency
python -m pip check

# Broader checks when touching shared transport or packaging
make test-sdk
python -m pytest

# Standalone local P2P checks; require SDK + daemon and may use live relay env vars
make integration-agency
make integration-agency-full
```

Before upstreaming or generalizing environment-dependent integrations, convert live-environment assumptions into temp-home fixtures, mocks, or explicit integration/manual tests.

## Local artifact hygiene

Do not commit:

- `__pycache__/`
- `.pytest_cache/`
- `.agency/`
- daemon logs/sockets
- downloaded daemon binaries such as `bin/agentanycastd`
- symlinks such as `agency_plugin`
- real `~/.hermes` config
- real peer IDs
- gateway logs
- Discord channel IDs
- local machine/service names
