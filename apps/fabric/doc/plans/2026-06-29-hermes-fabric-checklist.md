# Hermes Fabric Implementation Checklist

> Hermes Fabric is the frontend for Hermes Agency. Hermes Agency remains the main product and execution substrate.

## Global Guardrails

- [ ] Do not call Hermes Fabric the main product.
- [ ] Do not use "control plane" as product language.
- [ ] Preserve MIT license attribution from upstream Paperclip.
- [ ] Keep upstream remote fetchable and push-disabled unless the operator explicitly approves otherwise.
- [ ] Do not hardcode the operator's private profiles, providers, models, tokens, paths, or credentials into shipped defaults.
- [ ] Treat offline Hermes Agency agents as valid targets.
- [ ] Prefer skill-fit routing over manual direct assignment once routing data exists.
- [ ] Keep Hermes Agency as source of truth for roster, skills, trust, wake/queue, task dispatch, and status.
- [ ] No commits or pushes unless the operator explicitly asks.

---

## Phase 0 — Fork Safety and Baseline

### 0.1 Repo safety

- [x] Clone upstream Paperclip locally as `Hermes_Fabric`.
- [x] Rename `origin` remote to `upstream`.
- [x] Disable upstream push URL.
- [x] Create working branch `feat/hermes-fabric-foundation`.
- [x] Verify branch and remote state.

### 0.2 Dependency baseline

- [x] Install dependencies with pinned pnpm:
  - [x] `npm exec --yes pnpm@9.15.4 -- install --frozen-lockfile`
- [x] Run typecheck:
  - [x] `npm exec --yes pnpm@9.15.4 -- run typecheck`
- [x] Run dev smoke:
  - [x] `npm exec --yes pnpm@9.15.4 -- run dev`
  - [x] `curl http://localhost:3100/api/health`
- [x] Stop dev server after smoke.

### 0.3 Current changed files

- [x] `package.json`
- [x] `README.md`
- [x] `AGENTS.md`
- [x] `HERMES_FABRIC.md`
- [x] `doc/plans/2026-06-29-hermes-fabric-rebrand-map.md`
- [x] `doc/plans/2026-06-29-hermes-fabric-checklist.md`

---

## Phase 1 — Product Language and Public Rebrand

Goal: make the repo clearly read as Hermes Fabric without unsafe import/package churn.

### 1.1 Foundation docs

- [x] Create `HERMES_FABRIC.md`.
- [x] State product relationship:
  - [x] Hermes Agency is the main product.
  - [x] Hermes Fabric is the frontend.
  - [x] Hermes Agency is source of truth for roster/routing/runtime.
- [x] Add initial milestones.
- [x] Add non-goals.
- [x] Remove off-scope correction language.

### 1.2 README first pass

- [x] Rename top headline to Hermes Fabric.
- [x] Replace generic AI-company positioning with Hermes Agency frontend positioning.
- [x] Replace top nav with local foundation/rebrand docs.
- [x] Replace feature table with Hermes Agency-native features.
- [x] Replace problem table with Hermes Agency workflow problems.
- [x] Replace "what it is not" section.
- [x] Keep upstream CLI names explicitly marked as temporary until CLI rename pass.
- [x] Keep remaining upstream quickstart commands explicitly temporary until package/CLI rename is implemented.
- [x] Remove inherited upstream banner reference.
- [x] Remove inherited upstream video reference.
- [x] Replace roadmap with Hermes Fabric roadmap.

### 1.3 AGENTS.md first pass

- [x] Add Hermes Fabric purpose section.
- [x] Add instruction to read `HERMES_FABRIC.md`.
- [x] Remove disallowed product phrase from touched purpose text.
- [x] Keep deeper upstream-specific fork notes for later after runtime direction is settled.

### 1.4 Text checks

