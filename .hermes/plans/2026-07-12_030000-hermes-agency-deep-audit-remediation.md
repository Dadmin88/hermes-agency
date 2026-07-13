# Hermes Agency Deep-Audit Remediation Implementation Plan

> **Execution status (2026-07-13):** Superseded for active execution by
> [`docs/plans/2026-07-13-hermes-agency-full-remediation.md`](../../docs/plans/2026-07-13-hermes-agency-full-remediation.md).
> This file is retained as historical technical detail (Phases 1–2 largely landed; remaining phases folded into
> the 2026-07-13 plan workstreams C–G).

> **For Hermes:** Use `subagent-driven-development` task-by-task. Keep each patch narrow; perform a specification review and a code-quality/security review before advancing.

**Goal:** Repair the verified Hermes Agency safety, lifecycle, remote-execution, packaging/CI, Keryx, and Fabric delivery defects in small independently verifiable phases, then reduce the architectural debt that enabled them.

**Architecture:** Preserve Hermes Agency as the Python operator layer and Keryx as primary transport. First establish host-process and lifecycle correctness, then secure remote execution at shared boundaries, then make packaging/CI reliably prove supported behavior. Decomposition happens only after regression coverage exists; it is not part of any bug-fix patch.

**Tech stack:** Python 3.11–3.13, pytest, Ruff, mypy, Hatch/uv, Docker Compose, gRPC/Keryx, Flask or FastAPI decision gate for pool service, Node/pnpm/Vitest/React for Fabric.

---

## Scope and non-negotiable constraints

### Product boundaries

- `hermes-agency/`: operator-facing Python plugin and CLI; primary implementation area.
- `src/keryx/`: vendored Python SDK; Keryx is the production transport.
- `src/agentanycast/`: legacy/fallback only; do not broaden fallback behavior during this program.
- `apps/fabric/`: separately operated Node/Paperclip-derived product; it needs parent-repository CI but must not be folded into the Python plugin.

### Preserve existing work

Do not edit, format, stage, restore, or fold in these pre-existing modified files unless Kyle separately authorizes reconciliation:

- `hermes-agency/__init__.py`
- `hermes-agency/tests/test_unit.py`

Use new focused test files wherever feasible. If a future fix absolutely requires either dirty file, stop and ask before changing it.

### Finding classification

- **Observed failure:** missing Flask dependency for the pool security suite; nonexistent release test reference; local editable gRPC mismatch.
- **High-confidence source-traced defect:** process cleanup input/PID safety, lifecycle race/cancellation, recovered work reauthorization, remote output exposure, ambient remote subprocess environment, inert relay config, externally-owned gRPC channel closure, custom Hermes-home bypass.
- **Hardening recommendation:** pool CLI token behavior, embedded non-loopback Flask policy, broader rate/frequency limits.
- **Architecture debt:** oversized mixed-responsibility modules and duplicated policy paths.
- **Environment-only issue:** current editable environment has `grpcio==1.81.1` although project metadata requires `>=1.82.1`; clean wheel installation selected 1.82.1 and passed Keryx/CLI smoke. Do not downgrade package requirements to accommodate the stale environment.

### Per-packet operating rule

For every implementation packet:

1. Run `git status --short` and `git diff --check`; confirm only known user changes plus the packet’s files exist.
2. Re-read the exact source and tests named for that packet; do not rely on audit summaries alone.
3. Add focused failing regression tests first.
4. Run the new test(s) and capture the red failure.
5. Make the smallest root-cause change; no adjacent refactor.
6. Run focused tests, then the packet’s regression suite.
7. Run Ruff on touched paths and `git diff --check`.
8. Record files changed, commands/results, residual risks, and the next phase.
9. Do not commit, push, change deployment resources, or alter the preserved dirty files without explicit authorization.

## Dependency graph

