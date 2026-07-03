# Model Sets Phase 1 — Code Review (t_888bec0b)

**Reviewer:** agency-code-reviewer  
**Scope:** Fabric model-set foundation (schema, migration `0125`, validators, service, routes, tests) plus in-worktree WIP on `packages/shared/src/index.ts` and `server/src/services/model-sets.ts`.  
**Verdict:** **Do not approve merge** until the shared barrel regression is fixed. Migration **0125** is acceptable as-is.

---

## Executive summary

| Area | Assessment |
|------|------------|
| Migration `0125_past_shinko_yamashiro.sql` | **Accept as-is** — additive, model-set–scoped, no unrelated drops |
| DB schema (`model_sets.ts`) | **Good** — FKs, unique constraints, cascade deletes |
| Validators (`model-set.ts`, `validators/index.ts`) | **Good** — Zod shapes match API contracts |
| Routes (`model-sets.ts`) | **Good** — board + company access, activity logging |
| Service (committed core) | **Good** — resolution precedence, packaged vs custom, preferences |
| Service (WIP: apply + profile sync + gateway restart) | **Reasonable direction** — needs tests and barrel fix |
| Tests | **8/8 passed** (`model-sets-routes`, `model-sets-service`) |
| `@paperclipai/shared` typecheck (worktree) | **Fails** — broken `index.ts` re-exports |

**`approved`:** `false`

---

## Migration 0125 — accept as-is

**File:** `apps/fabric/packages/db/src/migrations/0125_past_shinko_yamashiro.sql` (89 lines)

- **Only** `CREATE TABLE IF NOT EXISTS`, indexes, and idempotent `ALTER TABLE … ADD CONSTRAINT` for:
  - `model_sets`
  - `model_department_overrides`
  - `model_profile_overrides`
  - `model_pricing`
- **No** `DROP TABLE`, `DROP COLUMN`, or unrelated schema churn in this file.
- Foreign keys reference `companies` and `agents` with `ON DELETE cascade` — appropriate for tenant-scoped rows.
- Unique constraints: `(company_id, name)` on sets, `(company_id, department)`, `(company_id, agent_id)`, `(provider, model)` on pricing.

This does **not** match the task note about a ~746-line migration with unrelated drops; that concern does **not** apply to `0125` in the current tree.

**Recommendation:** Ship `0125` without splitting for Phase 1. If a separate migration is ever needed for unrelated work, keep it out of the model-set migration chain.

---

## Blocking issues

### 1. [Critical] `packages/shared/src/index.ts` barrel split breaks TypeScript

**Location:** `apps/fabric/packages/shared/src/index.ts` (~lines 1370–1454)

**Problem:** Uncommitted WIP closes a large re-export block with:

```ts
} from "./validators/model-set.js";
```

while that block still lists **company-skill** and **catalog-skill** symbols (`companySkillSourceTypeSchema`, `catalogSkillKindSchema`, etc.). Those exports live in `./validators/company-skill.js` / `./validators/index.js`, not `model-set.js`.

**Evidence:** `@paperclipai/shared` `tsc --noEmit` reports dozens of `TS2305` missing export errors from `model-set.js`.

**Fix (minimal):**

1. Keep model-set validator symbols on the existing mega-export that ends with `} from "./validators/index.js";` (as in commit `6d12eba`), **or**
2. If splitting exports, close company-skill block at `company-skill.js`, model-set at `model-set.js`, and leave catalog-team/portability/plugin on `validators/index.js`.

3. Add the new API types export **after** the fixed block:

```ts
export type { ModelSetListItem, … } from "./types/model-set-api.js";
```

**Do not merge** until `pnpm --filter @paperclipai/shared exec tsc --noEmit` passes.

---

### 2. [High] Monorepo typecheck not green on worktree

Beyond the barrel bug, `pnpm -r typecheck` may still surface **pre-existing** server errors (e.g. `pipelines.ts`, `issue-execution-policy.ts`). For Phase 1 sign-off, require at minimum:

