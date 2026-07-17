# Agency skill-governance control plane

Status: implementation behind disabled defaults; no live profile gates or shared pool are enabled.

## Safety invariants

- Hermes native per-profile pending JSON is capture-only. Agency never calls native approval replay for shared publication.
- `agency-orchestrator` cannot propose. It can satisfy only routine approval after deterministic validation.
- `agency-security-reviewer` is required before any security/capability-sensitive proposal advances.
- The registered managed `agency-ceo` profile is escalation-only. Every decision uses a short-lived, process-authenticated capability whose exact profile and peer must match the managed roster. Display names, task text, caller strings, and Kanban authors are not authority.
- Publication and rollback require an unforgeable in-process promoter capability bound to the configured OS UID and executable identity. Production must also give that UID exclusive write access to the physical release root.
- Secrets, PII-like values, malformed frontmatter, ambiguous paths, links, special files, hard links, stale patch preimages, digest changes, missing approvals, and audit-chain failure fail closed.
- Review decisions are ordered, expiring, and bind the immutable digest, policy version, destination, baseline generation (including empty), and target generation. Security rejection and CEO rejection are terminal for that revision.

## Configuration

Defaults remain inert:

```yaml
agency:
  skill_governance:
    enabled: false
    auto_promote_after_reviews: false
    poll_interval_seconds: 30
    max_pending_bytes: 1572864
    state_path: null
    shared_skills_path: null
    hub_acquisition_enabled: false
    hub_max_results: 25
    hub_inspection_ttl_seconds: 600
```

When unset, installation-root paths resolve to:

- governance state: `<hermes-root>/.agency/skill-governance/`
- native capture: `<hermes-root>/profiles/<profile-name>/pending/skills/*.json`
- logical consumer path: `<hermes-root>/skills/shared`
- immutable releases: `<hermes-root>/skills/.agency-shared/releases/`

Do not enable the feature until an independent security review verifies the dedicated promoter identity, filesystem ownership/modes, authenticated principal bindings, and exact release candidate.

## Operator commands

Read-only/status operations:

```text
hermes agency skill-governance status --json
hermes agency skill-governance proposals --state AWAITING_SECURITY_APPROVAL --json
hermes agency skill-governance show <proposal-id> --json
```

A one-shot scan refuses to run while `agency.skill_governance.enabled` is false:

```text
hermes agency skill-governance scan --json
```

Migration planning is available in the operator CLI. Apply/restore are rejected
there and must pass through the authenticated promoter service:

```text
hermes agency skill-governance migrate plan --json
hermes agency skill-governance migrate apply --yes --json
hermes agency skill-governance migrate restore <migration-id> --yes --json
```

The migration confines canonical managed profile names, preflights every target, preserves unrelated YAML keys, sets `skills.write_approval: true` for specialists, keeps `agency-orchestrator` false, adds the configured canonical shared path once, preserves file mode, writes per-profile backups and digests, rolls back all earlier writes after a failure, and refuses restore when the current file differs from the migration output.

## Profile-local hub lifecycle

The independent `agency-skills` toolset is also disabled by default. An eligible
non-orchestrator `agency-*` worker can search, inspect/freeze, install, activate,
report, clean up, and inspect status. The current profile is resolved from the
authenticated Hermes home; no tool accepts `profile`, destination, URL, or
`force`. Inspection fetches once into isolation and installs those exact scanned
bytes. Local acquisition is never approval and cannot call the promoter.

Only `helped` evidence with an allowed materiality category and a concrete
task-specific test/command/artifact/review result creates or attaches a durable
governance proposal. Partial, no-help, harmful, or self-asserted usage remains
negative/evidence-only. Cleanup removes only receipt-owned, unchanged local
bytes; drift fails closed. Hub trust labels and scanner success are routing
inputs, not authority.

No CLI command accepts free-form approval identity. Review mutation is an authenticated-service API concern: callers must provide a principal already bound in the protected ledger, the required role, a unique nonce, and an authenticated channel. Promotion is intentionally not exposed as a general model tool or ordinary CLI action.

## Durable state and recovery

The SQLite ledger uses WAL, foreign keys, full synchronous transactions, typed proposal/review/promotion/generation/outbox/acquisition/evidence records, uniqueness constraints, and an append-only SHA-256 audit chain with an external atomic checkpoint. Promotion and rollback verify both chain and checkpoint first. Original pending bytes are copied into a content-addressed owner-only object store before proposal acknowledgement. Repeated identical scans return the existing proposal; changed bytes under one native ID fail closed; semantic duplicates retain provenance and become superseded duplicates.

Publication builds a complete sibling generation, recomputes manifests, fsyncs content, renames the immutable generation, then atomically replaces the stable `shared` symlink. Published generations are never edited in place. Rollback verifies a retained generation manifest and atomically repoints the symlink while appending an audit event.

Promotion is serialized by an interprocess lock. A durable job intent is written before publication; if the process fails after pointer swap, reconciliation verifies the active generation and deterministically commits the job/proposal ledger state. Keep at least two verified generations and tested database backups.

## Validation

Focused implementation checks:

```bash
python -m pytest -q hermes-agency/tests/test_skill_governance.py
python -m pytest -q hermes-agency/tests/test_skill_hub_lifecycle.py
ruff check hermes-agency/skill_governance hermes-agency/tests/test_skill_governance.py hermes-agency/config.py hermes-agency/cli.py
ruff format --check hermes-agency/skill_governance hermes-agency/tests/test_skill_governance.py hermes-agency/config.py hermes-agency/cli.py
```

Tests use temporary profiles, state databases, objects, and shared release roots. They must never target a live Hermes home.
