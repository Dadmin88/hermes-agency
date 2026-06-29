# Hermes Agency — Agent Instructions

Hermes Agency is the primary product in this repository. It is a Hermes Agent plugin and local operations layer for running a managed multi-agent team: packaged specialist profiles, skill-based routing, Kanban-backed work tracking, model-set controls, orchestration helpers, GPT escalation, Discord intake, and P2P delegation.

The AgentAnycast SDK under `src/agentanycast/` is the underlying transport layer. Do not present this repository as primarily an AgentAnycast SDK repo in public docs, issue summaries, PR summaries, or generated handoff notes.

## Repository map

- `hermes-agency/` — main product area: plugin registration, CLI/slash commands, model tools, config, staff install, node manager, orchestration, Kanban bridges, pool delegation, GPT bridge, Discord intake, and plugin-specific tests.
- `hermes-agency/default_staff/` — packaged `agency-*` staff profiles and their role definitions.
- `hermes-agency/model_sets/` — packaged model-set strategies for installed staff profiles.
- `src/agentanycast/` — P2P transport SDK used by Hermes Agency. Touch this only for transport tasks or security fixes that explicitly require it.
- `docker/`, `Dockerfile`, `docker-compose.yml` — headless setup/node runtime. Current compose is not a dashboard service.
- `scripts/` — operational helpers such as signed auto-update setup.
- `docs/` — focused design, operations, and integration notes.

## Repository priorities

- Keep Hermes Agency product-first in public-facing documentation.
- Keep AgentAnycast described as the bundled transport/foundation, not the main user-facing deliverable.
- Keep examples generic. Use placeholders such as `<profile-name>`, `<relay-multiaddr>`, `<registry-address>`, `<workspace>`, and `<peer-id>`.
- Never commit maintainer names, machine names, private hostnames, local absolute paths, private relay addresses, private peer IDs, tokens, keys, API keys, environment dumps, gateway logs, or Discord channel IDs.
- Keep SDK imports lazy inside the plugin so Hermes can load the plugin even when optional runtime pieces are unavailable.
- Do not document a dashboard command or dashboard container unless the branch actually contains the dashboard server/routes and CLI entry point. Current compose runs setup/node only.

## Safety defaults

- Remote task execution must be conservative by default:
  - `allow_remote_tasks: false`
  - `incoming.tool_access: safe`
  - progress artifacts opt in through `incoming.send_progress: true`
- Plugin discovery must not start daemon processes when the SDK is absent or `agency.enabled: false`.
- Management endpoints, pool services, dashboard services if reintroduced, and local APIs should bind to loopback by default unless an explicit LAN/remote mode is configured.
- State-changing HTTP endpoints must require authentication.
- Do not let remote discovery metadata, handshakes, or advertised names wake arbitrary local profiles.
- Treat relay/bootstrap and anycast registry configuration as separate concerns: relay/bootstrap connects libp2p; `AGENTANYCAST_REGISTRY_ADDRS=<host>:50052` enables skill discovery.
- Always transition incoming tasks through `WORKING` before `COMPLETED`; daemon builds reject direct `SUBMITTED -> COMPLETED`.
- Keep routine model-tool responses compact. Use full `agency_info` only for troubleshooting; health checks should call `agency_info({"compact": true})` or `NodeManager.compact_info()`.

## Install for local development

From the repository root:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Docker workflow

The Docker setup should stay host-neutral and use the provided named volume.

```bash
docker compose up --build
```

The default service runs setup and the local agency node manager. It should install packaged staff, configure the active model set, initialize agency Kanban boards when available, and keep the node process alive.

Useful environment overrides:

```bash
HERMES_AGENCY_MODEL_SET=<model-set> docker compose up --build
AGENTANYCAST_RELAY=<relay-multiaddr> docker compose up --build
AGENTANYCAST_REGISTRY_ADDRS=<registry-address> docker compose up --build
HERMES_AGENCY_START_NODE=0 docker compose --profile tools run --rm setup
```

Advanced profiles:

```bash
docker compose --profile tools run --rm setup
docker compose --profile split up node
```

## Validation before commit

Run the fastest relevant checks for the files you changed, then the broader checks before pushing:

```bash
ruff check .
ruff format --check .
make test-agency
make test-sdk
python -m pytest
python -m pip check
```

For plugin/model-set changes, also run:

```bash
python -m pytest -q hermes-agency/tests/test_model_sets.py
```

For Docker changes, also run or inspect:

```bash
docker compose config
python -m py_compile docker/run_agency.py docker/hermes_compat.py
```

If dashboard code is reintroduced under `web/agency-dashboard/`, restore and run the dashboard build/typecheck commands before documenting dashboard usage.

## Dispatch and Kanban expectations

- Target-agent dispatch must route through the pool sender so offline agents can wake or queue safely.
- Kanban tasks must include board, assignee, target, status, and A2A correlation where available.
- Agency task views must aggregate agency Kanban boards, not only a default board.
- Do not hide Kanban failures silently during debugging; surface enough diagnostic context to understand missing tasks.

## Documentation expectations

- `README.md` is public-facing and should explain usage without local environment assumptions.
- `hermes-agency/README.md` is plugin/operator documentation.
- `hermes-agency/AGENTS.md` contains plugin-specific contributor rules.
- `llms.txt` should summarize Hermes Agency first and mention AgentAnycast only as the transport layer.
- Keep examples copy-pasteable but generic.
- Remove stale language such as “local testing / PR-prep” unless a section is explicitly describing a future upstream proposal.
- Never include real peer IDs, private relay addresses, private gateway names, maintainer-local paths, or private hostnames.
