# Hermes Agency Model Sets Acceptance Checklist

Use this before applying the canonical model set to real installed profiles.

- [ ] `hermes agency models list` shows only `openai-codex-only`.
- [ ] `hermes agency models validate openai-codex-only --strict` passes.
- [ ] `agency-backend-engineer` resolves to `openai-codex/gpt-5.6-sol`.
- [ ] `agency-orchestrator` resolves to `openai-codex/gpt-5.6-terra`.
- [ ] `agency-copywriter` resolves to `openai-codex/gpt-5.6-luna`.
- [ ] `hermes agency models plan openai-codex-only` shows installed `agency-*` profiles.
- [ ] `hermes agency models apply openai-codex-only --dry-run` writes nothing.
- [ ] `hermes agency models apply openai-codex-only --yes --backup` updates only model routing and Agency model metadata.
- [ ] `hermes agency models restore --backup-id <id>` restores previous configs.
- [ ] `hermes agency doctor` reports active model set and drift.
- [ ] Every default staff profile resolves under the canonical `openai-codex-only` preset.
- [ ] No preset, catalog, doctor output, log, or AgentCard contains secrets.
- [ ] Existing `agency.routing` behavior still works.
- [ ] Existing staff install behavior still works.
- [ ] Existing orchestrator promote/demote behavior still works.
- [ ] Tests pass in a refreshed dev environment with `pip install -e ".[dev]"`.

MVP success command:

```bash
hermes agency models apply openai-codex-only --yes --backup
```

Preferred one-switch command after validation:

```bash
hermes agency models use openai-codex-only --apply --yes
```
