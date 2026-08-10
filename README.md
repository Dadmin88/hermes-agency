# Hermes Agency

**Hermes Agency is a profile pack. That is the product.**

It is a curated set of professional [Hermes Agent](https://github.com/NousResearch/hermes-agent) profiles with clear role boundaries, routing descriptions, and shared collaboration rules. Install the profiles, route work to them, and let Hermes provide the runtime.

Hermes Agency does **not** contain its own web app, server, scheduler, worker runtime, networking layer, database, deployment stack, agent transport, or orchestration framework.

## Why this exists

A useful multi-agent system needs more than a pile of generic prompts. It needs specialists whose responsibilities are clear enough that a router can answer:

- Who should own this task?
- What decisions is that specialist allowed to make?
- What should they hand to another role instead?
- What evidence must they return before the work is considered done?

Hermes Agency packages those answers as installable Hermes profiles.

## Roster

### Leadership

| Profile | Responsibility |
|---|---|
| `agency-orchestrator` | Decompose goals, route work, manage dependencies, synthesize results. |
| `agency-product-manager` | Product intent, requirements, scope, priorities, acceptance criteria. |
| `agency-technical-lead` | Engineering execution strategy, technical coordination, integration risk. |

### Engineering

| Profile | Responsibility |
|---|---|
| `agency-software-architect` | System boundaries, interfaces, architecture decisions, migrations. |
| `agency-backend-engineer` | APIs, services, domain logic, application persistence, backend tests. |
| `agency-frontend-engineer` | User-facing implementation, client state, accessibility, frontend tests. |
| `agency-ai-engineer` | Model integration, agent workflows, retrieval, prompts, evals, AI failure controls. |
| `agency-data-engineer` | Data ingestion, pipelines, transformations, schemas, quality, analytical stores. |
| `agency-infrastructure-engineer` | CI/CD, environments, deployment, networking, observability, reliability. |

### Quality

| Profile | Responsibility |
|---|---|
| `agency-security-engineer` | Threat modeling, auth/authz, secrets, security review and remediation. |
| `agency-qa-engineer` | Independent behavioral validation, regression testing, bug reproduction. |
| `agency-code-reviewer` | Independent diff review for correctness, maintainability, compatibility, tests. |

### Design

| Profile | Responsibility |
|---|---|
| `agency-product-designer` | User flows, interaction design, UI states, information architecture, UX. |
| `agency-brand-designer` | Brand identity, art direction, typography, color, visual consistency. |

### Strategy & Content

| Profile | Responsibility |
|---|---|
| `agency-researcher` | Technical, product, market, user, and competitive research with evidence. |
| `agency-marketing-strategist` | Positioning, audience, messaging, campaigns, channel strategy, measurement. |
| `agency-content-writer` | Public-facing long-form copy, launch copy, articles, scripts, case studies. |
| `agency-social-media-manager` | Platform-native social posts, demo narratives, capture plans, content cadence. |
| `agency-technical-writer` | READMEs, tutorials, API/developer docs, runbooks, migrations, release notes. |

### Delivery

| Profile | Responsibility |
|---|---|
| `agency-git-steward` | Safe Git integration, staging, commits, branches, rebases, merges, PR hygiene. |

## Install

Hermes profile distributions are normally one Git repository per profile. Hermes Agency intentionally keeps the whole Agency together in one repository, so the included installer installs each `profiles/<name>` directory as a local profile distribution.

```bash
git clone https://github.com/Dadmin88/hermes-agency.git
cd hermes-agency

# Install the complete Agency.
python3 install.py

# Or install only selected roles.
python3 install.py agency-orchestrator agency-backend-engineer agency-code-reviewer
```

Use `--force` to re-apply a distribution over an existing profile while preserving Hermes-owned user data according to Hermes' distribution behavior:

```bash
python3 install.py --force
```

The installer also writes each curated routing description with `hermes profile describe`, because profile descriptions are part of Hermes' Kanban routing signal.

## Use with Hermes Kanban

Hermes already provides the durable multi-profile task board and dispatcher. Agency profiles are designed to be assignees on that board.

For a gateway/profile that should use the Agency orchestrator for decomposition, configure Hermes with:

```yaml
kanban:
  orchestrator_profile: agency-orchestrator
```

The `agency-orchestrator` profile deliberately has a narrow tool surface. It coordinates through Kanban instead of becoming another implementation worker.

## Repository layout

```text
.
├── AGENCY.md          # collaboration and routing contract
├── AGENTS.md          # scope guardrails for contributors/agents
├── agency.json        # machine-readable roster
├── install.py         # small local installer
└── profiles/
    ├── agency-orchestrator/
    │   ├── distribution.yaml
    │   ├── config.yaml
    │   └── SOUL.md
    └── ...
```

Each profile is deliberately boring to package:

- `distribution.yaml` identifies the Hermes distribution and provides a concise role description.
- `SOUL.md` contains the professional identity, authority boundaries, working method, collaboration rules, and definition of done.
- `config.yaml` is shipped only where Agency needs an opinionated capability boundary. The orchestrator is the main example.

No credentials, memories, sessions, runtime databases, workspaces, or user-specific state belong in this repository.

## Design rule

A new profile must create a **meaningfully distinct routing lane**.

If a proposed role overlaps heavily with an existing profile, improve the existing profile instead of adding another title. The goal is not to simulate an org chart. The goal is to make routing reliable and specialist output excellent.

See [AGENCY.md](./AGENCY.md) for the collaboration contract.
