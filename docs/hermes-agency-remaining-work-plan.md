# Hermes Agency Remaining Work Plan

**Created:** 2026-07-14
**Repository:** `<workspace>/Hermes_Agency`
**Baseline commit:** `8d2317672dece7743b1701639739589a4df9245b`
**Execution mode:** Direct work only. Do not use Hermes Agency, Agency agents, delegation, or Agency task routing while those systems are unreliable.

## 1. Objective

Turn the currently validated but mixed working tree into a reviewable, mergeable, and operationally clean set of changes without losing pre-existing or concurrent work.

The engineering changes have already passed the configured Python gates, deterministic Fabric test lanes, clean Fabric installation, TypeScript typechecking, and production build. The remaining work is primarily ownership separation, cleanup, review, commit/PR construction, residual-risk remediation, and—only with explicit operator approval—deployment.

## 2. Current State

- Execution branch: `audit/hermes-agency-hardening-20260714`
- Baseline HEAD: `8d2317672dece7743b1701639739589a4df9245b`
- Eight focused implementation/test commits have been created; documentation closeout is the final local commit.
- Durable state and validation evidence is stored under `<evidence-root>/final-state/`.
- The original temporary patch and staged snapshot were lost during temporary-directory cleanup; the durable replacement snapshot, ownership manifest, and checksums now cover the retained tree.
- Thirty-one root-owned `node_modules.pre-*` backup trees were moved intact to `<evidence-root>/quarantine/root-owned-backups/` using a bounded container mount. No generated dependency backup remains in the repository.
- The only intentionally preserved unrelated worktree material was an untracked user attachment under `.hermes/attachments/`; it was excluded from every commit.
- Canonical Python, package, workflow, Compose, Fabric typecheck, focused bridge, production build, artifact-budget, and policy gates pass. Complete deterministic Fabric lane logs from the unchanged test partition are retained under `<evidence-root>/`.
- No deployment has been performed; deployment remains separately approval-gated.

## 3. Non-Negotiable Safety Rules

1. Work directly in the repository; do not invoke Hermes Agency or delegate to Agency agents.
2. Before editing, create durable current-state snapshots outside `/tmp`.
3. Do not use `git reset --hard`, `git clean`, blanket checkout/restore, or destructive cleanup.
4. Do not discard an untracked file merely because its origin is unclear.
5. Never stage all files with `git add -A` while ownership remains mixed.
6. Stage explicit paths or reviewed patch hunks only.
7. Do not commit credentials, runtime databases, desktop attachments, generated dependency trees, or machine-specific paths.
8. Do not deploy, push, merge, or perform privileged deletion without explicit operator approval.
9. Preserve the current passing test coverage; do not skip suites or weaken assertions to make gates pass.
10. Record every command and result used as release evidence.

## 4. Phase 0 — Preserve the Current State

### Actions

- Create a durable audit directory outside `/tmp`, for example:
  - `<evidence-root>/final-state/`
- Save:
  - `git status --porcelain=v1 -z`
  - full unstaged patch
  - staged patch
  - untracked-file manifest with size and modification time
  - `git diff --stat`
  - current HEAD and branch
  - checksums of all saved evidence
- Copy the existing verification logs from `<evidence-root>/` into a stable evidence subdirectory.

### Acceptance Criteria

- Evidence is stored outside `/tmp`.
- Patch and manifest files are non-empty where expected.
- Their checksums are recorded.
- No repository content changes during snapshot creation.

## 5. Phase 1 — Classify Every Changed and Untracked Path

Build a manifest with one row per path and these fields:

- path
- tracked/untracked
- probable owner: audit, pre-existing user work, concurrent skill-governance work, generated/runtime, or unknown
- intended PR stream
- keep/remove/quarantine decision
- evidence supporting the classification
- validation required

### Known groups

#### Audit/remediation work

Likely includes:

- pool authentication and CLI token propagation
- recovered-task trust revalidation
- Keryx channel ownership and connection cleanup
- Fabric profile-path hardening and atomic writes
- Fabric service-supervisor fallback
- Fabric global-route authorization
- OpenAPI route coverage
- Fabric stable-runner and test corrections
- package and release validation
- policy scanner corrections
- branding/UI regression updates
- security and release documentation
- `tests/test_keryx_client.py`
- `src/agentanycast/CHANGELOG.md`
- `apps/fabric/scripts/check-forbidden-tokens.test.mjs`
- `apps/fabric/.agents/skills/create-issue-interaction-ui/SKILL.md`

