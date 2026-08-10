# AGENTS.md

## Repository purpose

Hermes Agency is a curated collection of professional Hermes Agent profiles designed to work together as a multidisciplinary agency.

Repository changes should improve one or more of these areas:

- profile quality;
- skill quality;
- routing clarity;
- collaboration behavior;
- profile packaging;
- installation;
- durable user and contributor documentation.

## Sources of truth

- `agency.json` is the machine-readable roster used by the installer and distributed orchestration consumers.
- `profiles/<name>/distribution.yaml` defines distribution metadata for a profile.
- `profiles/<name>/SOUL.md` defines the professional behavior of a profile.
- `profiles/<name>/skills/` contains the task skills bundled with that profile.
- `skills-map.json` defines the target skill bundle, curation priority, and sourcing queue for every profile.
- `AGENCY.md` defines the shared collaboration model.
- `README.md` is the newcomer-facing product documentation.

Keep these files consistent in the same change.

## Profile structure

Every profile must include:

```text
profiles/<profile-name>/
├── distribution.yaml
├── SOUL.md
└── skills/
    └── <skill-name>/
        └── SKILL.md
```

Every profile must ship with at least one useful role-specific skill. Additional Hermes configuration, references, or skill helper scripts may be added when they materially improve the specialty.

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

## Skill quality standard

Skills are procedural capability, not alternate personas.

A useful skill should define a repeatable method for a recognizable class of work within the profile's specialty. It should tell the specialist when to use the procedure, what evidence or inputs matter, how to perform the work, and how to judge completion.

Skills should:

- solve a real recurring task;
- contain concrete professional procedure rather than generic advice;
- complement the profile's `SOUL.md` instead of repeating it;
- state important validation or quality gates;
- use supporting references or scripts only when they materially improve the workflow;
- avoid unnecessary tool, provider, framework, platform, or machine assumptions unless the skill is intentionally specific to them.

A profile can bundle multiple skills. Prefer a small set of strong, distinct procedures over a large collection of overlapping prompts.

## Skill map

`skills-map.json` is the curation ledger for the complete Agency skill library.

For each profile it records:

- the skills currently bundled with the profile;
- the target skills still to curate;
- whether the profile belongs to the high-priority backbone pass;
- verified legacy skill candidates where an older Agency skill may be worth salvaging.

The map's target names describe desired professional capabilities. They do not prove that a suitable third-party implementation exists.

When a target skill is added, remove it from that profile's `targets`, update `bundled`, and keep the aggregate counts accurate. When a bundled skill is renamed or removed, update the map in the same change.

### Third-party skill sourcing

Public skill directories and marketplaces are discovery sources, not runtime dependencies for Hermes Agency.

Before adding a third-party skill:

1. Follow the listing back to the canonical source repository or author.
2. Review the complete skill directory, including `SKILL.md`, scripts, references, executable files, and install instructions.
3. Verify the license permits redistribution in Hermes Agency and preserve required notices or attribution.
4. Pin the reviewed source revision rather than depending on an unreviewed moving target.
5. Reject skills that request unnecessary credentials, secret discovery, persistence, broad filesystem access, arbitrary remote code execution, opaque installers, or unrelated network access.
6. Adapt agent-specific instructions to Hermes only when the adaptation preserves the skill's intent and license requirements.
7. Vendor the reviewed skill files into the appropriate profile's `skills/` directory. Do not make profile installation fetch mutable marketplace content at runtime.
8. Add a `SOURCE.md` beside `SKILL.md` for vendored third-party skills containing the canonical source, reviewed revision, license, review date, and any local adaptations.

Prefer existing Hermes Agency skills and reputable first-party or verified sources when quality is comparable. Popularity, stars, or marketplace ranking are not substitutes for review.

## Fleet interoperability

Hermes Agency profiles are designed to run under distributed orchestration such as Hermes Fleet, with Keryx and Nodescale providing the surrounding node and transport system.

The Agency side of that contract is static and portable:

- the profile `name` is the stable identity used to refer to the same professional profile on every Hermes node;
- `agency.json` exposes the profile roster and distribution layout for machine consumers;
- each profile must be independently installable as a Hermes profile distribution;
- the same profile package should behave consistently regardless of which eligible Hermes node runs it;
- profiles and skills must not bake in node IDs, hostnames, IP addresses, machine-specific absolute paths, local credentials, or assumptions about a particular Fleet placement;
- model/provider/runtime requirements should only be declared when the professional capability genuinely depends on them.

Live placement is not stored in this repository. Fleet/Nodescale may maintain a dynamic inventory mapping profile identities to nodes where those profiles are installed and ready, then select among those nodes using live health, capacity, policy, and availability. Keryx may carry authenticated task/handoff transport to the selected node.

If a requested profile is not currently present on an eligible node, distributed orchestration may install the profile distribution on a suitable node and route work after that node reports the profile ready.

Do not add live node registries, scheduling, placement, transport, capacity management, or remote-execution logic to Hermes Agency. Preserve the clean interface: Agency defines portable professional capabilities; distributed orchestration discovers and places them.

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
3. Update `skills-map.json`.
4. Update the README roster if category counts or profile names change.
5. Check handoff references in related profiles.
6. Add or update the role's bundled skills.
7. Confirm `install.py --list` can discover the result.

Profile names are distributed identities. Renaming a profile is therefore a compatibility change for installers, Fleet inventories, task routing, saved assignments, and other consumers. Treat it deliberately rather than as a cosmetic rename.

## Installer

Keep `install.py` small and dependency-free.

The installer should rely on Hermes profile commands rather than reimplement profile-management or skill-loading behavior. The profile distribution itself owns its `skills/` directory, so installing or updating a profile carries its curated skills with it.

The installer must support the full roster and selected profile installation from `agency.json`.

## Security and repository hygiene

Never commit credentials, API keys, `.env` files, `auth.json`, memories, sessions, runtime databases, caches, logs, or user workspaces.

Treat third-party skills as executable agent instructions with meaningful access to the profile's tools and environment. Review them accordingly before vendoring.

Keep examples generic and safe for a public repository.

## Documentation style

Write documentation for someone encountering Hermes Agency for the first time.

Documentation should explain the current product directly:

- what it is;
- why someone would use it;
- how to install it;
- how to use it;
- how the profiles and skills are organized;
- how to contribute.

Use normal production documentation. Avoid personal notes, implementation diaries, conversational explanations, migration commentary, or historical comparisons unless a document is specifically intended to record history.