```text
Phase 0 ─┬─> Phase 1 process safety ─┐
         ├─> Phase 2 lifecycle ──────┼─> Phase 5 packaging/CI ─> Phase 9 final gates
         ├─> Phase 3A queue auth ────┤
         │       └─> Phase 3B output boundary ─> Phase 3C subprocess env
         ├─> Phase 6 Keryx contracts (after Phase 2)
         ├─> Phase 7 profile-home consistency (may follow Phase 1)
         └─> Phase 8 Fabric delivery boundary (independent)

Phase 10 modularization/optimization is blocked by Phases 1–8 and green Phase 9 gates.
```

---

## Phase 0 — Baseline, decision gates, and reproducibility

**Objective:** Create a repeatable, non-destructive baseline and settle product choices that materially affect later diffs.

**Files:**
- Create: `.hermes/plans/` packet handoff/checklist files only if needed.
- Inspect: `pyproject.toml`, `Makefile`, `.github/workflows/{ci,release}.yml`, `docker-compose.yml`, `hermes-agency/pool/{service,cli}.py`, `hermes-agency/config.py`, `hermes-agency/node_lifecycle.py`, `apps/fabric/package.json`.

### Tasks

1. Capture current branch, commit, dirty paths, and diff integrity.
   - Run: `git status --short --branch && git rev-parse HEAD && git diff --check`
   - Expected: only the two preserved user modifications; no whitespace errors.

2. Record toolchain versions and clean-install baseline.
   - Run Python/uv/Ruff/pytest versions plus Node/pnpm versions.
   - Build wheel/sdist and install the wheel into a fresh temporary virtualenv.
   - Verify `import keryx`, `hermes-agency --help`, and `pip check` from that clean environment.
   - Do not modify the current editable environment merely to make its old gRPC version pass.

3. Capture canonical current commands and expected classifications.
   - Python base SDK tests: `pytest tests/ -q -m "not integration"`.
   - Current documented Agency test command: `make test-agency`.
   - Style: `ruff check .` and `ruff format --check .`.
   - Compose syntax: `docker compose config --quiet`.
   - Fabric checks are incomplete until Phase 8; record that the previous full test run was terminated and is neither pass nor failure.

4. Obtain explicit decisions before implementation crosses these gates.
   - **Pool service:** Is `hermes-agency/pool/service.py`, its HTTP CLI, and systemd unit a supported public/operator surface? Choices: support with declared dependencies and tests, or retire coherently.
   - **Recovered remote tasks:** On changed/revoked trust, should a recovered task be rejected and dropped, or quarantined for an operator? Default proposed policy: fail closed, retain a local audit record, no remote artifact.
   - **Keryx relay setting:** Does `agency.keryx.relay_endpoint` configure the Python client, or is relay configuration exclusively owned by external `keryxd`/relay configuration? Do not silently choose a behavior.
   - **Remote redaction policy:** approve concrete redaction categories, retained local diagnostic behavior, artifact size cap, and progress rate/payload cap.

**Acceptance criteria:** a reproducible baseline exists; decisions are written down before dependent phases; no behavior changes occur.

**Stop condition:** do not start Phase 4B or Phase 6 until their respective product decision is explicit.

---

## Phase 1 — Host process-control safety

**Objective:** Guarantee agent lifecycle commands cannot target arbitrary processes through malformed names, stale pidfiles, or broad process matching.

**Files:**
- Modify: `hermes-agency/pool/tools.py`
- Possibly modify: `hermes-agency/pool/manager.py` only if a shared validator/path policy is extracted without changing manager behavior.
- Create: `hermes-agency/tests/test_pool_process_safety.py`
- Inspect direct callers: `hermes-agency/cli.py`, `hermes-agency/tools.py`, `hermes-agency/orchestrator.py`.

### Task 1.1 — Characterize invalid lifecycle input

1. Write parameterized tests for `pool_wake`, `pool_sleep`, `pool_send`, and runner cleanup using:
   - `agency-.*`
   - `agency-x/../../other`
   - `agency-x/y`
   - empty or `agency-` only
   - uppercase/space/regex metacharacter forms
   - syntactically valid but unknown profile