- `@paperclipai/shared` clean after index fix
- Model-set tests green (already **8/8**)
- No **new** errors in `model-sets.ts` / `model-sets.ts` routes

---

## Security & authorization

| Check | Result |
|-------|--------|
| Company-scoped routes use `assertCompanyAccess` | Pass |
| Board/org gate `assertBoardOrgAccess` on model-set routes | Pass |
| Cross-company list/create blocked in tests | Pass (403) |
| `model_pricing` global table — PUT/GET board-only | Acceptable for instance-level pricing; document that pricing is not per-company |
| Activity log on create/update/delete/apply | Pass |
| Secrets in API payloads | None observed in validators |

**Medium (follow-up):** `hermes-profile-config.ts` builds paths with `path.join(profilesDir, profileName, "config.yaml")` without rejecting `..` or absolute segments in `profileName`. Values come from agent `adapterConfig` / `agency-*` names. Board-only apply limits exposure; still worth validating profile names before write.

**Medium (follow-up):** `applyModelSet` with `restartIdleGateways: true` triggers gateway restarts — ensure this is documented and defaults stay `false` unless operator opts in (schema default `false` — good).

---

## Correctness & design (committed + WIP)

**Strengths**

- Resolution order: profile override → department override → model set (profile mapping / default family) → agent adapter config — matches stated precedence.
- Packaged YAML sets are read-only; custom sets in DB; duplicate name checks across packaged + custom.
- `replaceDepartmentOverrides` uses delete-then-insert in one flow — acceptable for Phase 1; consider transaction wrapper if not already implicit in route handler.
- `previewApply` vs `applyModelSet` separation is clear.
- WIP adds Hermes `config.yaml` sync and optional idle gateway restart — aligned with “apply model set to running agency” goal.

**Suggestions (non-blocking)**

1. **`model-set-api.ts` types** include `monthlyEstimateLabel`, `agentCostBreakdown`, etc., while list/get handlers return slimmer rows today — fine for forward-compatible UI phase; document or narrow types until cost endpoints land.
2. **Packaged set cache** (`cachedPackagedSets`) never invalidates if `PAPERCLIP_MODEL_SETS_DIR` changes at runtime — restart-only; note in ops docs.
3. **`JSON.stringify` adapter config equality** in apply/preview can false-positive on key order — low risk for JSONB objects; optional normalized compare later.
4. **Tests:** Add coverage for `restartIdleGateways` apply flag, profile config write skip/error paths, and `model-set-cost` / pricing auto-detect when those modules are part of the same PR.

---

## Test verification

```text
pnpm --filter @paperclipai/server exec vitest run \
  src/__tests__/model-sets-routes.test.ts \
  src/__tests__/model-sets-service.test.ts

Test Files  2 passed (2)
Tests       8 passed (8)
```

---

## Files reviewed

| Path | Notes |
|------|--------|
| `packages/db/src/schema/model_sets.ts` | Tables + relations |
| `packages/db/src/migrations/0125_past_shinko_yamashiro.sql` | Accept as-is |
| `packages/shared/src/validators/model-set.ts` | Schemas |
| `packages/shared/src/validators/index.ts` | Correct re-exports |
| `packages/shared/src/index.ts` | **Broken in worktree** |
| `packages/shared/src/types/model-set-api.ts` | Future UI shapes |
| `server/src/services/model-sets.ts` | Core + WIP apply/sync |
| `server/src/routes/model-sets.ts` | HTTP surface |
| `server/src/services/hermes-profile-config.ts` | Filesystem writes |
| `server/src/__tests__/model-sets-*.test.ts` | Passing |

---

## Approval checklist

- [x] Migration 0125 scoped and additive — **approved to run**
- [ ] `packages/shared/src/index.ts` barrel fixed
- [ ] `@paperclipai/shared` typecheck passes
- [x] Model-set vitest suite passes
- [ ] Human sign-off after fix (this review)

**Next owner:** Implementer — fix `index.ts`, re-run shared typecheck, then re-request review.