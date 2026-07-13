# Phase 17 Hermes Agency integration

**Status: shipped** (PR [#85](https://github.com/DeployFaith/Hermes_Agency/pull/85); issues [#81](https://github.com/DeployFaith/Hermes_Agency/issues/81) / [#83](https://github.com/DeployFaith/Hermes_Agency/issues/83) closed)

This workstream synchronized the reviewed Hermes Keryx Python SDK revision into `src/keryx` and verified Agency lifecycle, incoming handler, durable task handle, artifact reconciliation, and Kanban pending-review seams against the Keryx result protocol.

The synchronized revision is recorded in `src/keryx/_sync_manifest.json` so future updates remain deterministic and reviewable.

## Live proof

```bash
python scripts/e2e_agency_keryx.py --keryx-root <hermes-keryx-checkout> --work-dir .tmp/agency-phase17-e2e
```

CI workflow: `.github/workflows/agency-phase17-e2e.yml`

## What it proves

- remote specialist discovery
- authenticated sender trust
- Agency production incoming-queue completion
- Kanban running → done and pending-review reconciliation
- terminal artifact return to the sender

## Boundary notes

- The in-process golden path remains `hermes-agency/tests/test_golden_path.py`.
- Hermes Fabric live dispatch is a separate follow-up (default Fabric client is dry-run/unconfigured).
- Active residual remediation: [`docs/plans/2026-07-13-hermes-agency-full-remediation.md`](./plans/2026-07-13-hermes-agency-full-remediation.md)
- Product claim ledger: [`docs/keryx-cross-node-boundary.md`](./keryx-cross-node-boundary.md)