2. Mock filesystem writes, `subprocess.run`, `subprocess.Popen`, and signal paths.
3. Run the new tests before implementation.
   - Expected initial failure: one or more invalid strings reach path/process actions.
4. Centralize normalization/validation:
   - Normalize only a plain short name to `agency-<short-name>` where public API intentionally supports that convenience.
   - Validate final name against the exact existing lower-case `agency-` format, non-empty suffix, and length limit.
   - Resolve via `_profile_dir_for_agent_name()` after validation; reject any unknown profile before cleanup/spawn.
5. Make every public wake/sleep/send/runner-cleanup entry use the same validation path.
6. Rerun focused tests.

**Acceptance:** invalid/unknown values return a safe error before filesystem mutation, `subprocess.run`, `Popen`, `os.kill`, or `pkill` invocation.

### Task 1.2 — Replace unsafe broad daemon cleanup

1. Read all `pkill` use sites and identify whether a tracked runner process group/PID can replace each one.
2. Add a failing test proving malformed valid-prefix input cannot shape any fallback process pattern.
3. Prefer process-group or verified PID cleanup.
4. If an unavoidable legacy fallback remains:
   - build a literal escaped, anchored, profile-scoped expression;
   - invoke only after strict validation and canonical path resolution;
   - document residual ownership risk in a code comment and test it.
5. Avoid introducing new AgentAnycast behavior; this is cleanup safety only.

**Acceptance:** no attacker-controlled unescaped text reaches `pkill -f`; valid tracked daemon/runner teardown still succeeds.

### Task 1.3 — Verify runner PID identity before every signal

1. Add failing tests for:
   - stale pidfile containing a live unrelated same-user PID;
   - pidfile PID whose command line does not identify the expected runner/profile;
   - PID identity changing during TERM grace period before KILL;
   - valid expected runner PID.
2. Make PID-file candidates pass the same identity checks currently applied to `/proc`-discovered candidates.
3. Verification should use the expected runner script/profile directory and relevant command line/executable/cwd evidence, not liveness alone.
4. Remove and locally record mismatched/stale pidfiles without signaling.
5. Recheck identity immediately before `SIGKILL`.
6. Rerun the focused tests and existing pool process tests that do not require the Phase 4B dependency decision.

**Acceptance:** only a verified runner for the requested validated profile receives TERM/KILL; stale files are safely removed; valid runner shutdown remains functional.

**Phase validation:**
- `pytest hermes-agency/tests/test_pool_process_safety.py -q`
- relevant existing pool manager/provider tests
- `ruff check hermes-agency/pool/tools.py hermes-agency/tests/test_pool_process_safety.py`
- `ruff format --check` on the same paths

---

## Phase 2 — Lifecycle state machine and cancellation semantics

**Objective:** Make startup, shutdown, and synchronous timeout behavior serializable, cancellable, and incapable of late state mutation.

**Files:**
- Modify: `hermes-agency/node_lifecycle.py`
- Create: `hermes-agency/tests/test_node_lifecycle_concurrency.py`
- Inspect: `hermes-agency/tests/test_agent_lifecycle.py`

### Task 2.1 — Establish deterministic race regressions

1. Use `threading.Event`, futures, barriers, and controlled fake nodes; do not use sleep-based race tests.
2. Write failing tests for:
   - startup blocked before node assignment, then stop is requested;
   - startup blocked before serve-loop creation, then stop is requested;
   - repeated/concurrent start requests;
   - repeated stop after cancelled/failed startup.
3. Assert no live node, worker, serve task, or lifecycle loop work survives after stop returns.

### Task 2.2 — Define and enforce lifecycle ownership

1. Document internal lifecycle states, e.g. `stopped`, `starting`, `running`, `stopping`, `failed`.
2. Add one synchronization mechanism: a dedicated lock/state-machine owner, not scattered booleans.
3. Treat an incomplete `_start_future` as active lifecycle state.
4. On stop:
   - prevent new starts;
   - cancel/await/drain in-flight startup;
   - stop an already created node if startup crossed that boundary;
   - clear state only after cleanup completes.
