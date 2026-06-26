# Hermes Agency Model Sets

Hermes Agency Model Sets let the agency choose a model strategy once, then apply the resolved provider/model to every installed `agency-*` Hermes profile.

This is deliberately implemented in Hermes Agency, not as a fake Hermes core `model.overrides` feature. Hermes profiles remain isolated config homes. Agency model sets resolve profile-to-family-to-model routing and then safely update only the `model` block in installed profile `config.yaml` files.

## Safety rules

- Do not put API keys, tokens, passwords, or provider credentials in presets.
- Do not overload `agency.routing`; that remains task/profile routing.
- Do not edit all 83 profiles by hand.
- Always run a dry-run plan before applying to real profiles.
- Backups are created by default for non-dry-run bulk apply unless `--no-backup` is passed.

The current writer uses PyYAML and preserves unrelated config keys, but it does not guarantee comment preservation inside `config.yaml`. Use backups before applying to real profiles.

## Commands

```bash
hermes agency models list
hermes agency models show economic
hermes agency models validate economic --strict
hermes agency models resolve agency-backend-engineer --set economic
hermes agency models plan economic
hermes agency models apply economic --dry-run
hermes agency models apply economic --yes --backup
hermes agency models restore --backup-id <id>
```

The target MVP command is:

```bash
hermes agency models apply economic --yes --backup
```

The nicer one-switch flow is:

```bash
hermes agency models use economic --apply --yes
```

## Preset locations

Packaged presets ship in:

```text
hermes-agency/model_sets/*.yaml
```

User presets live in:

```text
~/.hermes/agency/model_sets/*.yaml
```

If a user preset has the same name as a packaged preset, the user preset wins.

## Schema

Presets use model families so the agency does not hardcode 83 individual model choices.

Required top-level keys:

```yaml
version: 1
name: economic
description: "Cheap default routing for day-to-day Hermes Agency work."

defaults:
  family: general_worker

families:
  general_worker:
    provider: opencode-go
    model: deepseek-v4-flash
    reason: "Cheap routine worker."

profiles:
  agency-backend-engineer: coding_worker

escalation:
  default_family: senior_review
  triggers: [security, legal, release, destructive_change, architecture]

budget:
  warn_if_unknown_pricing: true

metadata:
  source: packaged
  last_reviewed: "2026-06-26"
```

## Resolution order

For a given profile, Hermes Agency resolves the target model in this order:

1. Explicit preset mapping in `profiles`.
2. `model_family` in packaged profile metadata, if present.
3. Category-to-family default.
4. `defaults.family`.

Risk escalation is exposed through the resolver API but does not automatically spend premium model calls until a runtime caller opts into using it.

## Packaged presets

- `balanced`: good daily default; economical workers, GPT-5.5 for orchestration/review/escalation.
- `economic`: lowest practical spend; cheap workers, GPT-5.5 only for senior/high-risk roles.
- `premium`: quality-first without pretending cost does not matter.
- `go-plan`: only OpenCode Go provider models.
- `openai-codex-only`: only OpenAI Codex provider models. Routine roles use cheaper OpenAI models, coding roles use Codex-focused models, and orchestration/senior review use GPT-5.5.
- `chatgpt-bridge-only`: only Nous Portal MiMo models. This also stamps a managed `agency.gpt_bridge` block so profiles know to package substantive work for `agency-gpt-bridge` via `orch_escalate_to_gpt`.
- `local-only`: intentionally fails validation until a real local provider/model exists.

## Examples

Example presets live in `examples/model_sets/`:

- `custom-agency.yaml`
- `local-only.example.yaml`
- `premium-with-budget-caps.yaml`

Copy one into `~/.hermes/agency/model_sets/`, rename it, then run `hermes agency models validate <name> --strict`.

## Bake-off harness

The starter bake-off harness lives in `evals/model_bakeoff/`. Use it to compare model sets on backend, Godot, security, release, docs, worldbuilding, product, QA, refactor, and routing tasks.

## Troubleshooting

If a model set applies but an agent still uses the old model, run:

```bash
hermes agency models plan economic
hermes agency doctor
```

If the plan shows drift, apply again with `--yes --backup` after confirming the target models look right.

If validation says a provider or model is unknown, update `hermes-agency/model_catalog.yaml` or fix the preset typo.

If `local-only` fails, that is expected until a real local provider is configured. OpenCode Go is not treated as free; it is plan/subscription based.