#### Concurrent or separately owned work

Keep separate until reviewed:

- `hermes-agency/skill_governance/**`
- `hermes-agency/skill_tools.py`
- `hermes-agency/tests/test_skill_governance.py`
- `hermes-agency/tests/test_skill_hub_lifecycle.py`
- `docs/agency-skill-governance.md`
- `docs/agency-skill-governance-migration-dry-run.json`
- possibly related portions of `hermes-agency/cli.py`, `config.py`, and `__init__.py`
- `docs/agency-night-shift-playbook.md`
- `docs/qa-validation-ladder.md`

#### User/runtime material that must not enter a PR

- `.hermes/desktop-attachments/hermes_dangerous.mp4`
- repository-local Keryx databases or daemon state
- generated package-manager backup trees
- build outputs, caches, logs, sockets, and temporary workspaces

### Acceptance Criteria

- Every modified or untracked path has an owner and disposition.
- No path remains classified only as “probably fine.”
- Mixed files such as `cli.py`, `config.py`, and `__init__.py` are classified at hunk level.

## 6. Phase 2 — Remove or Quarantine Generated and Runtime Artifacts

### Actions

- Obtain operator approval for privileged cleanup of root-owned dependency backups.
- Remove or move all `node_modules.pre-t_d79ea6c2-root-owned` trees after confirming they are generated dependency links/copies.
- Verify no repository-local `.keryx`, `.agency`, daemon logs, sockets, databases, build output, coverage, or temporary package directories remain.
- Keep `.gitignore` rules that prevent dependency-repair backups from polluting Git status.
- Preserve the desktop attachment outside PR staging; do not delete it without explicit instruction.

### Acceptance Criteria

- `git status --ignored` shows no unexpected runtime/build artifacts.
- No privileged cleanup is performed without approval.
- The repository still installs and builds after cleanup.

## 7. Phase 3 — Separate Work Into Reviewable Change Streams

Use explicit path/hunk staging and independent branches or commits. Do not combine unrelated work into one large commit.

### Stream A — Security and Authorization

Scope:

- pool mutation authentication
- CLI token propagation
- recovered-task trust revalidation
- Fabric instance-admin authorization
- profile path containment, symlink rejection, atomic writes, and permissions
- related regression tests

Acceptance:

- focused security tests pass
- unauthorized mutations and global operations fail
- authorized operations succeed
- no token values appear in logs, fixtures, diffs, or documentation

### Stream B — Transport and Lifecycle

Scope:

- Keryx channel ownership
- failed-connect cleanup
- process-supervisor fallback
- Keryx regression tests
- AgentAnycast changelog if appropriate

Acceptance:

- Keryx lifecycle tests pass
- existing SDK suite passes
- no regression to legacy fallback behavior

### Stream C — Packaging, CI, and Release

Scope:

- `pyproject.toml`
- `Makefile`
- CI and release workflows
- packaged default-staff resources
- isolated wheel installation and smoke validation

Acceptance:

- wheel and source distribution build cleanly
- wheel contents are inspected programmatically
- isolated import/resource smoke passes outside the source tree
- workflow YAML parses
- release workflow consumes the artifact it validated

### Stream D — Fabric Hardening and Test Infrastructure

Scope:

- stable-runner project mapping and deterministic shards
- serialized cold-start timeout policy
- clean-checkout Git provenance handling
- OpenAPI coverage
- local process supervision
- profile configuration hardening
- environment isolation
- UI and server regression repairs
- tracked skill fixture

Acceptance:

- frozen install passes
- workspace and generated-catalog preflights pass
- all TypeScript workspaces typecheck
- general server shards pass with no overlap
- serialized route shards pass with no overlap
- UI, CLI, and remaining workspace lanes pass
- production build passes

### Stream E — Branding, Policies, and Documentation

Scope:

- Hermes Agency naming corrections
- forbidden-token whole-word matching and regression test
- no-git-push policy
- branding allowlist
- changelog, security policy, contributor docs, and Fabric docs
- portable example paths

Acceptance:

- policy scanners pass
- zero unallowlisted user-facing branding violations
- no machine-specific maintainer path remains
- documentation matches actual commands and product behavior

### Stream F — Model Sets and Configuration

Scope:

- model catalog and model-set YAML changes
- CLI/config integrations
- model-set documentation and tests

This stream has mixed ownership and must not be bundled automatically with audit work.

Acceptance:

- determine whether these changes predated the audit or were concurrent
- validate every set against the catalog
- ensure removed presets are intentional
- preserve Codex-only routing requirements
- pass model-set tests and CLI smoke checks