5. Use generation/operation IDs if necessary so late completion cannot overwrite a newer stop/start transition.

### Task 2.3 — Cancel timed-out submitted operations

1. Write a failing test with a blocked coroutine that would perform a delayed state-changing side effect after caller timeout.
2. Update `_submit()` so timeout:
   - cancels the submitted future;
   - drains it for a bounded, deterministic period;
   - preserves the caller-visible timeout;
   - records/handles cancellation deterministically.
3. Define explicitly which operations are safe to cancel. If an operation reaches an irreversible external boundary, return an explicit `in_progress/unknown completion` result rather than an ordinary timeout.
4. Add tests for start, stop, and a representative send/discovery call as appropriate.

**Acceptance:** shutdown cannot return while startup can later serve; a timed-out operation cannot silently mutate state or later dispatch work; repeated lifecycle calls are idempotent; no task/thread leak occurs.

**Phase validation:** focused concurrency suite, `test_agent_lifecycle.py`, relevant `test_keryx_transport.py` from a clean compatible environment, Ruff on changed files.

---

## Phase 3A — Reauthorize recovered remote work

**Objective:** Enforce current trust/allowlist policy immediately before recovered persisted work executes.

**Files:**
- Modify: `hermes-agency/incoming_queue.py`
- Possibly modify: `hermes-agency/node_manager.py`, `hermes-agency/incoming_security.py`, `hermes-agency/trust.py`
- Create: `hermes-agency/tests/test_incoming_reauthorization.py`

### Tasks

1. Re-read and test the actual live sender-verification implementation; do not infer behavior from audit summary.
2. Characterize metadata persisted for sender identity and verification state.
3. Build one shared authorization boundary callable by both live intake and recovery execution. Do not duplicate current-policy checks in queue code.
4. Before invoking a recovered handler:
   - require sender identity;
   - re-evaluate current trust, allowlist, and remote-task policy;
   - fail closed for missing/legacy/tampered metadata;
   - apply the Phase 0 decision: reject/drop or quarantine.
5. Ensure rejected recovered work sends no progress, completion, or artifact; record only safe local audit diagnostics.
6. Add regression tests:
   - accepted/persisted task, then peer revoked, then restart;
   - missing sender identity;
   - trust downgrade or allowlist removal;
   - tampered queue record;
   - valid authorized task still resumes.

**Acceptance:** a revoked or unverifiable recovered task never executes and never sends output; a valid record resumes through the same authorization policy as live intake.

---

## Phase 3B — Central outbound sanitization and bounded remote artifacts

**Objective:** Make every remote-visible output path safe, bounded, and consistent before persistence or transport.

**Files:**
- Modify: `hermes-agency/incoming_queue.py`, `hermes-agency/task_processor.py`
- Create if no existing suitable boundary exists: `hermes-agency/outbound_security.py`
- Create: `hermes-agency/tests/test_remote_output_redaction.py`

### Tasks

1. Inventory every outbound remote path before coding:
   - progress callbacks;
   - final artifacts/results;
   - rejection output;
   - exceptions/errors;
   - persisted remote-facing progress/result text.
2. Define one final-boundary API, conceptually `sanitize_remote_text(text, kind=...)`, invoked immediately before both local persistence and `task.send_artifact()`.
3. Agree/implement policy from Phase 0:
   - fixed maximum characters/bytes per artifact;
   - maximum accumulated output per task;
   - progress frequency/payload bound;
   - deterministic truncation marker;
   - stable remote error codes and sanitized summaries.
4. Redact practical patterns at minimum:
   - bearer/API/token/key-shaped values;
   - private-key blocks;
   - credential-bearing URLs;
   - secret environment assignments/config dumps;
   - local home/profile/workspace paths;
   - private hostnames/addresses where policy requires.
5. Keep detailed raw diagnostics local only; never claim pattern matching detects every possible secret.
6. Write tests for multiline values, token-like values split across lines, URLs, local paths, private hosts, final/error/progress paths, and oversized output.