- [x] Check touched foundation docs for off-scope project mention.
- [x] Check touched foundation docs for disallowed product phrase.
- [x] Search full repo for user-facing Paperclip strings.
- [x] Categorize each hit as:
  - [x] attribution/legal
  - [x] package namespace/import
  - [x] CLI/runtime config
  - [x] UI-visible copy
  - [x] docs-only copy
  - [x] test fixture/snapshot

### 1.5 Verification

- [x] `git diff --check`
- [x] `npm exec --yes pnpm@9.15.4 -- run typecheck`
- [x] `npm exec --yes pnpm@9.15.4 -- run test:run` attempted after code/runtime copy changes; full suite has unrelated upstream/local environment failures, targeted changed-area tests pass.
- [x] `npm exec --yes pnpm@9.15.4 -- run build` after UI/runtime branding changes

---

## Phase 2 — Runtime Branding Surface

Goal: make the running app visibly identify as Hermes Fabric while avoiding broad package namespace breakage.

### 2.1 Locate branding entry points

- [x] Inspect `server/src/ui-branding.ts`.
- [x] Inspect app HTML/title metadata.
- [x] Inspect UI shell/header/sidebar components.
- [x] Inspect login/onboarding screens.
- [x] Inspect local config display paths.
- [x] Inspect telemetry naming and disable controls.
- [x] Inspect package CLI name assumptions.

### 2.2 Update safe runtime strings

- [x] Replace browser title with Hermes Fabric.
- [x] Replace app header/logo text with Hermes Fabric.
- [x] Replace onboarding screen product copy with Hermes Fabric.
- [x] Replace settings/about product copy with Hermes Fabric.
- [x] Keep internal env vars/package scopes unchanged unless each dependency path is understood.

### 2.3 Add attribution surface

- [x] Add "Based on Paperclip, MIT licensed" in docs or about page.
- [x] Preserve `LICENSE`.
- [x] Do not impersonate upstream Paperclip social/docs links as Hermes Fabric links.

### 2.4 Verification

- [x] `npm exec --yes pnpm@9.15.4 -- run typecheck`
- [x] `npm exec --yes pnpm@9.15.4 -- run test:run` attempted; targeted changed-area tests pass; full suite blocked by unrelated failures.
- [x] `npm exec --yes pnpm@9.15.4 -- run build`
- [x] Run dev server.
- [x] Fetch rendered HTML.
- [x] Confirm rendered title says Hermes Fabric.
- [x] Confirm no server startup regression.

---

## Phase 3 — Hermes Agency Roster API

Goal: expose a read-only Hermes Agency roster endpoint before dispatching tasks.

### 3.1 Decide integration source

- [x] Inspect available Hermes Agency local data/API surfaces.
- [x] Prefer existing Hermes Agency roster state over handrolled profile parsing.
- [x] Confirm how to read all 83 delegable `agency-*` profiles.
- [x] Confirm how online/offline state is represented.
- [x] Confirm wake failure / last error source.
- [x] Confirm skill/description source.

### 3.2 Define shared types

- [x] Add `HermesAgencyAgent` type:
  - [x] `name`
  - [x] `description`
  - [x] `skills`
  - [x] `online`
  - [x] `status`
  - [x] `lastSeen`
  - [x] `wakeAttempts`
  - [x] `lastAttempt`
  - [x] `lastError`
  - [x] `model`
  - [x] `provider`
- [x] Add `HermesAgencyRosterResponse` type:
  - [x] `tenant`
  - [x] `filter`
  - [x] `total`
  - [x] `online`
  - [x] `offline`
  - [x] `agents[]`

### 3.3 Add server service

- [x] Create Hermes Agency service module.
- [x] Add read-only roster loader.
- [x] Normalize missing data safely.
- [x] Treat offline as normal, not error.
- [x] Return structured `lastError` when source reports wake/profile failures.
- [x] Do not mutate Agency state from roster read.

### 3.4 Add API route

