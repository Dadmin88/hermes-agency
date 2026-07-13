# Hermes Agency Full Remediation Plan

**Date:** 2026-07-13  
**Status:** Active execution source of truth  
**Supersedes for execution:** `.hermes/plans/2026-07-12_030000-hermes-agency-deep-audit-remediation.md` (retained for historical technical detail)  
**Related audit:** `docs/audits/2026-07-10-p0-product-truth-keryx-alignment.md`

---

## Goal

Repair remaining Hermes Agency safety, remote-execution, packaging/CI, Keryx contract, and product-truth defects in small independently verifiable phases. Keep Hermes Agency as the Python operator layer and Keryx as primary transport. Do not broaden AgentAnycast behavior.

## Architecture boundaries

| Area | Role |
|---|---|
| `hermes-agency/` | Operator-facing Python plugin and CLI; primary implementation area |
| `src/keryx/` | Vendored Python SDK; production transport |
| `src/agentanycast/` | Legacy/fallback only |
| `apps/fabric/` | Separate Node operator UI; parent-repo CI required; not folded into the Python plugin |

## Non-goals (this program)

- Full Fabric live Agency dispatch client
- Growing the 83-profile roster
- AgentAnycast feature expansion
- Broad modularization of all large modules without characterization tests
- Public marketing launch / PyPI version bump unless explicitly requested
- Committing/pushing without explicit authorization

---

## Status inventory

### Already landed (do not re-do unless regressions found)

| Work | Evidence |
|---|---|
| Pool process safety (validation, pidfd ownership, broad cleanup removal) | `test_pool_process_safety.py`, `test_pool_profile_validation.py` |
| Lifecycle serialization / cancel / teardown join | `test_node_lifecycle.py` concurrency cases |
| Keryx primary runtime default | config default `keryx`; PR #71 |
| Phase 17 live cross-process Agency round trip | PR #85; `scripts/e2e_agency_keryx.py`; `.github/workflows/agency-phase17-e2e.yml`; issues #81/#83 closed |
| Fabric CI skeleton | `.github/workflows/fabric-ci.yml` |

### Remaining workstreams

| ID | Name | Status |
|---|---|---|
| A | Durable plan + cross-links | Done |
| B | Product truth lock (docs, SECURITY, changelog, examples, metadata) | Done |
| C1 | Reauthorize recovered remote work | Done |
| C2 | Outbound remote output redaction | Done |
| C3 | Remote subprocess environment isolation | Done |
| D | CI taxonomy, pool extra, wheel smoke, release fix | Done |
| E1 | Keryx relay config truth + channel ownership | Done |
| E2 | Hermes-home / profile path consistency | Done |
| F | Fabric honesty + CI completeness | Done (Fabric CI already ran typecheck/test/build; docs claim ledger updated) |
| G | Final verification gates | Done (`make test-agency` 395+ passed including new security suites) |

---

## Phase 0 product decisions (locked)

| Decision | Locked default |
|---|---|
| Pool HTTP service (`pool/service.py`) | **Support** with optional `pool` extra (Flask); CI installs `.[pool,dev]` for pool tests |
| Recovered remote tasks after trust change | **Fail closed**: reject, retain local audit only, no remote artifact/progress |
| `agency.keryx.relay_endpoint` | **Warn/document if inert**; propagate only if an SDK path exists; never invent silent daemon config |
| Remote redaction | Tokens/keys/credential URLs/private-key blocks/local paths; max artifact size; progress bound; stable remote error codes |

---

## Dependency graph

```text
A plan doc
  → B product truth
  → C1 reauth → C2 redaction → C3 subprocess env
  → D1 CI taxonomy → D2 pool extra → D3 wheel smoke
  → E1 relay → E2 profile paths
  → F Fabric honesty/CI
  → G final gates
```

---

## Workstream A — Plan document

**Deliverable:** this file.

**Also update:**

- `docs/audits/2026-07-10-p0-product-truth-keryx-alignment.md` — residual work points here
- `.hermes/plans/2026-07-12_030000-hermes-agency-deep-audit-remediation.md` — superseded banner
- `docs/plans/agent-pool-manager.md` — implemented vs wishlist banner

**Acceptance:** one plan path agents can follow without reconciling three sources.

---