**Acceptance:** sensitive fixtures appear in neither persisted remote output nor transmitted artifact payloads; useful normal output survives; truncation is explicit and deterministic.

---

## Phase 3C — Remote subprocess environment isolation

**Objective:** Ensure remote-triggered subprocesses do not inherit ambient machine credentials or unrelated provider settings.

**Files:**
- Modify: `hermes-agency/task_processor.py`
- Possibly modify: `hermes-agency/config.py` and operator docs only if controlled extra variables are approved.
- Create: `hermes-agency/tests/test_remote_subprocess_environment.py`

### Tasks

1. Trace the subprocess command and its real minimum environmental requirements.
2. Write a failing mocked `Popen`/subprocess test with seeded tokens, cloud credentials, proxy credentials, SSH variables, and provider configuration in `os.environ`.
3. Replace `os.environ.copy()` with an allowlisted environment builder containing only controlled `PATH`, `HOME`, workspace, locale, and explicitly necessary Hermes execution variables.
4. Make any optional inherited variable an explicitly configured, named non-secret value; do not add a wildcard pass-through.
5. Keep remote hooks disabled unless existing trusted/configured policy permits them.
6. Test that required non-secret values remain and seeded secrets do not.

**Acceptance:** remote subprocess invocations have no ambient credentials by default while supported subprocess/delegation behavior remains functional.

---

## Phase 4A — Repair release workflow and canonicalize Python test taxonomy

**Objective:** Ensure CI and tag releases test all supported non-integration Python surfaces with a single maintained taxonomy.

**Files:**
- Modify: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `Makefile`, `pyproject.toml`
- Possibly create: lightweight test-selection validation helper/test if explicit path lists remain.

### Tasks

1. Write/execute a failing check confirming `.github/workflows/release.yml` references absent `hermes-agency/tests/test_gpt_bridge.py`.
2. Remove the stale reference.
3. Define named canonical groups, using pytest markers/directories or clear Make targets:
   - SDK non-integration;
   - Agency non-integration;
   - pool-service tests (only with the supported extra if retained);
   - live Keryx/relay integration, always opt-in.
4. Update Makefile, CI, and release to invoke those shared groups instead of divergent manually curated file lists.
5. Ensure lifecycle, default-staff, departments, pool manager/provider/security, and p5 security suites are not silently omitted.
6. Keep live relay/daemon tests opt-in and report their infrastructure prerequisites accurately.

**Acceptance:** CI and tagged release use the same supported test taxonomy; no tracked relevant non-integration suite is silently skipped; no stale explicit test path remains.

---

## Phase 4B — Pool service support decision and packaging repair

**Objective:** Make the pool HTTP surface genuinely supported or retire it coherently.

**Decision gate:** requires Phase 0 product decision.

### If the pool HTTP service is supported

**Files:**
- Modify: `pyproject.toml`, `hermes-agency/pool/service.py`, `hermes-agency/pool/cli.py`
- Modify/create pool tests and relevant docs/systemd unit as needed.

Tasks:
1. Add a dedicated optional `pool` dependency extra containing Flask; prefer migrating CLI HTTP to already-declared `httpx` rather than adding Requests, unless compatibility requires Requests.
2. Update CI/release test environments to install `.[pool,dev]` for pool test group.
3. Add CLI bearer header support when `HERMES_POOL_TOKEN` is configured, explicit request timeouts, and error/status handling.
4. Enforce non-loopback/no-token policy in app initialization/deployment boundary, not only `run()`, or explicitly document supported launcher-only behavior.
5. Add fresh-install smoke: import service, CLI help, pool security tests.

### If pool HTTP service is retired

Tasks:
1. Enumerate every reference to service, CLI, systemd unit, tests, and docs.
2. Remove/deprecate all of them in one coherent patch while preserving the supported in-process pool path.
3. Update CI/test selection and docs so no absent surface is advertised.

**Acceptance:** a clean install either runs the supported pool service and its security tests or no longer exposes it at all.

---

## Phase 5 — Distribution verification

