# Hermes Fabric Rebrand Map — 2026-06-29

## Scope

Hermes Fabric is the frontend for Hermes Agency. Hermes Agency remains the main product and execution substrate.

This repo is a renamed MIT fork of `paperclipai/paperclip`. The goal is to take the useful frontend/backend foundation and progressively reshape it around Hermes Agency's roster, routing, wake/queue semantics, task status, artifacts, budgets, watchdogs, and human governance.

## Current Local Fork State

- Local repo: `<hermes-fabric-workspace>`
- Branch: `feat/hermes-fabric-foundation`
- Upstream fetch remote: `https://github.com/paperclipai/paperclip`
- Upstream push URL: `DISABLED`
- Root package name: `hermes-fabric`

## Product Language Rules

Use:

- Hermes Fabric
- frontend
- interface
- dashboard
- operator surface
- workspace
- Hermes Agency team
- agency roster
- specialist
- task thread
- work product
- artifact
- skill-fit routing
- wake/queue lifecycle

Avoid for new Hermes Fabric wording:

- generic autonomous AI company framing
- employee/company as primary product language
- Paperclip as the product name outside attribution/upstream references
- hardcoded personal profile names
- hardcoded model/provider assignments in shipped defaults

## Source of Truth

Hermes Agency owns:

- `agency-*` profile identities
- profile skills and descriptions
- online/offline state
- wake/sleep behavior
- persistent offline queue
- task dispatch/status
- trust/allowlist boundaries
- AgentAnycast/P2P/A2A routing

Hermes Fabric should read from and display that source of truth instead of becoming a competing source of truth for the agent workforce.

## Current Hermes Agency Context to Model

- Tenant: `default`
- Team context filter: `agency-only`
- Registered agency roster: `0/83 online`
- Offline agents are valid task targets
- Routing should use skill fit first
- Wake/queue behavior is normal and should be visible in the UI
- Example state to support: `wake_failed` with `last_error: profile agency-competitive-analyst not found`

## Rebrand Surface Inventory

Initial scan found hundreds of upstream naming/language hits. Do not bulk replace blindly. Use focused passes.

### Pass A — Public identity surfaces

Priority files:

- `README.md`
- `AGENTS.md`
- `HERMES_FABRIC.md`
- `docs/docs.json`
- `docs/start/what-is-paperclip.md`
- `docs/start/quickstart.md`
- `docs/start/core-concepts.md`
- `docs/start/architecture.md`
- `server/src/ui-branding.ts`
- `docs/images/logo-light.svg`
- `docs/images/logo-dark.svg`

Goal: rename user-facing product identity to Hermes Fabric while preserving upstream attribution.

### Pass B — Runtime branding/configuration

Priority files:

- `package.json`
- `server/package.json`
- `cli/package.json`
- `ui/package.json`
- package names under `packages/*/package.json`
- CLI entrypoints and help text
- server-rendered page titles and metadata

Goal: make the app visibly run as Hermes Fabric while minimizing package namespace churn until imports are mapped.

### Pass C — Hermes Agency roster foundation

Add minimal read-only server surface for agency roster data before changing task execution:

- `GET /api/hermes-agency/roster`
- `GET /api/hermes-agency/agents/:name`

Expected model fields:

- `name`
- `description`
- `skills`
- `online`
- `lastSeen`
- `wakeAttempts`
- `lastAttempt`
- `lastError`
- `model`
- `provider`

Goal: show all 83 agents, including offline agents, before dispatching work.

### Pass D — Hermes Agency task dispatch

Add task send/status bridge only after roster visibility works:

- direct profile dispatch first
- skill-fit routing second
- preserve offline queue semantics
- show queued/running/completed/blocked/wake_failed states in the task thread
- store returned reports and validation evidence as artifacts/work products

## First UI Feature Target

Build a Hermes Agency roster page/card set that shows:

- total agents: 83
- online/offline count
- skill chips
- description
- model/provider
- last seen
- wake attempts
- last error
- action affordances for wake/sleep/send task later

This should be read-only first. Dispatch comes after the status model is stable.

## Validation Policy

For foundation/rebrand docs:

```sh
npm exec --yes pnpm@9.15.4 -- run typecheck
```

For runtime/UI changes:

```sh
npm exec --yes pnpm@9.15.4 -- run typecheck
npm exec --yes pnpm@9.15.4 -- run test:run
npm exec --yes pnpm@9.15.4 -- run build
```

For local smoke:

```sh
npm exec --yes pnpm@9.15.4 -- run dev:once
curl http://localhost:3100/api/health
```

If port 3100 is occupied, use the dev runner's reported port and verify that health endpoint instead.