### Stream G — Skill Governance

Treat as an independent feature stream.

Scope:

- `skill_governance/**`
- `skill_tools.py`
- associated CLI/config/plugin registration
- governance tests and docs

Acceptance:

- reconcile tracked integration hunks with untracked implementation files
- run governance and lifecycle tests
- verify packaging includes intended modules
- review migration behavior, dry-run output, authority model, path safety, and profile scoping
- do not merge partially wired integration code without the implementation files

## 8. Phase 4 — Residual Technical Debt

### 8.1 Strict Mypy debt

The configured Agency gate is Ruff, and Keryx’s 36-file Mypy scope passes. A broader strict-Mypy experiment exposed longstanding errors in legacy AgentAnycast and the plugin package.

Plan:

- establish a supported Mypy invocation that understands the `hermes-agency` package layout
- add required stubs where appropriate
- baseline existing errors rather than hiding new ones
- remediate by subsystem in separate PRs
- add CI only after the command is stable and actionable

Do not block the current hardening PRs on the entire historical typing backlog.

### 8.2 Default-staff policy review

The audit found many permissive `tool_access: full` settings. Do not mass-edit them without understanding operational requirements.

Review:

- remote-task enablement
- safe/full tool access
- progress reporting
- profile-specific need for shell/process/network access
- whether remote execution remains disabled by default

Produce a profile-by-profile decision table and security-owner approval before changing defaults.

### 8.3 Fabric build warnings

Investigate separately:

- CSS optimizer warnings for `::highlight(...)`
- `MarkdownEditor.tsx` being both statically and dynamically imported
- large Vite chunks, especially the main bundle

Acceptance:

- determine whether each warning is harmless, fixable, or requires architectural work
- add explicit budgets or documented exceptions
- do not conflate performance cleanup with security fixes

### 8.4 Monolithic test runtime

`pnpm run test:run` exceeded the available foreground timeout even though all deterministic lanes passed independently.

Plan:

- make the canonical command execute the same bounded lanes with durable summaries
- retain non-overlapping shard regression coverage
- ensure CI reports each lane separately
- add an aggregate success/failure result
- document expected runtime and resource requirements

## 9. Phase 5 — Revalidate Each Stream

For every prepared branch or commit, run only the relevant focused tests first, followed by the canonical gates before PR creation.

### Python canonical gates

```bash
make lint-agency
.venv/bin/python -m mypy src/keryx
make test-sdk
make test-agency
.venv/bin/python -m pytest -m 'not integration'
.venv/bin/python -m pip check
git diff --check
```

Also run focused governance tests if Stream G is included.

### Fabric canonical gates

From a clean verification checkout/copy:

```bash
CI=1 pnpm install --frozen-lockfile
pnpm run preflight:workspace-links
pnpm run preflight:generated-catalogs
pnpm run typecheck
node scripts/check-forbidden-tokens.test.mjs
node scripts/check-forbidden-tokens.mjs
node scripts/check-no-git-push.mjs
node scripts/check-product-branding.mjs
node --test scripts/__tests__/run-vitest-stable-shard.test.mjs
pnpm run build
```

Run all deterministic Fabric test lanes and preserve their logs. Do not infer success from partial output or a started process.

### Packaging gates

- build wheel and source distribution
- inspect wheel resources with Python rather than depending on `unzip`
- install the wheel in an isolated environment outside the source tree
- import public packages and read packaged default-staff resources

### Security and hygiene gates

- scan added lines and intended untracked source for high-confidence credential patterns
- verify no runtime database, socket, log, binary attachment, or local profile data is staged
- confirm workflow YAML parses
- confirm Compose configuration validates
- confirm no generated build output is staged

## 10. Phase 6 — Human Review and PR Construction

For each stream:

1. Review the exact staged diff.
2. Confirm staging contains only that stream.
3. Record commands and results in the commit/PR evidence.
4. Use a focused commit message.
5. Create separate PRs where streams can be reviewed independently.
6. Require security review for Stream A.
7. Require architecture/ownership review for Streams F and G.
8. Do not include the desktop attachment, generated dependency backups, runtime state, or unrelated documentation.

Suggested PR order:

1. Security and authorization
2. Keryx lifecycle
3. Packaging and CI/release
4. Fabric hardening and test infrastructure
5. Branding/policy/documentation
6. Model sets/configuration after ownership review
7. Skill governance after ownership and architecture review
8. Typing, warning, and test-runtime debt as follow-up PRs

