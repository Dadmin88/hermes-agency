# Hermes Agency Hermes Plugin — Contributor Notes

This directory contains the Hermes user-plugin scaffold for Hermes Agency P2P agent communication.

## Current status

- This plugin is still in local testing / PR-prep mode.
- Do **not** open pull requests from this checkout unless Kyle explicitly asks.
- Keep changes profile-safe: do not depend on Kyle's real `~/.hermes` homes, real peer IDs, the VPS relay, Discord channels, or local daemon sockets in tests that should run in CI.

## Plugin shape

- `plugin.yaml` declares the standalone plugin.
- `__init__.py` registers the `/agency` slash command, `hermes agency` CLI command, model tools, and lifecycle hooks.
- `card_builder.py` builds an AgentCard from profile `SOUL.md`, installed `skills/**/SKILL.md`, and a strict non-secret config allowlist.
- `node_manager.py` owns the async Hermes Agency SDK node, daemon lifecycle, incoming task queue, compact health, registry refresh, and Kanban reconciliation.
- `tools.py` exposes the core `a2a_*` tools.
- `orchestrator.py` exposes `orch_*` tools only for the promoted/configured orchestrator profile.
- `autonomous_tools.py` exposes registry, bidding, workflow, proactive, autonomy, and learning helpers.

## Safety rules

- The Hermes Agency SDK is optional. All SDK imports must stay lazy so Hermes can load the plugin when `agentanycast` is not installed.
- Plugin discovery must not start daemon processes when the SDK is absent or `agency.enabled: false`.
- Remote task execution is conservative by default:
  - `allow_remote_tasks: false`
  - `incoming.tool_access: safe`
  - progress artifacts are opt-in via `incoming.send_progress: true`
- Never expose API keys, tokens, Discord channel IDs, raw env vars, daemon paths, or local profile paths in AgentCards.
- Treat relay configuration and anycast registry configuration as separate concerns: relay/bootstrap connects libp2p; `AGENTANYCAST_REGISTRY_ADDRS=<host>:50052` enables skill discovery.
- Always transition incoming tasks through `WORKING` before `COMPLETED`; daemon builds reject direct `SUBMITTED -> COMPLETED`.
- Keep routine model-tool responses compact. Use full `a2a_info` only for troubleshooting; health checks should call `a2a_info({"compact": true})` or `NodeManager.compact_info()`.

## Test expectations

Run from the repo root:

```bash
# Unit / PR-prep checks
/home/kyle/.hermes/hermes-agent/venv/bin/python -m pytest hermes-agency/tests/test_unit.py -q
/home/kyle/.hermes/hermes-agent/venv/bin/python -m py_compile hermes-agency/*.py
/home/kyle/.hermes/hermes-agent/venv/bin/python -m pip check

# Standalone local P2P checks; require SDK + daemon and may use live relay env vars
/home/kyle/.hermes/hermes-agent/venv/bin/python hermes-agency/tests/test_e2e.py
/home/kyle/.hermes/hermes-agent/venv/bin/python hermes-agency/tests/test_e2e_full.py
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