**Objective:** Make artifacts—not the developer’s editable environment—the supported-package proof.

**Files:** likely CI/workflow changes only, depending on Phase 4.

### Tasks

1. Build wheel and sdist in CI.
2. Inspect artifacts for required package contents:
   - `hermes_agency` package;
   - vendored `keryx`;
   - packaged default staff;
   - packaged model sets;
   - plugin metadata/resources required at runtime.
3. Install wheel into a clean virtual environment.
4. Run `pip check`, `import keryx`, Agency CLI help, and selected package-level tests/imports.
5. Repeat on supported Python versions according to project matrix.
6. Keep the local gRPC mismatch classified as an environment repair item, not a source requirement rollback.

**Acceptance:** artifact construction/install/use catches missing files or dependency constraints before release.

---

## Phase 6 — Keryx transport contract correctness

**Objective:** Remove silent inert configuration and prevent the SDK from closing channels it does not own.

**Files:**
- Modify: `hermes-agency/node_manager.py`, `src/keryx/node.py`, `src/keryx/client.py`
- Modify/create: `hermes-agency/tests/test_keryx_transport.py` only after confirming it is not user-dirty; otherwise create a separate focused test file.
- Modify docs/config schema as required by the Phase 0 relay decision.

### Tasks

1. Confirm relay ownership decision with external Keryx runtime documentation/source.
2. If Python owns relay configuration:
   - propagate `relay_endpoint` to the actual node/daemon/client configuration path;
   - test propagation without a live relay.
3. If external daemon owns it:
   - reject, rename, deprecate, or emit a clear warning for the inert Python setting;
   - document the supported daemon configuration location.
4. Add ownership flags for injected daemon and registry channels.
5. Close only channels created by the SDK; make repeated `close()` idempotent.
6. Test caller-owned shared channels survive, internally created channels close, and configuration is effective or explicitly rejected.

**Acceptance:** relay configuration is never silently accepted without effect; caller-owned channels survive client teardown; SDK-owned channels close exactly once.

---

## Phase 7 — Hermes-home and profile-path consistency

**Objective:** Make every pool path resolve against the active configured Hermes installation rather than global `$HOME/.hermes` state.

**Files:**
- Modify: `hermes-agency/pool/tools.py`
- Possibly modify: `hermes-agency/pool/manager.py` or a narrow shared path helper
- Create: `hermes-agency/tests/test_pool_profile_paths.py`

### Tasks

1. Establish one precedence policy:
   1. `HERMES_PROFILES_DIR`
   2. otherwise `HERMES_HOME/profiles`
   3. otherwise default Hermes home.
2. Remove/import-time freeze environment-derived profile constants where runtime isolation is expected.
3. Reuse canonical containment validation from Phase 1.
4. Add isolated temporary-home tests for wake, sleep, send, runner discovery, and cleanup.
5. Test explicit profile directory, custom home, default home, and containment/symlink behavior.

**Acceptance:** custom configured homes never fall back to the global profile tree; valid profiles resolve consistently in tools and manager.

---

## Phase 8 — Fabric delivery boundary

**Objective:** Give the embedded Fabric workspace an active parent-repository CI contract and unambiguous ownership boundaries.

**Files:**
- Create: `.github/workflows/fabric-ci.yml`
- Modify: Fabric docs, likely `apps/fabric/doc/DEVELOPING.md`
- Possibly create: `apps/fabric/doc/HERMES_AGENCY_PRECEDENCE.md`
- Inspect/possibly modify: `apps/fabric/package.json`, `apps/fabric/pnpm-workspace.yaml`, lockfile policy scripts.

### Tasks

