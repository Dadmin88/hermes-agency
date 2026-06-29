# Hermes Fabric

Hermes Fabric is the Paperclip-derived frontend for Hermes Agency.

## Product Relationship

- **Hermes Agency** is the main product and execution substrate: the multi-agent workforce, agency-* roster, AgentAnycast/P2P/A2A routing, wake/queue behavior, trust/allowlists, and task dispatch.
- **Hermes Fabric** is the frontend and persistent operator surface for Hermes Agency: roster visibility, task threads, artifacts, status, routing decisions, budgets, watchdogs, and human governance.

## Foundation

Hermes Fabric starts from `paperclipai/paperclip` under the MIT License. Preserve upstream license attribution while transforming the product identity, data flows, and execution model around Hermes Agency.

Upstream source at fork time:

- Repository: https://github.com/paperclipai/paperclip
- Local upstream remote: `upstream`
- Fork branch: `feat/hermes-fabric-foundation`

## Core Direction

Hermes Fabric should take Paperclip's useful chassis:

- React dashboard
- server/API structure
- PostgreSQL persistence
- issue/task threads
- run logs
- artifacts/work products
- adapter architecture
- budgets/governance surfaces
- liveness/watchdog concepts

Then reshape it around Hermes Agency as source of truth for agent workforce execution:

- agency-* roster and skill tags
- offline agents as valid task targets
- skill-fit routing first
- wake/sleep lifecycle
- persistent offline queue
- A2A task dispatch/status
- trust/allowlist visibility
- specialist profile identity and descriptions

## Current Hermes Agency Context

- Tenant: `default`
- Team context filter: `agency-only`
- Registered agency roster currently reports `0/83 online`
- Offline agents are still valid targets: `agency_pool_send` / orchestrator routing should attempt wake and persistently queue if wake fails
- Routing should prefer skill fit before direct assignment when possible

## Initial Milestones

1. **Own the fork safely**
   - Keep upstream remote fetchable.
   - Disable upstream push.
   - Preserve MIT attribution.
   - Rename/rebrand from Paperclip to Hermes Fabric in focused passes.

2. **Agency roster visibility**
   - Surface all 83 agency-* profiles regardless of online status.
   - Show skills, descriptions, model/provider, online/offline, last_seen, wake attempts, last_error.

3. **Agency task dispatch**
   - Convert a Hermes Fabric task into a Hermes Agency task packet.
   - Dispatch by direct profile first, then skill-fit routing.
   - Reflect queued/wake_failed/running/completed/blocked states back into the task thread.

4. **Artifacts and validation**
   - Store returned reports, files, screenshots, diffs, URLs, logs, and validation evidence as first-class work products.

5. **Agency-native governance**
   - Add budget/time/turn guardrails.
   - Add watchdog/reviewer roles mapped to existing agency QA/review profiles.
   - Keep Hermes Agency trust/allowlist as the security boundary; Hermes Fabric must not bypass it.

## Non-Goals

- Do not make Hermes Fabric a replacement for Hermes Agency.
- Do not move agency-* profile source of truth out of Hermes Agency.
- Do not hardcode maintainer-local profiles or model/provider choices into shipped defaults.
- Do not bypass Hermes Agency's trust, relay, allowlist, or queue semantics.

## Phase 7 Rename Decisions

- **Package namespace:** keep `@paperclipai/*` workspace package names temporarily. They are wired through package imports, workspace filters, build scripts, tests, and plugin package references. Target future namespace: `@hermes-fabric/*`, but only after a dedicated package-rename migration updates imports, lockfiles, bins, publish metadata, and release tooling together.
- **CLI name:** expose `hermes-fabric` first and keep `paperclipai` as a compatibility alias. Removing `paperclipai` is deferred until package publishing and downstream docs have migrated.
- **Config path:** keep `~/.paperclip` and `PAPERCLIP_*` environment variables for now to preserve existing local dev data. Future migration should copy—not move—data into a Hermes Fabric path, verify config/db/log/storage parity, then optionally deprecate the old path. Do not delete user data during migration.
- **Docs/assets:** top-level identity and docs metadata should say Hermes Fabric. Historical docs, release notes, Paperclip skill references, and upstream attribution may retain Paperclip references until a deeper docs rewrite.
