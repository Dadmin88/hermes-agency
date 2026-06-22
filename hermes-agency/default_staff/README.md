# Default Staff Profiles

Hermes Agency ships with a built-in roster of **83 AI agency staff profiles** covering leadership, product, engineering, design, content, marketing, QA, and support roles.

## What Are Default Staff Profiles?

Default staff profiles are pre-configured Hermes profiles that come packaged with the Hermes Agency plugin. Each profile has:

- **SOUL.md** — Identity, mission, operating principles, responsibilities, and behavior rules
- **ROUTING.md** — Ownership boundaries, delegation rules, escalation triggers, and handoff formats
- **profile.yaml** — Metadata including category, tools, tags, and agency configuration

These profiles are designed to work together as a coordinated agency team. They follow the [STAFF_CONTRACT.md](STAFF_CONTRACT.md) — a universal operating contract that governs all default staff behavior.

## Where They Live

```
hermes-agency/default_staff/
  STAFF_CONTRACT.md          # Universal operating rules
  manifest.json              # Machine-readable profile registry
  README.md                  # This file
  __init__.py                # Discovery/install code
  profiles/
    agency-orchestrator/
      SOUL.md
      ROUTING.md
      profile.yaml
    agency-frontend-engineer/
      SOUL.md
      ROUTING.md
      profile.yaml
    ... (83 profiles total)
```

## Profile Categories

| Category | Count | Description |
|----------|-------|-------------|
| Leadership | 6 | Orchestrator, Chief of Staff, Project Manager, Traffic Manager, Scrum Master, Operations Manager |
| Product | 8 | Product Manager, Strategist, Business Analyst, Requirements Analyst, User/Market/Competitive Researchers, Monetization Strategist |
| Engineering | 18 | Architects, Leads, Fullstack/Frontend/Backend Engineers, DevOps, Security, Data, AI, Godot, and more |
| Design | 14 | Creative/Art Directors, UI/UX, Brand, Game Design, Worldbuilder, Technical Artist, Motion, Audio |
| Content | 9 | Editor-in-Chief, Copywriter, Technical Writer, Lore Writer, Dialogue Writer, Scriptwriter, and more |
| Marketing | 10 | Strategist, Growth, Launch, Social Media, Community, Partnerships, SEO, Email, Analytics, PR |
| QA | 10 | QA Lead/Tester, Code/Design/Security/Accessibility/Compliance Reviewers, Red Team, Release Manager, Git Steward |
| Support | 8 | Support Specialist, Customer Success, Onboarding, Training, Knowledge Manager, Finance, Procurement, Legal |

## How Hermes Agency Discovers Them

The `hermes-agency/default_staff/__init__.py` module provides discovery functions:

```python
from hermes_agency.default_staff import list_default_staff, load_manifest

# List all available default staff profiles
profiles = list_default_staff()

# Load the full manifest
manifest = load_manifest()
```

The manifest (`manifest.json`) is a machine-readable registry of all profiles with metadata, categories, tags, and delegation maps.

## Installing Default Staff Profiles

Default staff profiles are **not automatically installed** into your local `~/.hermes/profiles/`. They are shipped as a library within the plugin. To install them:

### Via CLI (recommended)

```bash
# Install all default staff profiles
hermes agency staff install

# Install specific profiles
hermes agency staff install agency-orchestrator agency-frontend-engineer

# Dry run (see what would happen)
hermes agency staff install --dry-run

# Force overwrite existing profiles
hermes agency staff install --force
```

### Via Python API

```python
from hermes_agency.default_staff import install_default_staff

# Install all
result = install_default_staff()

# Install specific profiles
result = install_default_staff(names=["agency-orchestrator", "agency-qa-lead"])

# Dry run
result = install_default_staff(dry_run=True)

# Force overwrite
result = install_default_staff(force=True)
```

## Safety: No Existing Profiles Are Touched

The installation system has strict safety rules:

1. **Never overwrites without `--force`** — If a profile with the same name already exists, it is skipped.
2. **Never touches non-agency profiles** — Only `agency-*` profiles are created. Your existing `katana`, `gpt`, `grok`, `designer`, `git`, and other profiles are never modified.
3. **Dry-run support** — Always preview before installing.
4. **Namespace isolation** — The `agency-` prefix prevents collision with user-created profiles.

## Why the `agency-` Namespace?

The `agency-` prefix serves several purposes:

- **Collision prevention** — Won't conflict with your existing Hermes profiles
- **Identification** — Instantly distinguishes built-in agency staff from custom profiles
- **Safe bulk operations** — Enables install/update/disable all agency profiles at once
- **Contract compliance** — Signals that these profiles follow the STAFF_CONTRACT.md rules

## Configuration

Each installed profile uses these defaults (in `profile.yaml`):

```yaml
agency:
  enabled: true
  auto_start: false
  allow_remote_tasks: false
  skills_from_profile: true
```

### Customizing Profiles

After installation, you can customize any profile by editing its files in `~/.hermes/profiles/agency-*/`:

- Edit `SOUL.md` to change identity, principles, or responsibilities
- Edit `ROUTING.md` to change ownership or delegation rules
- Edit `config.yaml` to change model, toolset, or agency settings

### Auto-Start

To make a profile start its P2P node automatically on session start:

```yaml
agency:
  auto_start: true
```

### Remote Tasks

To allow a profile to process incoming A2A tasks:

```yaml
agency:
  allow_remote_tasks: true
```

### Orchestrator Role

Only `agency-orchestrator` should be configured as the primary coordinator:

```yaml
agency:
  orchestrator:
    enabled: true
    agent: agency-orchestrator
    auto_decompose: true
```

## The Orchestrator vs Specialists

**agency-orchestrator** is the primary coordinator. It:
- Decomposes complex tasks into subtasks
- Routes subtasks to specialist profiles
- Tracks progress and manages dependencies
- Escalates blockers to the operator

**Specialist profiles** (all others) are domain experts. They:
- Execute specific tasks within their domain
- Delegate cross-domain work to other specialists
- Escalate when work falls outside their boundaries
- Report results back to the orchestrator

## Extending the Staff

You can create custom agency profiles by:

1. Creating a new directory under `~/.hermes/profiles/` with the `agency-` prefix
2. Adding `SOUL.md`, `ROUTING.md`, and `config.yaml`
3. Following the STAFF_CONTRACT.md rules

Custom profiles will not be overwritten by default staff installation.
