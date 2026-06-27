# Hermes Agency MoA Integration

Hermes Agency integrates native Hermes Agent Mixture-of-Agents. It does not implement MoA itself.

Hermes Agent is the execution engine. Native MoA presets live under the top-level `moa:` key in the active Hermes `config.yaml`, and native Hermes Agent owns reference-model fan-out, aggregator execution, prompt/context internals, preset normalization, model-picker behavior, and `/moa` slash-command behavior.

Hermes Agency only owns Agency-layer policy and product surfaces: status/read APIs, orchestrator recommendations, Kanban event tracking, dashboard affordances, tools, and CLI commands.

## Configuration split

Native Hermes Agent MoA config remains top-level:

```yaml
moa:
  default_preset: default
  presets:
    default:
      reference_models:
        - provider: openai-codex
          model: gpt-5.5
      aggregator:
        provider: openrouter
        model: anthropic/claude-opus-4.8
      reference_temperature: 0.6
      aggregator_temperature: 0.4
      max_tokens: 4096
      enabled: true
```

Agency policy lives separately under `agency.moa:`:

```yaml
agency:
  moa:
    enabled: true
    default_preset: null
    allow_auto_moa: false
    require_confirmation: true
    kanban_tracking: true
    attach_trace_to_cards: true
    recommend_for_triggers:
      - architecture
      - security
      - release
      - destructive_change
      - blocker
```

`agency.moa.default_preset: null` means Agency uses native `moa.default_preset`. If a preset name is configured there, it must exist in native `moa.presets`.

## Verification gate

Before implementing or debugging Agency MoA, verify native Hermes Agent MoA exists:

```bash
hermes --version
hermes moa ls
hermes moa configure --help
python -c "from hermes_cli.moa_config import normalize_moa_config, resolve_moa_preset; from agent.moa_loop import MoAClient, MoAChatCompletions; print('native_moa_imports_ok')"
hermes profile
hermes config path
```

If the installed Hermes Agent does not expose native MoA, stop. Do not add a custom Agency fallback runtime.

## Agency CLI

Agency-specific read/recommend commands:

```bash
hermes agency moa status
hermes agency moa presets
hermes agency moa show default
hermes agency moa recommend "Review this architecture before release"
```

These commands inspect native Hermes Agent MoA through the Agency adapter. They do not replace `hermes moa`.

Native preset editing remains in native Hermes surfaces:

```bash
hermes moa configure [name]
```

Also use the Hermes Dashboard or Desktop model settings when those surfaces are available.

## Tools and dashboard

Agency tools:

- `agency_moa_status`
- `agency_moa_presets`
- `agency_moa_show`
- `agency_moa_recommend`

Dashboard API endpoints, under the existing `/api` prefix:

- `GET /api/agency/moa/status`
- `GET /api/agency/moa/presets`
- `GET /api/agency/moa/presets/{name}`
- `POST /api/agency/moa/recommend`

A future `run` endpoint may be added, but it must invoke native Hermes model selection with `provider=moa` and a preset name. It must not call reference models directly from Agency code.

## Orchestrator policy

MoA is recommended for high-leverage triggers such as architecture, security, release, destructive changes, and blockers.

Default behavior is recommendation-only:

- `agency.moa.allow_auto_moa=false`: recommend only.
- `agency.moa.allow_auto_moa=true` and `require_confirmation=true`: prepare the action but require confirmation.
- `agency.moa.allow_auto_moa=true` and `require_confirmation=false`: may auto-run only for configured triggers.

MoA review never bypasses existing Agency or Hermes approval gates for destructive work.

## Kanban trace limits

For v1, Agency should record only Agency-level MoA event data:

- preset name
- native provider/model selection
- prompt or task title
- final assistant output if a future native run surface is implemented
- start/end timestamps
- exit status
- error text when command execution fails

Raw reference outputs, aggregator guidance, per-reference token usage, and degraded-reference details are native Hermes internals unless Hermes Agent later exposes official trace hooks.

## What Agency must not do

Agency must not add:

- a custom MoA runtime
- a custom reference-model fan-out loop
- a custom aggregator call path
- a separate Agency preset schema or `~/.hermes/agency/moa_presets` directory
- recursive MoA
- hardcoded Anthropic/Claude requirements
- benchmark claims beyond official Hermes documentation
