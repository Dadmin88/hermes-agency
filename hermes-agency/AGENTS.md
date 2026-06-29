# Hermes Agency Hermes Plugin — Contributor Notes

This directory contains the Hermes user-plugin scaffold for Hermes Agency P2P agent communication.

## Current status

- This plugin is still in local testing / PR-prep mode.
- Do **not** open pull requests from this checkout without explicit maintainer approval.
- Keep changes profile-safe: do not depend on real Hermes homes, real peer IDs, private relays, messaging channels, local daemon sockets, or machine-specific paths in tests that should run in CI.

## Plugin shape

- `plugin.yaml` declares the standalone plugin.
- `__init__.py` registers the `/agency` slash command, `hermes agency` CLI command, model tools, and lifecycle hooks.
- `card_builder.py` builds an AgentCard from profile `SOUL.md`, installed `skills/**/SKILL.md`, and a strict non-secret config allowlist.
- `node_manager.py` owns the async Hermes Agency SDK node, daemon lifecycle, incoming task queue, compact health, registry refresh, and Kanban reconciliation.
- `tools.py` exposes primary `agency_*` tools and deprecated `a2a_*` compatibility aliases.
- `orchestrator.py` exposes `orch_*` tools only for the promoted/configured orchestrator profile.
- `autonomous_tools.py` exposes registry, bidding, workflow, proactive, autonomy, and learning helpers.

## Safety rules

- The Hermes Agency SDK is optional. All SDK imports must stay lazy so Hermes can load the plugin when `agentanycast` is not installed.
- Plugin discovery must not start daemon processes when the SDK is absent or `agency.enabled: false`.
- Remote task execution is conservative by default:
  - `allow_remote_tasks: false`
  - `incoming.tool_access: safe`
  - progress artifacts are opt-in via `incoming.send_progress: true`
- Never expose API keys, tokens, private channel IDs, raw env vars, daemon paths, local profile paths, private hostnames, machine names, or maintainer identity details in AgentCards, docs, logs committed to the repo, or tests.
- Treat relay configuration and anycast registry configuration as separate concerns: relay/bootstrap connects libp2p; `AGENTANYCAST_REGISTRY_ADDRS=<host>:50052` enables skill discovery.
- Always transition incoming tasks through `WORKING` before `COMPLETED`; daemon builds reject direct `SUBMITTED -> COMPLETED`.
- Keep routine model-tool responses compact. Use full `agency_info` only for troubleshooting; health checks should call `agency_info({"compact": true})` or `NodeManager.compact_info()`.

## Install and use expectations

From the repository root, install development dependencies with:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Build the dashboard frontend after changes under `web/agency-dashboard/`:

```bash
cd web/agency-dashboard
npm ci
npm run build
```

Run the dashboard through a configured Hermes runtime:

```bash
hermes agency dashboard --host 127.0.0.1 --no-open
```

For containerized work, prefer the repository Docker Compose setup:

```bash
docker compose up --build
```

The default service is the full agency stack: config bootstrap, packaged staff install, model-set config, Kanban board initialization, local agency node manager, and dashboard. Use `docker compose --profile tools run --rm setup` for setup-only and `docker compose --profile split up node dashboard` for split services.

Keep all examples generic. Use placeholders for relay, registry, profile, and workspace values.

## Test expectations

Run from the repo root after `python -m pip install -e ".[dev]"`:

```bash
# Unit / PR-prep checks
make test-agency
make lint-agency
python -m pip check

# Standalone local P2P checks; require SDK + daemon and may use live relay env vars
make integration-agency
make integration-agency-full
```

Before upstreaming, convert live-environment assumptions in standalone e2e scripts into temp-home fixtures or mark them explicit integration/manual tests.

## Local artifact hygiene

Do not commit:

- `__pycache__/`
- `.pytest_cache/`
- `.agency/`
- daemon logs/sockets
- `bin/agentanycastd`
- symlinks such as `agency_plugin`
- real `~/.hermes` config, peer IDs, gateway logs, or Discord channel IDs
