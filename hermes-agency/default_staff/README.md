# Default Staff Profiles

Hermes Agency ships with a built-in roster of **83 AI agency staff profiles** covering leadership, product, engineering, design, content, marketing, QA, and support roles.

The machine-readable `manifest.json` is the canonical source for the roster count and packaged profile metadata. The pool registry in `../pool/registry_definition.json` provides the runtime capability roster used for wake, queue, and routing behavior.

## Profile contract

Each packaged profile includes:

- `SOUL.md` — identity, mission, principles, responsibilities, and behavior rules
- `ROUTING.md` — ownership boundaries, delegation rules, escalation triggers, and handoff formats
- `profile.yaml` — category, tools, tags, model family, and Agency configuration
- `skills/` — curated role-specific Hermes skills
- `.no-bundled-skills` — prevents generic bundled skills from being reseeded into Agency profiles

All packaged profiles follow `STAFF_CONTRACT.md`, the shared operating contract for the default workforce.

## Layout

```text
hermes-agency/default_staff/
├── STAFF_CONTRACT.md
├── manifest.json
├── README.md
├── __init__.py
└── profiles/
    ├── agency-orchestrator/
    │   ├── SOUL.md
    │   ├── ROUTING.md
    │   ├── profile.yaml
    │   ├── skills/
    │   └── .no-bundled-skills
    ├── agency-frontend-engineer/
    └── ... 83 profiles total
```

## Categories

The packaged workforce includes roles across:

- Leadership and operations
- Product and research
- Engineering and infrastructure
- Design, games, and creative production
- Content and documentation
- Marketing, growth, and community
- QA, review, security, release, and Git stewardship
- Support, onboarding, knowledge, finance, procurement, and legal operations

When adding or removing packaged staff, update `manifest.json`, the runtime pool registry, and this README together.

## Discovering packaged staff

```python
from hermes_agency.default_staff import list_default_staff, load_manifest

profiles = list_default_staff()
manifest = load_manifest()
```

`manifest.json` records profile names, categories, tags, paths, and delegation metadata.

## Installing staff

Packaged profiles are shipped as a library and are not automatically copied into `~/.hermes/profiles/`.

```bash
# Preview all changes
hermes agency staff install --dry-run

# Install all packaged profiles
hermes agency staff install

# Install selected profiles
hermes agency staff install agency-orchestrator agency-frontend-engineer

# Replace existing profiles with packaged versions
hermes agency staff install --force
```

Equivalent standalone commands are available through `hermes-agency staff ...`.

## Installation safety

The installer follows these rules:

1. Existing profiles are never overwritten without `--force`.
2. Only `agency-*` profiles are managed by bulk staff operations.
3. Dry-run is available before installation.
4. The `agency-` namespace prevents collisions with personal Hermes profiles.
5. Custom profiles are not overwritten unless their exact names are explicitly forced.

## Model families and Model Sets

Profiles may declare a `model_family` in `profile.yaml`. Model Sets resolve the effective provider/model in this order:

1. Explicit profile mapping in the selected Model Set
2. Profile `model_family`
3. Category-to-family mapping
4. Model Set default family

This lets Hermes Agency apply one model strategy across the entire installed workforce without editing 83 profile configs by hand.

```bash
hermes agency models plan openai-codex-only
hermes agency models apply openai-codex-only --dry-run
hermes agency models apply openai-codex-only --yes --backup
```

## Runtime defaults

Installed profiles use conservative defaults:

```yaml
agency:
  enabled: true
  auto_start: false
  allow_remote_tasks: false
  skills_from_profile: true
```

Remote execution and automatic node startup remain opt-in per profile.

## Orchestrator and specialists

`agency-orchestrator` is the primary coordinator. It can decompose work, route subtasks, track dependencies, and escalate blockers.

The remaining profiles are specialists. They own work within their role boundaries, delegate cross-domain work, and report results or blockers back to the orchestrator.

Only the configured orchestrator profile should enable the orchestrator tool surface:

```yaml
agency:
  orchestrator:
    enabled: true
    agent: agency-orchestrator
    auto_decompose: true
```

## Extending the workforce

Custom profiles can be added under `~/.hermes/profiles/agency-<name>/` with a `SOUL.md`, `ROUTING.md`, `profile.yaml` or `config.yaml`, and role-specific skills. Follow `STAFF_CONTRACT.md` so custom staff participate cleanly in routing, delegation, and escalation.
