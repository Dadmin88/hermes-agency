# Keryx cross-node Agency boundary

Status: **Agency orchestration golden path and Phase 17 live multi-process Keryx round trip are shipped**

Tracking (historical):

- Hermes Keryx: [DeployFaith/hermes-keryx#10](https://github.com/DeployFaith/hermes-keryx/issues/10) (Phase 17 transport contract)
- Hermes Agency integration: [#81](https://github.com/DeployFaith/Hermes_Agency/issues/81) (closed)
- Integration PR: [#85](https://github.com/DeployFaith/Hermes_Agency/pull/85)
- Active remediation: [`docs/plans/2026-07-13-hermes-agency-full-remediation.md`](./plans/2026-07-13-hermes-agency-full-remediation.md)

## What Hermes Agency proves today

### In-process golden path

The permanent test at `hermes-agency/tests/test_golden_path.py` exercises the real Agency module seams and proves:

1. an offline specialist is selected from the persistent roster
2. the wake path is invoked
3. sender and receiver pass the Agency allowlist/trust gates
4. the receiver processes the task through Hermes delegation
5. a completion artifact returns to the sender
6. local orchestrator state becomes `completed`
7. Kanban moves through running to done and pending review
8. when wake fails, the task is durably queued and local/Kanban state reflects that truthfully

This is an **in-process loopback integration proof** using an in-memory transport adapter and board adapter. It proves the Agency workflow seams without requiring live Keryx binaries.

### Live multi-process Keryx round trip (Phase 17)

The permanent live proof is `scripts/e2e_agency_keryx.py`, gated by `.github/workflows/agency-phase17-e2e.yml`. It starts a real Keryx relay/registry, two daemons, two edge nodes, and a Python worker that enters Hermes Agency's production incoming queue. It verifies:

- remote specialist discovery
- authenticated sender trust
- Agency incoming-record completion
- Kanban transition from running to done
- terminal artifact return to the sender
- pending-review reconciliation

The synchronized Keryx Python SDK revision is recorded in `src/keryx/_sync_manifest.json`.

## What Keryx provides

```text
sender SDK
  -> sender keryxd SendTask
  -> relay PublishTask / mailbox
  -> destination keryx-node stream
  -> destination keryxd SubmitTask
  -> claim-next / serve_forever handler dispatch
  -> terminal result / artifact return
  -> TaskHandle.wait() completion
```

Keryx also implements registry discovery, local daemon lifecycle, leases, heartbeats, completion/failure, cancellation, deadlines, artifacts, routing policy, and relay security primitives.

## Claims that remain future-tense

Safe shipped claims:

- Hermes Agency has a proven managed delegation workflow from roster selection through artifact and Kanban reconciliation.
- Offline specialists are valid targets; Agency can attempt wake and persistently queue work.
- Keryx is the primary transport and provides daemon, relay, registry, routing, mailbox, lifecycle, and security foundations.
- A remote Hermes Agency profile can consume a relay-delivered Keryx task through the production incoming path and return a terminal artifact (Phase 17 E2E).
- `TaskHandle.wait()` can observe remote terminal completion in the supported Keryx result protocol.

Claims that must remain future-tense or carefully qualified:

- Hermes Fabric live dispatch to Agency is the **default** operator path (default Fabric client remains unconfigured/dry-run)
- Multi-tenant production SaaS hardening
- Every packaged staff profile is production-proven under live load
- AgentAnycast is a recommended or equal primary transport (it is legacy/fallback only)

## Operator notes

- Dual-run infrastructure health checks (daemon + relay up) are **not** a substitute for the Agency Phase 17 E2E.
- Discovery plus daemon health alone is not proof of handler execution; use `scripts/e2e_agency_keryx.py` or the Phase 17 CI workflow for the full loop.
- Set `agency.transport_backend: agentanycast` only for explicit legacy rollback.