## Workstream B — Product Truth Lock

### B1. Claim ledger and boundary docs

| Claim | Status after this program |
|---|---|
| Agency in-process golden path (wake, trust, delegation, artifact, Kanban) | Shipped — `hermes-agency/tests/test_golden_path.py` |
| Live multi-process Keryx Agency round trip (Phase 17) | Shipped — `scripts/e2e_agency_keryx.py` + CI workflow |
| Keryx is primary transport default | Shipped |
| AgentAnycast is legacy/fallback only | Shipped (runtime path retained) |
| Fabric shows Agency roster | Shipped (read path) |
| Fabric live dispatch to Agency by default | **Not shipped** — dry-run / unconfigured client |
| Production multi-tenant SaaS | **Not a claim** |

**Modify:**

- `docs/keryx-cross-node-boundary.md`
- `README.md`
- `hermes-agency/README.md`
- `llms.txt`
- `docs/phase17-agency-integration.md`

### B2. Security, changelog, examples, package metadata

**Modify:**

- `SECURITY.md` — Keryx-first trust boundaries
- `CHANGELOG.md` — real Unreleased / 0.8 notes for Keryx + Phase 17 + pool safety
- `examples/` — Agency/Keryx path or clearly mark legacy AgentAnycast
- `pyproject.toml` — keywords/description oriented to Agency + Keryx

### B3. Stale plan language

**Modify:** `docs/plans/agent-pool-manager.md`

**Acceptance:** primary public docs cannot invent a Phase 17 gap; AgentAnycast labeled legacy only; no private hosts/IDs/paths in examples.

**Validation:**

```bash
rg -n "Phase 17.*remain|remains Phase 17|not yet proven|complete remote Keryx round trip is Phase 17" \
  README.md hermes-agency/README.md llms.txt docs/keryx-cross-node-boundary.md docs/phase17-agency-integration.md || true
```

---

## Workstream C — Remote execution hardening

### C1. Reauthorize recovered remote work

**Modify:** `hermes-agency/incoming_queue.py`  
**Possibly:** `hermes-agency/incoming_security.py`, `hermes-agency/trust.py`  
**Create:** `hermes-agency/tests/test_incoming_reauthorization.py`

Tasks:

1. Shared authorization boundary for live intake and recovery.
2. Before recovered handler runs: require sender identity; re-evaluate trust, allowlist, and `allow_remote_tasks`; fail closed on missing/tampered metadata.
3. Rejected recovered work: local audit only; no remote artifact/progress that leaks content.
4. Tests: revoked peer after persist; missing sender; allowlist removal; valid resume.

**Acceptance:** revoked or unverifiable recovered work never executes and never sends remote output.

```bash
pytest hermes-agency/tests/test_incoming_reauthorization.py -q
```

### C2. Outbound sanitization and bounded remote artifacts

**Create:** `hermes-agency/outbound_security.py`  
**Modify:** `hermes-agency/incoming_queue.py`, `hermes-agency/task_processor.py`  
**Create:** `hermes-agency/tests/test_remote_output_redaction.py`

Tasks:

1. Inventory progress, final artifacts, rejection/errors, persisted remote-facing text.
2. Single `sanitize_remote_text(text, kind=...)` before persistence and `send_artifact`.
3. Size caps + truncation marker; redact tokens/keys/credential URLs/local paths.
4. Reuse patterns from pool startup sanitizer where appropriate.

**Acceptance:** sensitive fixtures appear in neither persisted remote output nor transmitted artifacts.

```bash
pytest hermes-agency/tests/test_remote_output_redaction.py -q
```

### C3. Remote subprocess environment isolation

**Modify:** `hermes-agency/task_processor.py`  
**Create:** `hermes-agency/tests/test_remote_subprocess_environment.py`

Tasks:

1. Replace ambient `os.environ.copy()` on remote-triggered subprocess paths with an explicit allowlist.
2. Keep required non-secret Hermes vars; no wildcard secret inheritance.
3. Tests with seeded API keys/cloud credentials proving absence.

**Acceptance:** remote subprocess invocations have no ambient credentials by default.

```bash
pytest hermes-agency/tests/test_remote_subprocess_environment.py -q
```

---

## Workstream D — CI, release, packaging

