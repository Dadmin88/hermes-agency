# P0 Product Truth and Keryx Alignment

Date: 2026-07-10
Branch: `fix/p0-product-truth-keryx-alignment`
Baseline: `main` after the July 10 security merges

## Objective

Make Hermes Agency's runtime behavior, package metadata, contributor guidance, tests, and public product language describe the same system.

The canonical product model is:

- Hermes Agent is the execution engine and profile runtime.
- Hermes Agency is the managed multi-agent workforce and operations layer.
- Keryx is the primary production transport.
- AgentAnycast is a legacy compatibility path only.
- Hermes Fabric is the separate persistent operator interface for Hermes Agency.

## Verified project shape

### Core Hermes Agency plugin

The Python plugin owns:

- plugin, CLI, and slash-command registration
- profile-safe AgentCard construction
- per-profile node lifecycle
- incoming queue persistence and processing
- sender trust and allowlist enforcement
- task send, status, inbox, discovery, and registration tools
- team discovery and bounded context injection
- orchestrator routing, decomposition, escalation, and task state
- Kanban bridging and synchronization
- wake/sleep pool behavior and persistent offline queueing
- Model Sets and native Hermes MoA policy integration
- optional autonomy, bidding, proactive-task, workflow, and learning helpers

### Default workforce

`hermes-agency/default_staff/manifest.json` is the canonical packaged staff registry and currently declares 83 profiles.

The pool runtime uses `hermes-agency/pool/registry_definition.json` as its static capability roster, then overlays volatile peer ID, online, wake, error, and last-seen state.

### Hermes Fabric

Fabric is a Paperclip-derived Node/React application. It currently has real Agency-specific roster, task-packet, dispatch-record, API, and UI surfaces.

The current default dispatch client is not a live Hermes Agency client. It is either unconfigured or dry-run gated. Public claims must distinguish the implemented operator flow from live end-to-end dispatch.

## P0 findings

### P0-1: Documented Keryx default does not match config default

Public and contributor documentation says `agency.transport_backend: keryx` is primary/default.

The current config dataclass, config resolver, tool resolver, node resolver, pool manager, and roster helpers still use `agentanycast` when no explicit setting exists.

Required resolution:

- make `keryx` the single default at every config boundary
- preserve explicit `agentanycast` selection for legacy deployments
- reject or clearly report unsupported backend names
- add regression tests for absent, explicit Keryx, explicit AgentAnycast, alias, and invalid values

### P0-2: AgentAnycast fallback resolver is mislabeled

The current node-class resolver returns `KeryxNode` even when it reports the effective backend as `agentanycast`.

Required resolution:

- either restore a genuine AgentAnycast node-class import for explicit legacy mode
- or remove the runtime fallback claim and state that AgentAnycast source is retained for compatibility/security maintenance only
- never report an effective backend different from the node implementation actually selected

### P0-3: Package metadata is stale

The package description said the product was built on the AgentAnycast Python SDK and used inconsistent public positioning.

Resolution in this branch:

- describe Hermes Agency as managed multi-agent operations for Hermes Agent
- describe the 83-profile roster, routing, Kanban, Model Sets, and Keryx transport

### P0-4: Staff count disagreement

The canonical manifest declares 83 profiles while the staff README claimed 84.

Resolution in this branch:

- make 83 the public count
- name the manifest as canonical
- avoid hand-maintained category subtotals unless they are generated or validated

### P0-5: CI did not exercise the primary transport suite

The root workflow ran only the core unit file, skipped the Keryx transport suite and Model Set suite, invoked `pip-audit` twice, and uploaded Codecov data without producing a coverage file.

Resolution in this branch:

- make `make test-agency` include unit, Model Set, extended-status, and Keryx transport tests
- run that target on Python 3.11, 3.12, and 3.13
- remove the duplicate audit command
- remove the misleading empty coverage upload
- keep the AgentAnycast SDK test exclusion explicit until that legacy package imports cleanly

### P0-6: Fabric documentation mixed current and future state

Fabric documentation described the intended operator platform without consistently identifying which integration seams were live, dry-run, or planned.

Resolution in this branch:

