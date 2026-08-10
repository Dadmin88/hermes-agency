# AGENTS.md

## Repository purpose

Hermes Agency is a curated collection of professional Hermes Agent profiles designed to work together as a multidisciplinary agency.

Repository changes should improve one or more of these areas:

- profile quality;
- routing clarity;
- collaboration behavior;
- profile packaging;
- installation;
- durable user and contributor documentation.

## Sources of truth

- `agency.json` is the machine-readable roster used by the installer.
- `profiles/<name>/distribution.yaml` defines distribution metadata for a profile.
- `profiles/<name>/SOUL.md` defines the professional behavior of a profile.
- `AGENCY.md` defines the shared collaboration model.
- `README.md` is the newcomer-facing product documentation.

Keep these files consistent in the same change.

## Profile structure

Every profile must include:

```text
profiles/<profile-name>/
├── distribution.yaml
└── SOUL.md
```

Additional Hermes configuration or bundled skills may be added when they materially improve the role.

Profile names use the `agency-` prefix and lowercase kebab case.

## Profile quality standard

A profile must represent a meaningful professional specialization.

Its routing description should make clear:

- what class of work the profile owns;
- what deliverables it is expected to produce;
- how it differs from nearby specialties.

Its `SOUL.md` should define:

- role and specialty;
- core responsibilities;
- authority and handoff boundaries;
- operating standards;
- common collaborators;
- communication expectations;
- definition of done.

Profiles should be capable of independent professional judgment inside their domain. Avoid generic instructions that could be copied unchanged to every role without affecting behavior.

## Routing quality

Routing should be based on responsibility, not keyword matching.

When adding or editing a role, compare it with neighboring profiles. Overlap is acceptable when the professions are genuinely distinct, but the ownership boundary must be clear enough for an orchestrator to choose between them.

Examples:

- Product Manager defines product behavior; Technical Lead coordinates engineering execution.
- Software Architect defines durable software structure; Backend Engineer implements backend behavior.
- Product Designer defines product experience; Frontend Engineer implements the interface.
- Code Reviewer reviews implementation; QA Tester validates behavior.
- Marketing Strategist defines marketing direction; Copywriter produces persuasive copy.
- Market Researcher studies the market; User Researcher studies users.

## Collaboration standard

Profiles should work as a team without becoming interchangeable.

Shared expectations:

- inspect relevant context before acting;
- keep ownership explicit;
- use the smallest capable specialist set;
- preserve unrelated work;
- validate deliverables before completion;
- use independent review where it adds meaningful confidence;
- hand off outcome, artifacts, evidence, risks, and next action;
- escalate decisions to the role that owns them.

## Distribution metadata

Each `distribution.yaml` should include at least:

```yaml
name: agency-example
version: 0.1.0
description: "Clear routing description"
author: "Kyle French"
license: "AGPL-3.0-only"
```

Do not pin a model or provider unless the profile genuinely depends on one.

## Roster changes

When adding, renaming, or removing a profile:

1. Update the profile directory.
2. Update `agency.json`.
3. Update the README roster if category counts or profile names change.
4. Check handoff references in related profiles.
5. Confirm `install.py --list` can discover the result.

## Installer

Keep `install.py` small and dependency-free.

The installer should rely on Hermes profile commands rather than reimplement profile-management behavior. It must support the full roster and selected profile installation from `agency.json`.

## Security and repository hygiene

Never commit credentials, API keys, `.env` files, `auth.json`, memories, sessions, runtime databases, caches, logs, or user workspaces.

Keep examples generic and safe for a public repository.

## Documentation style

Write documentation for someone encountering Hermes Agency for the first time.

Documentation should explain the current product directly:

- what it is;
- why someone would use it;
- how to install it;
- how to use it;
- how the profiles are organized;
- how to contribute.

Use normal production documentation. Avoid personal notes, implementation diaries, conversational explanations, migration commentary, or historical comparisons unless a document is specifically intended to record history.