### D1. Canonical test taxonomy

**Modify:** `Makefile`, `pyproject.toml`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`

| Target | Contents |
|---|---|
| `test-sdk` | `tests/ -m "not integration"` |
| `test-agency` | unit, golden_path, model_sets, keryx, node_lifecycle, pool_*, default_staff, departments, agent_lifecycle, p5 security (non-integration) |
| `test-pool` | pool suites under `.[pool,dev]` when needed |
| `integration-agency*` | opt-in live only |

**Fix:** remove stale `hermes-agency/tests/test_gpt_bridge.py` reference from `release.yml`.

### D2. Pool service packaging

**Modify:** `pyproject.toml` optional-deps `pool = ["flask>=…"]`  
**Modify:** `hermes-agency/pool/service.py` / `cli.py` as needed for bearer token + timeouts  
**CI:** install `.[dev,pool]` for pool security tests

### D3. Distribution verification

CI job/steps:

1. Build wheel and sdist
2. Clean venv install of the wheel
3. `import keryx`, `hermes-agency --help`, `pip check`
4. Confirm packaged staff and model sets are present

**Acceptance:** CI and release share one taxonomy; no stale paths; pool tests not silently skipped; clean wheel smoke green.

---

## Workstream E — Keryx and profile path contracts

### E1. Relay config truth and channel ownership

**Inspect/modify:** `hermes-agency/config.py`, `hermes-agency/node_manager.py`, `src/keryx/node.py`, `src/keryx/client.py`, docs  
**Tests:** extend `test_keryx_transport.py` or a focused new file

- If SDK can apply `relay_endpoint` → propagate and test
- Else → warn/reject/deprecate inert setting; document daemon-owned config
- Close only channels the SDK created; repeated `close()` idempotent

### E2. Hermes-home / profile path consistency

**Modify:** `hermes-agency/pool/tools.py` (and shared helpers if needed)  
**Create:** `hermes-agency/tests/test_pool_profile_paths.py`

Precedence:

1. `HERMES_PROFILES_DIR`
2. `HERMES_HOME/profiles`
3. default Hermes home

No silent fallback to global `~/.hermes` when a custom home is active.

**Acceptance:** relay never silently no-ops; custom homes isolate; channel ownership safe.

```bash
pytest hermes-agency/tests/test_keryx_transport.py hermes-agency/tests/test_pool_profile_paths.py -q
```

---

## Workstream F — Fabric boundary

### F1. Docs honesty

**Modify:** `apps/fabric/HERMES_FABRIC.md` (and related)

- Default dispatch client remains unconfigured/dry-run until a live client exists
- Keryx-first language; Agency is workforce, Fabric is interface
- Live dispatch is a follow-up, not this program's deliverable

### F2. CI completeness

**Modify:** `.github/workflows/fabric-ci.yml` so typecheck/build/unit shards are required for `apps/fabric/**` changes when feasible without claiming browser E2E green unless proven.

**Acceptance:** Fabric type errors fail a parent-repo check; no live-dispatch marketing claims.

---

## Workstream G — Final gates

```bash
ruff check .
ruff format --check .
make test-sdk
make test-agency
python -m pip check
docker compose config --quiet
```

Live Keryx E2E: run when binaries available; otherwise record as not-run with reason.

Optional modularization only after green gates, one extraction max, with characterization tests.

---

## Per-packet operating rules

1. Re-read the exact source and tests named for the packet.
2. Add focused failing regression tests first when changing behavior.
3. Make the smallest root-cause change; no adjacent refactor.
4. Run focused tests, then the relevant regression group.
5. Run Ruff on touched paths.
6. Do not commit, push, or alter deployment secrets without explicit authorization.
7. Keep examples free of real peer IDs, private hostnames, tokens, and maintainer-local absolute paths.

---

## Definition of done

1. This file is the single execution source of truth.
2. Public docs match Phase 17 + Keryx shipped reality.
3. Recovered-task reauth, remote redaction, and subprocess env isolation land with tests.
4. CI/release run a complete non-integration Agency+pool taxonomy; release no longer references missing files.
5. Relay config and profile-home resolution are truthful and tested.
6. Fabric remains correctly scoped; parent CI contract is clear.
7. Final gates are recorded; residual risks are listed honestly.
