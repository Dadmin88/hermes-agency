# Hermes Agency — Agent Instructions

Hermes Agency is the primary product in this repository. It is a Hermes Agent plugin and local operations layer for running a managed multi-agent team: packaged specialist profiles, skill-based routing, Kanban-backed work tracking, model-set controls, orchestration helpers, and P2P delegation.

**Keryx is the primary transport.** AgentAnycast remains only as a legacy/fallback path under `src/agentanycast/`.

Do not present this repository as primarily an AgentAnycast SDK repo in public docs, issue summaries, PR summaries, or generated handoff notes.

## Repository map

- `hermes-agency/` — main product area: plugin registration, CLI/slash commands, model tools, config, staff install, node manager, orchestration, Kanban bridges, pool delegation, and plugin-specific tests.
- `hermes-agency/default_staff/` — packaged `agency-*` staff profiles and their role definitions.
- `hermes-agency/model_sets/` — packaged model-set strategies for installed staff profiles.
- `src/keryx/` — **vendored Keryx Python SDK** (import name `keryx`). Source of truth for the Rust runtime remains the separate `hermes-keryx` repo.
- `src/agentanycast/` — legacy AgentAnycast transport retained for fallback/compat. Touch only for security fixes or explicit fallback work.
- `docker/`, `Dockerfile`, `docker-compose.yml` — headless setup/node runtime. Current compose is not a dashboard service.
- `apps/fabric/` — Hermes Fabric frontend (separate Node/React product). Do not treat Fabric as part of the core Python plugin.
- `scripts/` — operational helpers such as batch agent wake scripts.
- `docs/` — focused design, operations, and integration notes.

## Transport model

| Backend | Path | Role |
|---------|------|------|
| `keryx` (default/primary) | `src/keryx/` + external `keryxd`/`keryx-relay` | Production transport |
| `agentanycast` (legacy) | `src/agentanycast/` | Fallback/compat only |

Config:

```yaml
agency:
  transport_backend: keryx
  keryx:
    daemon_endpoint: 127.0.0.1:50051
    registry_endpoint: 127.0.0.1:51053   # dual-run default
    relay_config: {}
```

Plugin imports should prefer:

```python
from keryx import KeryxNode, AgentCard, Skill, peer_id_to_did_key
```

Keep transport SDK imports lazy at plugin load time so Hermes can still start if optional runtime pieces are missing.

Related runtime repo: [DeployFaith/hermes-keryx](https://github.com/DeployFaith/hermes-keryx) (migration + dual-run scripts live there).

## Repository priorities

- Keep Hermes Agency product-first in public-facing documentation.
- Describe Keryx as primary transport; AgentAnycast as legacy/fallback only.
- Use generic placeholders: `<profile-name>`, `<relay-multiaddr>`, `<registry-address>`, `<workspace>`, `<peer-id>`.
- Never commit maintainer names, machine names, private hostnames, local absolute paths, private relay addresses, private peer IDs, tokens, keys, API keys, environment dumps, gateway logs, or Discord channel IDs.
- Do not document a dashboard command/container unless the branch actually contains dashboard server/routes and CLI entry points. Current compose runs setup/node only.

## Safety defaults

- Remote task execution must be conservative by default:
  - `allow_remote_tasks: false`
  - `incoming.tool_access: safe`
  - progress artifacts opt-in via `incoming.send_progress: true`
- Plugin discovery must not start daemon processes when transport SDK is absent or `agency.enabled: false`.
- Management endpoints, pool services, and local APIs should bind to loopback by default unless explicit LAN/remote mode is configured.
- State-changing HTTP endpoints must require authentication.
- Do not let remote discovery metadata, handshakes, or advertised names wake arbitrary local profiles.
- Always transition incoming tasks through `WORKING` before `COMPLETED`.
- Keep routine model-tool responses compact. Prefer `agency_info({"compact": true})` / `NodeManager.compact_info()` for health checks.

## Install for local development

From the repository root:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

This installs the vendored Keryx SDK from `src/keryx/`. External Keryx binaries (`keryxd`, `keryx-relay`) still come from the hermes-keryx repo.

## Docker workflow

```bash
docker compose up --build
```

Useful overrides:

```bash
HERMES_AGENCY_MODEL_SET=<model-set> docker compose up --build
HERMES_AGENCY_START_NODE=0 docker compose --profile tools run --rm setup
```

Legacy AgentAnycast compose vars may still exist for fallback runs; prefer Keryx endpoints for new deployments.

## Validation before commit

```bash
ruff check .
ruff format --check .
make test-agency
python -m pytest hermes-agency/tests/test_unit.py -q -m "not integration"
python -m pytest hermes-agency/tests/test_keryx_transport.py -q
python -m pip check
```

For model-set changes also run:

```bash
python -m pytest -q hermes-agency/tests/test_model_sets.py
```

## Dispatch and Kanban expectations

- Target-agent dispatch routes through the pool sender so offline agents can wake/queue safely.
- Kanban tasks must include board, assignee, target, status, and correlation metadata where available.
- Agency task views aggregate agency boards, not only a default board.
- Do not hide Kanban failures silently during debugging.

## Documentation expectations

- `README.md` — public product overview
- `hermes-agency/README.md` — plugin/operator docs
- `hermes-agency/AGENTS.md` — plugin contributor notes
- `llms.txt` — compact LLM-oriented summary (Agency first, Keryx primary)
- `CONTRIBUTING.md` — contribution workflow for this product repo
- Keep examples copy-pasteable but generic
- Never include real peer IDs, private relays, private hostnames, or maintainer-local paths