## 11. Phase 7 — Merge, Cleanup, and Deployment

Only after review approval:

- merge in dependency order
- fast-forward the canonical local checkout
- rerun smoke tests on the merged tree
- remove obsolete worktrees and temporary verification copies
- archive verification evidence
- clean root-owned generated backups with approved privileged access

Deployment is a separate operator-approved activity. Before deployment:

- identify exact target environment
- capture current deployed version and rollback point
- validate required migrations and configuration
- prepare rollback commands
- obtain explicit approval
- deploy
- run health, authorization, task-routing, and UI smoke checks
- monitor logs and resource usage
- roll back immediately if security or lifecycle checks fail

## 12. Definition of Done

The remaining work is complete when:

- every modified and untracked path has a verified owner and disposition
- audit work is separated from pre-existing and concurrent work
- generated/runtime artifacts are removed or explicitly quarantined
- each change stream has a focused reviewed diff
- all applicable canonical gates pass from clean environments
- package and release artifacts are validated in isolation
- no secrets or private runtime material are included
- review approvals are recorded
- PRs are merged in dependency order
- the canonical checkout is clean except for intentionally preserved user material
- any deployment has explicit approval, verified health checks, and a tested rollback path

## 13. Immediate Next Actions

All local execution actions are complete. The remaining release sequence is automated publication, remote CI/review, merge, and canonical fast-forward. Deployment is explicitly excluded.

## 14. Execution Record — 2026-07-14

### Ownership and preservation

- Durable snapshot, raw status, patches, untracked metadata, copied logs, and SHA-256 checksums: `<evidence-root>/final-state/`.
- Path and hunk classification: `ownership-manifest.json` and `ownership-manifest.md` in that evidence directory.
- Generated runtime/dependency backups were quarantined rather than deleted.
- The unrelated desktop attachment remains untracked and unstaged.

### Reviewable commit sequence

1. `1d2e817 feat(agency): consolidate Codex model routing`
2. `6a9c25b feat(agency): add governed shared skill lifecycle`
3. `633fdbf fix(agency): harden remote task and transport lifecycle`
4. `ea883fe fix(fabric): harden runtime and deterministic validation`
5. `a0017b4 ci: validate packages and shard Fabric deterministically`
6. `826fd5a chore(fabric): enforce branding and build policy`
7. `7176c08 test(agency): align status with canonical model set`
8. `d9f6d47 test(fabric): isolate bridge contract from editor CSS`

The commits are presented as one integrated PR because the packaging, CI, Fabric, model-set, and governance changes share the same mixed-tree baseline and final validation. The focused commits preserve reviewer-level separation without fabricating independent branch ancestry.

### Validation evidence

- Ruff lint and format: passed.
- Strict Mypy `src/` gate: passed.
- SDK: 406 passed, 33 deselected.
- Agency canonical suite: 242 passed.
- Full non-integration Python suite: 631 passed, 33 deselected.
- Governance/default-staff focused suite: 64 passed.
- Isolated wheel build/install/import/resource/CLI/`pip check`: passed.
- Workflow YAML and Docker Compose validation: passed.
- Fabric frozen install, preflights, typecheck, stable-runner partition tests, source-policy checks, and branding scan: passed.
- Bridge contract test: 11 passed.
- Production build: passed.
- Artifact budgets: JavaScript 4,914,705 / 5,250,000 bytes; CSS 374,279 / 400,000 bytes.
- Branding policy: 20,989 matches across 1,945 files, zero violations.
- Complete earlier deterministic Fabric lane logs remain valid because the subsequent changes were limited to the editor import boundary, its focused test isolation, policy scanners, CI wiring, and documentation; each affected surface was revalidated directly.

### Residual documented debt

- Hermes Agency plugin strict typing is not falsely marked green. The supported diagnostic baseline is 824 errors across 53 files and is documented in `docs/agency-typing-baseline.md`.
- The UI bundle remains large but is now governed by a failing artifact-budget gate.
- Standards-valid Custom Highlight API optimizer warnings are documented; any additional CSS optimizer warning is a regression.

### Rollback

- Before merge: close the PR and delete the remote audit branch; the baseline branch remains unchanged.
- After merge: revert the focused commits in reverse order, beginning with documentation and test-only commits, then CI/policy, Fabric, lifecycle/security, governance, and model routing.
- Quarantined generated backups can be restored from `<evidence-root>/quarantine/root-owned-backups/` if forensic comparison is required.
- Deployment rollback is not applicable because no deployment was performed.
