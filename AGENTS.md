# AGENTS.md

## Repository purpose

This repository has one product: **a curated pack of Hermes Agent profiles that work together as an Agency**.

Keep the repository aggressively scoped to that purpose.

## Hard scope boundary

Do **not** add:

- a web app or desktop app;
- an API server;
- a custom agent runtime;
- a queue, scheduler, dispatcher, or Kanban implementation;
- networking, A2A transport, P2P, discovery, or remote execution;
- machine/resource management;
- Docker/deployment infrastructure for an Agency service;
- a database or persistence layer for Agency state;
- dashboards, telemetry backends, or workflow engines.

Hermes Agent provides the agent runtime and Kanban primitives. Hermes Fleet or other systems may provide distributed execution. Agency supplies the professional profiles.

## Profile standard

Every profile must have:

1. `distribution.yaml`
2. `SOUL.md`

Add `config.yaml` only when the role requires an intentional capability/configuration boundary. Do not pin a model/provider merely because the author currently uses one.

A profile's `distribution.yaml` description is routing-critical. It must say what the profile is good at **and** distinguish it from neighboring roles.

A profile's `SOUL.md` must define:

- identity and mission;
- what the role owns;
- what it explicitly does not own;
- working method;
- collaboration/handoff relationships;
- shared Agency behavior;
- communication standard;
- definition of done.

## New-profile test

Before adding a role, answer:

> What class of task can this profile own better and more unambiguously than every existing profile?

If the answer is mostly a title difference, do not add the profile. Improve an existing one.

Avoid "manager inflation" and specialist pairs whose boundaries are too subtle for reliable routing.

## Collaboration rules

- Route by ownership, not keywords.
- Use the smallest capable specialist set.
- Keep implementation and independent review separate when the risk warrants it.
- Do not let one profile silently absorb another profile's decision authority.
- Handoffs must carry outcome, artifacts, evidence, risks/unknowns, and next owner.
- Named profiles remain accountable for bounded subagents used inside their own lane.
- Preserve unrelated repository/user work.

See `AGENCY.md` for the complete operating contract.

## Packaging rules

Hermes profile distributions must remain free of user/runtime state and secrets.

Never commit credentials, `.env`, `auth.json`, memories, sessions, logs, runtime DBs, workspaces, caches, or generated user state.

The root `agency.json` is the machine-readable roster and installer source of truth. When adding, renaming, or removing a profile, update it in the same change.

## Documentation style

This is a production repository, not an agent notebook.

Do not add:

- personal progress notes;
- phase diaries;
- giant planning documents for completed work;
- duplicated explanations spread across many files;
- stale architecture documents describing systems that no longer exist.

Prefer small durable documentation that explains the current product.
