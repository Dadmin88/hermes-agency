# Hermes Agency

Hermes Agency is a Hermes Agent plugin for running a managed team of specialist agents.

Instead of treating every Hermes profile as an isolated assistant, Agency lets you organize profiles into a team, discover their capabilities, delegate work, keep task state, and reconcile returned results.

> **Development status:** Hermes Agency is still development software. There is no official GitHub or PyPI release yet. Install from this repository for evaluation and development.

[![CI](https://github.com/Dadmin88/hermes-agency/actions/workflows/ci.yml/badge.svg)](https://github.com/Dadmin88/hermes-agency/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-AGPL--3.0--only-blue)](LICENSE)

## The simple model

```text
Hermes Agent
  Runs one agent/profile
        ↓
Hermes Agency
  Organizes profiles into a team
  Chooses specialists
  Delegates work
  Tracks team/task context
        ↓
Keryx
  Moves work and results between authenticated peers
```

Agency is the team/orchestration layer. Keryx is the transport layer. Hermes Agent still performs the actual AI work.

## What Agency provides

Hermes Agency currently includes:

- packaged specialist `agency-*` profiles;
- skill-based specialist discovery;
- managed delegation and wake-or-queue behavior;
- trusted incoming work handling;
- team and orchestrator context injection;
- Kanban task reconciliation when Hermes Kanban is available;
- model-set configuration across installed staff profiles;
- orchestrator-only tools for higher-level coordination;
- Keryx-first cross-node transport;
- an AgentAnycast compatibility path for older deployments;
- in-process and live multi-process proof suites.

Agency does not replace Hermes Agent. A specialist still runs as a normal Hermes profile with its own tools, skills, model configuration, and local permissions.

## Quick start

For a new development install:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Then install the starter staff pack and check the environment:

```bash
hermes-agency staff install --starter
hermes-agency setup-plugins
hermes-agency doctor
```

For the full operator walkthrough, see [Operator golden path](docs/operator-golden-path.md).

## Command surfaces

Agency has three related command surfaces:

| Surface | Where it runs | Example |
| --- | --- | --- |
| `hermes-agency ...` | Standalone package CLI. | `hermes-agency status` |
| `hermes agency ...` | Hermes plugin CLI. | `hermes agency status` |
| `/agency ...` | Inside a Hermes session. | `/agency status` |

Useful commands:

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

## How delegation works

A simplified delegation flow is:

```text
orchestrator receives work
        ↓
Agency selects a specialist/profile
        ↓
Agency tries to wake or reach that specialist
        ↓
work is delivered or queued
        ↓
Hermes performs the task
        ↓
result/artifact returns
        ↓
Agency updates orchestrator/task state
```

Agency keeps selection, team state, and task coordination above the transport layer. Keryx handles authenticated delivery and durable transport details.

## Keryx boundary

Keryx is the recommended transport for cross-node Agency work.

Keryx provides:

- authenticated peer identity;
- relay and daemon transport;
- task/result lifecycle;
- discovery and skill registration;
- remote worker delivery;
- terminal result and artifact return.

Agency provides:

- team membership and specialist meaning;
- staff/profile management;
- delegation policy;
- task/orchestrator context;
- trust rules for incoming Agency work;
- Kanban reconciliation;
- model-set policy.

Agency should not reach into Keryx's database directly.

See [Keryx cross-node boundary](docs/keryx-cross-node-boundary.md).

## Specialist staff

The packaged starter staff is made from normal Hermes profiles with Agency-specific roles and skills.

Typical specialist categories include:

- engineering;
- QA;
- product;
- research;
- design;
- content;
- marketing;
- operations;
- management.

The goal is not to force every task through a fixed org chart. Agency uses capabilities and configured policy to choose useful specialists.

## Model sets

Model sets let an operator choose one model/provider strategy and apply it consistently across installed Agency staff.

```bash
hermes-agency models list
hermes-agency models show openai-codex-only
hermes-agency models validate openai-codex-only --strict
hermes-agency models plan openai-codex-only
hermes-agency models apply openai-codex-only --dry-run
```

Packaged model sets live in `hermes-agency/model_sets/`. User overrides may live in the Hermes home directory.

Model-set files must never contain API keys, tokens, passwords, or other provider credentials.

See [Agency model sets](docs/agency-model-sets.md).

## Kanban integration

Agency can use Hermes Kanban as an operator/task-management surface when it is available.

Kanban is not the transport and it is not the execution engine. It records and presents work at a higher level while Agency and Keryx handle delegation and delivery.

## Proofs and validation

The repository keeps two important proof levels:

1. **In-process golden path**: exercises the real Agency modules with an in-memory transport adapter.
2. **Live multi-process Keryx round trip**: starts real Keryx infrastructure and verifies authenticated cross-process Agency delivery and result return.

The ordinary test suite proves repository logic. It should not be described as proof of a live cross-machine deployment unless the live integration proof actually ran.

Development checks:

```bash
ruff check .
ruff format --check .
make test-agency
make test-sdk
python -m pytest
python -m pip check
```

See [QA validation ladder](docs/qa-validation-ladder.md) for what each test level proves.

## Docker

The repository includes a headless Docker setup for development and server-style evaluation:

```bash
docker compose up --build
```

Docker is one deployment option, not a separate Agency architecture.

## Security model

Agency is designed to be conservative around remote work.

Important defaults and rules:

- plugin loading is opt-in;
- Agency runtime operation is gated by `agency.enabled`;
- remote task execution defaults to disabled;
- incoming remote work must pass Agency trust/allowlist checks;
- tool access for remote work should start with the safe policy rather than full access;
- public AgentCards contain non-secret capability metadata only;
- API keys, environment secrets, private addresses, local paths, private peer IDs, and other operator-specific details do not belong in AgentCards or public docs;
- authenticating a peer does not make every request from that peer authorized.

## What Agency is not

Hermes Agency is not:

- a replacement for Hermes Fleet;
- a private-network membership system;
- a Keryx replacement;
- a general remote shell;
- a scheduler for CPU/GPU placement;
- a reason to expose every local Hermes tool to remote peers.

Those responsibilities belong to other parts of the Hermes stack.

## Repository layout

| Area | Purpose |
| --- | --- |
| `hermes-agency/` | Plugin, CLI, tools, config, staff, orchestration, and delegation logic. |
| `hermes-agency/default_staff/` | Packaged specialist profiles. |
| `hermes-agency/model_sets/` | Packaged model/provider strategies. |
| `src/keryx/` | Vendored Keryx Python SDK used by Agency packaging. |
| `src/agentanycast/` | Legacy compatibility transport. |
| `docs/` | Operator, architecture, validation, and workflow documentation. |
| `scripts/` | Development and operational helpers. |

External Keryx Rust binaries still come from the separate [hermes-keryx](https://github.com/Dadmin88/hermes-keryx) repository.

## Documentation

Useful starting points:

- [Operator golden path](docs/operator-golden-path.md)
- [Keryx cross-node boundary](docs/keryx-cross-node-boundary.md)
- [Agency model sets](docs/agency-model-sets.md)
- [Agency MoA integration](docs/agency-moa.md)
- [QA validation ladder](docs/qa-validation-ladder.md)
- [Night Shift playbook](docs/agency-night-shift-playbook.md)

## Requirements

- Python 3.11+
- Hermes Agent 0.18.0+
- vendored Keryx Python SDK for Agency transport integration
- optional Keryx daemon/relay/edge services for cross-node operation
- AgentAnycast only when explicitly using the legacy fallback backend

## License

Current versions are licensed under the GNU Affero General Public License v3.0 only (`AGPL-3.0-only`). See [LICENSE](LICENSE).

Historical versions remain available under the license terms that applied when they were published.