- [x] Add `GET /api/hermes-agency/roster`.
- [x] Add board access checks consistent with existing instance/API patterns.
- [x] Add no activity logging because this is a read-only roster endpoint and existing read routes do not require it.
- [x] Return stable JSON shape.
- [x] Add clear error response if Hermes Agency source is unavailable.

### 3.5 Tests

- [x] Unit test roster normalization.
- [x] Unit test offline agents remain included.
- [x] Unit test source unavailable returns clear error.
- [x] API test route response shape.

### 3.6 Verification

- [x] `npm exec --yes pnpm@9.15.4 -- run typecheck`
- [x] targeted tests for roster service/route
- [x] dev server smoke
- [x] `curl http://localhost:3100/api/hermes-agency/roster`

---

## Phase 4 — Hermes Agency Roster UI

Goal: show all agency specialists in Hermes Fabric.

### 4.1 UI data client

- [x] Add API client function for `GET /api/hermes-agency/roster`.
- [x] Add frontend type imports or matching schema.
- [x] Add loading state.
- [x] Add error state.
- [x] Add empty state.

### 4.2 Roster page/card

- [x] Add nav item: `Agency Roster` or `Roster`.
- [x] Add page showing totals:
  - [x] total agents
  - [x] online count
  - [x] offline count
  - [x] wake failed count
- [x] Add agent cards/table:
  - [x] name
  - [x] description
  - [x] skills
  - [x] online/offline/status
  - [x] model/provider when available
  - [x] last seen
  - [x] last error
- [x] Add filters:
  - [x] online/offline
  - [x] skill search
  - [x] name search
  - [x] error/wake_failed only

### 4.3 UI tests

- [x] Mock roster response with 83 agents.
- [x] Mock 0 online / 83 offline.
- [x] Mock wake_failed agent.
- [x] Verify offline agents display as valid targets, not hidden failures.

### 4.4 Verification

- [x] `npm exec --yes pnpm@9.15.4 -- run typecheck`
- [x] UI tests / targeted Vitest
- [x] dev server smoke
- [x] visual/manual QA of roster page

---

## Phase 5 — Read-Only Task Mapping Design

Goal: map existing task/issue model to Hermes Agency task packets without dispatch yet.

### 5.1 Inspect current task model

- [x] Inspect issue/task schema.
- [x] Inspect comments/work products/artifacts schema.
- [x] Inspect adapter execution model.
- [x] Inspect existing Hermes local/gateway adapter.
- [x] Identify where task packet can be built without changing persistence.

### 5.2 Define Agency task packet

- [x] `title`
- [x] `goal`
- [x] `context`
- [x] `requestedSkills[]`
- [x] `targetAgentName?`
- [x] `repo/workspace context?`
- [x] `validation expectations`
- [x] `artifact expectations`
- [x] `stop conditions`

### 5.3 Add preview-only mapper

- [x] Add mapper from Hermes Fabric task to Hermes Agency task packet.
- [x] Add route or debug action to preview packet.
- [x] Do not dispatch yet.
- [x] Add tests for direct-agent and skill-routed packets.

### 5.4 Verification

- [x] typecheck
- [x] mapper unit tests
- [x] inspect preview JSON manually

---

## Phase 6 — Agency Dispatch Bridge

Goal: send work from Hermes Fabric to Hermes Agency after roster and packet preview are stable.

### 6.1 Dispatch backend

- [x] Add dispatch service.
- [x] Support direct profile dispatch first.
- [x] Support skill-fit dispatch second.
- [x] Call Hermes Agency through established safe interface seam; mocked in tests and dry-run gated for local smoke until a live bridge command is configured.
- [x] Persist returned task ID / queue ID.
- [x] Preserve offline queue semantics.
- [x] Do not treat wake failure as immediate task failure if queued.

### 6.2 Status sync

- [x] Poll or subscribe to task status.
- [x] Map states:
  - [x] queued
  - [x] wake_attempted
  - [x] wake_failed
  - [x] running
  - [x] blocked
  - [x] completed
  - [x] failed
