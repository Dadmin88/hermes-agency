# Hermes Agency Model Sets

Model sets let Hermes Agency resolve one named model strategy across the agency roster without hand-editing every `agency-*` profile.

This is an Agency feature, not a Hermes core profile-inheritance feature. Presets should contain provider/model routing only. Never put API keys, tokens, passwords, or provider credentials in these files.

Packaged presets:

- `balanced`: good daily default; economical workers with GPT-5.5 for orchestration/review/escalation.
- `economic`: cheapest practical default; GPT-5.5 only for senior escalation/review roles.
- `premium`: quality-first; GPT-5.5 broadly, Grok for creative/worldbuilding roles.
- `go-plan`: only `opencode-go` provider models.
- `openai-codex-only`: only `openai-codex` provider models, with role-specific OpenAI routing.
- `chatgpt-bridge-only`: only `nous` provider MiMo routing, with managed GPT bridge-first behavior.
- `local-only`: intentionally fails until real local provider/model support is configured.

Definitions:

- `free`: truly local/no-cost provider only.
- `included`: covered by an existing plan/subscription but still not technically free.
- `cheap`: expected lower marginal cost or lower quota pressure.

Useful commands:

```bash
hermes agency models list
hermes agency models show economic
hermes agency models validate economic --strict
hermes agency models resolve agency-backend-engineer --set economic
hermes agency models plan economic
hermes agency models apply economic --dry-run
hermes agency models apply economic --yes --backup
```

User presets live in `~/.hermes/agency/model_sets/*.yaml` and override packaged presets by name.
