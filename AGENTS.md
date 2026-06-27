# Hermes Agency — Agent Instructions

Hermes Agency is the primary deliverable in this repository. It provides the agency plugin, dashboard, model-set controls, task routing, Kanban integration, and pool-based agent delegation. The AgentAnycast SDK under `src/agentanycast/` is the transport layer the agency uses.

## Repository priorities

- Treat `hermes-agency/` as the main product area.
- Keep public documentation generic. Do not commit maintainer names, machine names, private hostnames, local absolute paths, private relay addresses, private peer IDs, tokens, keys, or environment dumps.
- Use placeholders such as `<profile-name>`, `<relay-multiaddr>`, `<registry-address>`, and `<workspace>` in examples.
- Keep SDK imports lazy inside the plugin so Hermes can load the plugin even when optional runtime pieces are unavailable.

## Install for local development

From the repository root:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Build the dashboard frontend when changing `web/agency-dashboard/`:

```bash
cd web/agency-dashboard
npm ci
npm run build
```

Run the dashboard through a Hermes runtime when available:

```bash
hermes agency dashboard --host 127.0.0.1 --no-open
```

For LAN exposure, require explicit opt-in:

```bash
hermes agency dashboard --host 0.0.0.0 --allow-lan --no-open
```

## Docker workflow

The Docker setup should stay host-neutral. Do not document host-specific paths; use the provided named volume.

```bash
docker compose up --build
```

Useful environment overrides:

```bash
HERMES_DASHBOARD_TOKEN=<token> docker compose up --build
AGENTANYCAST_RELAY=<relay-multiaddr> docker compose up --build
AGENTANYCAST_REGISTRY_ADDRS=<registry-address> docker compose up --build
```

## Validation before commit

Run the fastest relevant checks for the files you changed, then the broader checks before pushing:

```bash
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
PATH=.venv/bin:$PATH python -m pytest -q hermes-agency/tests/test_dashboard.py
cd web/agency-dashboard && npm run build
```

For plugin/model-set changes, also run:

```bash
PATH=.venv/bin:$PATH python -m pytest -q hermes-agency/tests/test_model_sets.py
```

## Dispatch and Kanban expectations

- Dashboard dispatch must create a Kanban task when requested.
- Target-agent dispatch must route through the pool sender so offline agents can wake or queue safely.
- Kanban tasks must include board, assignee, target, status, and A2A correlation where available.
- `/api/tasks` must aggregate agency Kanban boards, not only the default board.
- Do not hide Kanban failures silently during debugging; surface enough diagnostic context to understand missing tasks.

## Documentation expectations

- `README.md` is public-facing and should explain usage without local environment assumptions.
- `hermes-agency/AGENTS.md` contains plugin-specific contributor rules.
- Keep examples copy-pasteable but generic.
- Never include real peer IDs, private relay addresses, private gateway names, or maintainer-local paths.
