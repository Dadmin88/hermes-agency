# Hermes Agency Model Sets

Model sets let Hermes Agency resolve one named model strategy across the agency roster without hand-editing every `agency-*` profile.

This is an Agency feature, not a Hermes core profile-inheritance feature. Presets should contain provider/model routing only. Never put API keys, tokens, passwords, or provider credentials in these files.

The only packaged preset is `openai-codex-only`. It routes the whole Agency fleet through OpenAI Codex GPT-5.6 models: Sol for heavy engineering and senior review, Terra for orchestration/general/review/ops, and Luna for text-only writing and research synthesis.

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