- [x] Store status transitions in task thread/activity.
- [x] Store returned artifacts/work products.

### 6.3 UI dispatch flow

- [x] Add `Send to Hermes Agency` action.
- [x] Allow target by direct agent.
- [x] Allow target by skill.
- [x] Show route choice / selected specialist.
- [x] Show queue/wake/running status.
- [x] Show result artifacts.

### 6.4 Tests and verification

- [x] Unit test dispatch adapter.
- [x] Mock Agency offline queue response.
- [x] Mock Agency completed response.
- [x] Integration test API route with mocked Agency client.
- [x] Manual dev smoke with a harmless test task.

---

## Phase 7 — Cleanup, Naming, and Packaging

Goal: finish the rename without breaking runtime/package links.

### 7.1 Package and namespace audit

- [x] List all `@paperclipai/*` package names.
- [x] Decide which stay temporarily for internal compatibility.
- [x] Decide target package namespace.
- [x] Rename only when import paths, workspace links, bins, tests, and publishing are handled.

### 7.2 CLI rename

- [x] Decide CLI name, likely `hermes-fabric`.
- [x] Add alias first instead of removing `paperclipai` immediately.
- [x] Update README quickstart after alias works.
- [x] Update tests for CLI invocation.

### 7.3 Config path rename

- [x] Decide whether to migrate `~/.paperclip` to a Hermes Fabric config path.
- [x] If yes, write migration strategy.
- [x] Preserve existing local dev data until migration is verified.
- [x] Do not delete user data.

### 7.4 Docs and assets

- [x] Audit banner/logo assets and defer full replacement to dedicated visual asset pass.
- [x] Replace docs site metadata.
- [x] Replace roadmap.
- [x] Audit screenshots/videos and defer full replacement until new Hermes Fabric assets exist.
- [x] Keep MIT attribution.

### 7.5 Full validation

- [x] `npm exec --yes pnpm@9.15.4 -- run typecheck`
- [ ] `npm exec --yes pnpm@9.15.4 -- run test:run` — attempted; still fails on known unrelated Cursor sandbox/default-branch tests.
- [x] `npm exec --yes pnpm@9.15.4 -- run build`
- [x] dev server smoke
- [x] browser/manual QA
- [x] git status summary

---

## Delegation Plan

### Grok / broad audit

- [ ] Audit full repo for user-facing Paperclip identity surfaces.
- [ ] Return categorized hit list only; no edits.
- [ ] Identify risky package/namespace rename surfaces.

### GPT / precision implementation

- [ ] Implement roster API once source-of-truth interface is selected.
- [ ] Add tests.
- [ ] Fix type errors.

### Designer

- [ ] Review first Hermes Fabric UI shell/roster page visually.
- [ ] Recommend layout hierarchy and copy.

### Git profile

- [ ] Only when the operator asks for commit.
- [ ] Inspect dirty state.
- [ ] Stage intentional paths only.
- [ ] Commit with clear message.
- [ ] Do not push unless asked.

---

## Definition of Done for Current Sprint

- [ ] Local fork is safe.
- [ ] Foundation docs are clear.
- [ ] README top-level identity says Hermes Fabric.
- [ ] No off-scope correction language appears in touched foundation docs.
- [ ] No disallowed product phrase appears in touched foundation docs.
- [ ] Typecheck passes.
- [ ] Dev server starts and health endpoint returns ok.
- [ ] Rebrand map exists.
- [ ] Checklist exists.
- [ ] No commit or push made without the operator approval.

## Next Execution Slice

Recommended next task:

- [ ] Implement Phase 3.1 only: inspect and choose the Hermes Agency roster source-of-truth interface.
- [ ] Output a short technical note: source chosen, exact command/API/files, sample response, risks.
- [ ] Do not build UI until the roster source is confirmed.