- describe the current roster and dispatch-record surfaces
- explicitly state that the default dispatch client is unconfigured/dry-run
- reserve end-to-end live dispatch claims until a real client is wired
- align transport language with Keryx-first Agency

### P0-7: Stale comments and maintainer-local guidance remain

Examples include:

- orchestrator comments describing Kanban as future while the module actively writes Kanban tasks
- pool comments tied to a specific VPS environment
- Fabric contributor notes tied to an inherited personal fork/branch and machine-specific behavior
- legacy transport terminology in docs and comments

Required resolution:

- remove or rewrite stale implementation-phase comments
- move historical fork notes to clearly marked archival documentation when still useful
- keep contributor guidance portable and product-owned

## Implementation order

### Slice A: metadata and verification

- [x] Create P0 branch from current `main`
- [x] Align package description
- [x] Make the 83-profile manifest canonical in staff docs
- [x] Align Fabric's product/transport/current-state document
- [x] Add Keryx and Model Set tests to the standard Agency test target
- [x] Remove duplicate `pip-audit`
- [x] Remove misleading Codecov upload without coverage generation

### Slice B: runtime transport truth

- [x] Change the config default to `keryx`
- [x] Change tools, node manager, pool, and roster fallbacks to `keryx`
- [x] Restore a genuine explicit AgentAnycast node-class path or remove the runtime fallback claim
- [x] Ensure configured and effective backend reporting is truthful
- [x] Add transport-default and resolver regression tests
- [ ] Run the full Agency test target on all supported Python versions

### Slice C: stale implementation language

- [ ] Update orchestrator module header
- [ ] Remove maintainer-local/VPS assumptions from pool comments
- [ ] Rewrite Fabric contributor guidance around the current Hermes Agency fork
- [ ] Audit public docs for `AgentAnycast`, `83`, `84`, `Paperclip`, `control plane`, and live-dispatch claims
- [ ] Update changelog with the Keryx-default behavior change

### Slice D: golden-path proof

- [ ] Start the configured orchestrator node
- [ ] Route a harmless task by explicit specialist and by skill
- [ ] Demonstrate offline wake or persistent queue behavior
- [ ] Verify incoming trust enforcement
- [ ] Return a completion artifact/status
- [ ] Confirm Kanban reconciliation
- [ ] Capture CLI/log evidence suitable for documentation and X posts

### Slice E: Fabric live bridge

- [ ] Define the authenticated server-to-Agency client contract
- [ ] Implement live direct-agent dispatch
- [ ] Implement live skill-fit dispatch
- [ ] Poll or subscribe to real task status
- [ ] persist artifacts/status into Fabric's task thread/work products
- [ ] retain dry-run as an explicit demo/development mode

## Claim ledger for public communication

| Claim | Status at audit | Requirement before posting |
|---|---|---|
| Hermes Agency packages 83 specialists | Verified by manifest | Keep manifest and docs synchronized |
| Keryx is the primary transport | Product intent and most docs agree; default behavior still mismatched | Merge Slice B and run tests |
| AgentAnycast is a working fallback | Not currently proven by resolver inspection | Restore and test a real path or weaken claim |
| Offline specialists can be queued | Implemented in orchestrator/pool paths | Capture a golden-path run |
| Incoming tasks are trust-gated | Implemented | Capture tests or runtime evidence |
| Model Sets apply strategy across staff | Implemented and documented | Show plan/apply/backup evidence |
| Fabric can show the Agency roster | Implemented | Capture current UI screenshot/video |
| Fabric can dispatch live Agency work | Service seam exists; default client is unconfigured/dry-run | Complete Slice E |
| The project is production hardened | Not an appropriate current claim | Establish release criteria and broader integration evidence |

## Definition of done

This P0 effort is complete when:

1. An installation with no explicit transport setting resolves to Keryx.
2. Explicit AgentAnycast mode either selects real AgentAnycast implementation or is no longer described as a runtime fallback.
3. Status and diagnostics report the implementation actually in use.
4. Package metadata, READMEs, contributor docs, and Fabric docs use the canonical product model.
5. The standard Agency CI target includes Keryx and Model Set coverage.
6. The 83-profile count has one machine-readable source of truth.
7. A harmless end-to-end core delegation run has inspectable evidence.
8. Fabric's live-dispatch status is represented accurately.
