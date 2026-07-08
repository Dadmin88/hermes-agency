# Hermes Agency Plugin — Contributor Notes

This directory contains the Hermes Agency Hermes Agent plugin. It is the main product area of the repository and should be treated as the operator-facing layer for specialist staff profiles, skill routing, Kanban-backed delegation, model sets, orchestration helpers, and P2P task exchange.

**Keryx is the primary transport foundation.** The vendored Python SDK lives at repo-root `src/keryx/`. Legacy AgentAnycast code remains under `src/agentanycast/` for fallback only.

## Current status

- Usable as a local Hermes Agent plugin and as the `hermes-agency` package command surface.
- Primary transport: `agency.transport_backend: keryx` with `from keryx import ...`.
- Some integrations remain environment-dependent (live relay/registry discovery, full Kanban profile workflows).
- Keep changes profile-safe: CI tests must not depend on real Hermes homes, real peer IDs, private relays, messaging channels, local daemon sockets, private hostnames, or machine-specific paths.

## Plugin shape

- `plugin.yaml` — standalone Hermes plugin declaration
- `__init__.py` — registers `/agency`, `hermes agency ...`, model tools, lifecycle hooks
- `cli.py` — standalone `hermes-agency` + Hermes plugin CLI/slash verbs
- `card_builder.py` — AgentCard from `SOUL.md`, skills, non-secret config allowlist
- `node_manager.py` — node lifecycle, incoming queue, compact health, registry refresh, Kanban reconciliation; transport-aware (`KeryxNode` / legacy Node)
- `tools.py` — `agency_*` tools (+ deprecated `a2a_*` aliases); transport selection helpers
- `config.py` — Agency config including `transport_backend` and `agency.keryx.*`
- `orchestrator.py` — `orch_*` tools for the configured orchestrator profile
- `autonomous_tools.py` — registry/bidding/workflow/proactive/autonomy helpers
- `default_staff/` — packaged `agency-*` profiles
- `model_sets/` — packaged model-routing presets
- `pool/` — roster, wake/sleep, pool_send, node runner
- `tests/test_keryx_transport.py` — transport selection + SDK smoke tests

## Transport rules

- Prefer direct Keryx imports: `from keryx import KeryxNode, AgentCard, Skill, peer_id_to_did_key`
- Keep transport SDK imports lazy at plugin load boundaries
- If `transport_backend: keryx` but Keryx is unavailable, fall back carefully to AgentAnycast when present and report effective backend
- External Keryx binaries (`keryxd`, `keryx-relay`) are **not** built in this repo; use the hermes-keryx repo + its dual-run/migration scripts
- Typical local endpoints:
  - daemon: `127.0.0.1:50051`
  - dual-run registry: `127.0.0.1:51053`
  - dual-run relay health: `127.0.0.1:51052`

## Safety rules

- Plugin discovery must not start daemons when SDK is absent or `agency.enabled: false`
- Remote task execution defaults:
  - `allow_remote_tasks: false`
  - `incoming.tool_access: safe`
  - `incoming.send_progress: false` (opt-in)
- Never expose API keys, tokens, private channel IDs, env dumps, daemon paths, local profile paths, private hostnames, machine names, maintainer identity, real peer IDs, or gateway logs in cards/docs/tests/fixtures
- Always transition incoming tasks through `WORKING` before `COMPLETED`
- Keep routine tool responses compact; use compact health payloads for high-traffic checks
- Do not document or expose a dashboard command unless the branch actually includes dashboard server/routes and CLI

## Install and use expectations

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Docker:

```bash
docker compose up --build
docker compose --profile tools run --rm setup
docker compose --profile split up node
```

Keep examples generic (placeholders for relay, registry, profile, peer, workspace).

## Test expectations

```bash
make test-agency
make lint-agency
python -m pytest hermes-agency/tests/test_unit.py -q -m "not integration"
python -m pytest hermes-agency/tests/test_keryx_transport.py -q
python -m pip check
```

Live integration checks require local Keryx (or legacy AgentAnycast) binaries/relay and must be opt-in.

## Local artifact hygiene

Do not commit:

- `__pycache__/`, `.pytest_cache/`
- `.agency/` runtime state
- daemon logs/sockets
- downloaded daemon binaries
- real `~/.hermes` config
- real peer IDs / gateway logs / private hostnames

## Documentation

When changing transport behavior, update in the same PR:

- `../README.md`
- `README.md` (this directory)
- `AGENTS.md` (this file)
- `../llms.txt`
- `../CONTRIBUTING.md` when contributor workflow changes
