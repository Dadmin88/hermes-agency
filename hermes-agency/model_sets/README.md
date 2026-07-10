# Hermes Agency Model Sets

Model sets let Hermes Agency resolve one named model strategy across the agency roster without hand-editing every `agency-*` profile.

This is an Agency feature, not a Hermes core profile-inheritance feature. Presets should contain provider/model routing only. Never put API keys, tokens, passwords, or provider credentials in these files.

Packaged presets:

- `openai-codex`: role-specific OpenAI Codex routing across GPT-5.6 Sol, Terra, and GPT-5.5.
- `openai-codex-only`: DF-653 rollback policy; every Agency family uses OpenAI Codex GPT-5.5.

Definitions:

- `free`: truly local/no-cost provider only.
- `included`: covered by an existing plan/subscription but still not technically free.
- `cheap`: expected lower marginal cost or lower quota pressure.

Useful commands:

```bash
hermes agency models list
hermes agency models show openai-codex-only
hermes agency models validate openai-codex-only --strict
hermes agency models resolve agency-backend-engineer --set openai-codex-only
hermes agency models plan openai-codex-only
hermes agency models apply openai-codex-only --dry-run
hermes agency models apply openai-codex-only --yes --backup
```

User presets live in `~/.hermes/agency/model_sets/*.yaml` and override packaged presets by name.
