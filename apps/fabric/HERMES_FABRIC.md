# Hermes Fabric

Hermes Fabric is the Hermes Fabric-derived frontend for Hermes Agency.

## Product relationship

- **Hermes Agency** is the main product and execution substrate: the multi-agent workforce, `agency-*` roster, skill-fit routing, wake/queue behavior, trust policy, task dispatch, and status tracking.
- **Keryx** is Hermes Agency's primary transport for AgentCards, skill discovery, identity, encrypted P2P communication, and task messages. AgentAnycast remains a legacy compatibility path.
- **Hermes Fabric** is the persistent operator interface for Hermes Agency: roster visibility, task threads, artifacts, status, routing decisions, budgets, watchdogs, and human governance.

Hermes Agency is the workforce. Hermes Fabric is the interface.

## Foundation

Hermes Fabric starts from `hermes-fabric/fabric` under the MIT License. Preserve upstream license attribution while transforming the product identity, data flows, and execution model around Hermes Agency.

Upstream source at fork time:

- Repository: https://github.com/DeployFaith/Hermes_Agency
- Local upstream remote: `upstream`
- Fork branch: `feat/hermes-fabric-foundation`

## Core direction

Hermes Fabric retains Hermes Fabric's useful application chassis:

- React dashboard
- server/API structure
- PostgreSQL and embedded PGlite persistence
- issue and task threads
- run logs
- artifacts and work products
- adapter architecture
- budget and governance surfaces
- liveness and watchdog concepts

It is being reshaped around Hermes Agency as the source of truth for workforce execution:

- `agency-*` roster and skill tags
- offline specialists as valid task targets
- skill-fit routing before manual assignment when possible
- wake/sleep lifecycle
- persistent offline queue
- Agency task dispatch and status
- Keryx-backed peer discovery and transport
- trust and allowlist visibility
- specialist identity, role, and descriptions

## Current integration status

The current Fabric codebase includes:

- a read-only Agency roster service and API
- an Agency roster UI
- task-packet preview types and routes
- direct-agent and skill-fit dispatch service seams
- persisted dispatch records and status models
- dry-run dispatch for local interface testing

The default Fabric dispatch client is intentionally unconfigured. A real server-to-Agency client still needs to be wired before Fabric can claim end-to-end live dispatch without an injected adapter. Dry-run records prove the operator flow, not live transport execution.

### Claim ledger (Fabric)

| Claim | Status |
|---|---|
| Fabric can show the Agency roster | Shipped (read path) |
| Fabric dry-run / dispatch-record operator flow | Shipped |
| Fabric live dispatch to Hermes Agency by default | **Not shipped** — follow-up |
| Hermes Agency live multi-process Keryx round trip | Shipped in Agency (`scripts/e2e_agency_keryx.py`); independent of Fabric |

Live Agency dispatch client work is tracked as a follow-up outside
[`docs/plans/2026-07-13-hermes-agency-full-remediation.md`](../../docs/plans/2026-07-13-hermes-agency-full-remediation.md)
workstream F (honesty/CI only in that program).

## Current Hermes Agency context

- Tenant default: `default`
- Team context filter: `agency-only`
- Canonical packaged roster: 83 `agency-*` profiles
- Offline agents remain valid targets: pool/orchestrator routing attempts a wake and can persistently queue work if no peer is available
- Routing should prefer skill fit before direct assignment when possible

## Initial milestones

1. **Own the fork safely**
   - Keep the upstream remote fetchable.
   - Keep upstream push disabled.
   - Preserve MIT attribution.
   - Rebrand in focused passes rather than breaking package/runtime links wholesale.

2. **Agency roster visibility**
   - Surface all 83 packaged `agency-*` profiles regardless of online status.
   - Show skills, descriptions, model/provider, status, last seen, wake attempts, and last error.

3. **Agency task dispatch**
   - Convert a Fabric task into an Agency task packet.
   - Support direct-profile and skill-fit routing.
   - Wire a real authenticated dispatch client to the established Hermes Agency surface.
   - Reflect queued, wake-failed, running, completed, blocked, and failed states into the task thread.

4. **Artifacts and validation**
   - Store returned reports, files, screenshots, diffs, URLs, logs, and validation evidence as first-class work products.

5. **Agency-native governance**
   - Add budget, time, and turn guardrails.
   - Map watchdog and reviewer roles to Agency QA/review profiles.
   - Preserve Hermes Agency trust and approval boundaries. Fabric must not bypass them.

## Non-goals

- Do not make Hermes Fabric a replacement for Hermes Agency.
- Do not move `agency-*` profile source of truth out of Hermes Agency.
- Do not describe dry-run dispatch as live Agency execution.
- Do not hardcode maintainer-local profiles, providers, models, tokens, paths, or credentials into shipped defaults.
- Do not bypass Hermes Agency trust, relay, allowlist, queue, or approval semantics.

## Rename decisions

- **Package namespace:** keep `@hermes-fabric/*` workspace package names temporarily. Rename only after imports, lockfiles, bins, publish metadata, and release tooling can move together.
- **CLI name:** expose `hermes-fabric` and retain `hermes-fabric` as a compatibility alias during migration.
- **Config path:** keep `~/.hermes-fabric` and `HERMES_FABRIC_*` temporarily to preserve existing data. A future migration must copy, verify, and only then deprecate old paths.
- **Docs/assets:** public identity should say Hermes Fabric. Historical docs, release notes, upstream skills, package internals, and legal attribution may retain Hermes Fabric references until their dedicated migration.
