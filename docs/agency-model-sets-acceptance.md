# Hermes Agency Model Sets Acceptance Checklist

Use this before applying a model set to real installed profiles.

- [ ] `hermes agency models list` shows packaged presets.
- [ ] `hermes agency models validate balanced --strict` passes.
- [ ] `hermes agency models validate economic --strict` passes.
- [ ] `hermes agency models validate premium --strict` passes.
- [ ] `hermes agency models resolve agency-backend-engineer --set economic` returns `opencode-go/deepseek-v4-pro`.
- [ ] `hermes agency models plan economic` shows installed `agency-*` profiles.
- [ ] `hermes agency models apply economic --dry-run` writes nothing.
- [ ] `hermes agency models apply economic --yes --backup` updates only model routing and Agency model metadata.
- [ ] `hermes agency models restore --backup-id <id>` restores previous configs.
- [ ] `hermes agency doctor` reports active model set and drift.
- [ ] Every default staff profile resolves under every packaged preset except `local-only`, which intentionally fails until a real local provider is configured.
- [ ] No preset, catalog, doctor output, log, or AgentCard contains secrets.
- [ ] Existing `agency.routing` behavior still works.
- [ ] Existing staff install behavior still works.
- [ ] Existing orchestrator promote/demote behavior still works.
- [ ] Tests pass in a refreshed dev environment with `pip install -e ".[dev]"`.

MVP success command:

```bash
hermes agency models apply economic --yes --backup
```

Preferred one-switch command after validation:

```bash
hermes agency models use economic --apply --yes
```