1. Add root GitHub Actions workflow with path filters for `apps/fabric/**` and workflow changes.
2. Configure `defaults.run.working-directory: apps/fabric`.
3. Pin the selected Node major and declared pnpm version; decide whether a compatibility matrix is required.
4. Use frozen-lockfile install, then run typecheck, build, and stable unit-test shards.
5. Treat browser/E2E and release smoke as separate opt-in/scheduled checks unless a change requires them.
6. Diagnose `issue-recovery-actions.test.ts` independently first. The audit-run SIGTERM is not evidence of a test failure.
7. Add standalone validation for workspace-excluded providers: clean bootstrap/install, typecheck/test, and package/install smoke.
8. Establish an active lockfile owner and update docs/workflow to match.
9. Add a concise precedence/delta document identifying one owner and integration boundary for roster, dispatch, status, budgets, approvals/governance, and transport.
10. Decide whether nested `apps/fabric/.github/workflows` remain documented upstream references or are removed/relocated to avoid false expectations.

**Acceptance:** a Fabric type error schedules/fails a required root check; lockfile ownership is explicit and active; standalone providers receive clean validation; no Fabric full-suite success is claimed until a non-terminated full run completes.

---

## Phase 9 — Final verification and release readiness

**Objective:** Validate the repaired supported surfaces from clean environments and report all remaining limitations honestly.

### Required gates

1. `ruff check .`
2. `ruff format --check .`
3. Canonical Python SDK and Agency non-integration groups.
4. Pool-service suite with supported extras, if retained.
5. `mypy` at its defined scope.
6. `pip check` in clean install.
7. Wheel/sdist build and clean virtualenv smoke.
8. `docker compose config --quiet`; build image only if the relevant phase changed packaging/container behavior.
9. Keryx focused tests with compatible declared gRPC environment.
10. Opt-in live Keryx/relay test only where binaries/relay are available; otherwise report it as not run.
11. Fabric frozen install, typecheck, build, and unit test under the root CI environment.
12. Focused process, lifecycle, queue authorization, redaction, and subprocess-environment regressions.
13. `git diff --check` and `git status --short` verifying preserved user files were not touched.
14. Docs/config review: Keryx primary, AgentAnycast legacy; no private endpoints/IDs/paths/secrets in examples or outputs.

**Acceptance:** all required gates pass, or each failed/not-run check has a precise cause, owner, and follow-up; no result is normalized away as “probably environmental” without artifact evidence.

---

## Phase 10 — Controlled modularization and evidence-led optimization

**Objective:** Reduce the architecture debt only after behavior is protected by Phase 1–9 coverage.

**Candidate modules:** `hermes-agency/pool/tools.py`, `hermes-agency/config.py`, `hermes-agency/tools.py`, `hermes-agency/orchestrator.py`, `hermes-agency/kanban_bridge.py`, `hermes-agency/task_processor.py`.

### Rules

- One extraction per patch/PR; do not combine extraction with unrelated behavior changes.
- Characterization tests first; preserve CLI/tool/plugin public contracts.
- Suggested order:
  1. profile validation/process supervision;
  2. lifecycle state machine;
  3. outbound remote artifact policy;
  4. subprocess execution policy;
  5. config parse/normalize vs presentation;
  6. queue/roster persistence;
  7. transport façade.
- Optimize only after measuring a bottleneck. Candidate measurements: repeated roster scans, duplicate `/proc` scanning, queue persistence volume, registry discovery, context refresh, and progress payload/frequency.
- Do not introduce broad compatibility fallbacks or wake arbitrary profiles from remote metadata.

**Acceptance:** each extraction reduces a known duplication/coupling, retains behavior through characterization tests, and makes no unmeasured performance claim.

---

## First implementation packet recommendation

**Packet:** Phase 1 only — host process-control safety.

**Why first:** unrelated local process termination is the most immediate laptop-safety risk. It is independent of the policy decisions needed by packaging and Keryx transport work.

**Boundaries:** `hermes-agency/pool/tools.py` plus a new dedicated `hermes-agency/tests/test_pool_process_safety.py`; no lifecycle/CI/refactor work; no changes to the two preserved dirty files.

**Exit criteria:** malformed and unknown names are rejected before side effects; stale/reused PIDs never receive signals; valid runner cleanup passes focused regressions.

**Post-packet report format:** files changed; exact focused/broader checks with results; residual `pkill` fallback risk (if any); git status; whether Phase 2 can begin.
