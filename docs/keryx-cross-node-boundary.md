# Keryx cross-node Agency boundary

Status: **the Agency orchestration golden path is proven; the complete remote Keryx round trip is Phase 17 work**

Tracking:

- Hermes Keryx: [DeployFaith/hermes-keryx#10](https://github.com/DeployFaith/hermes-keryx/issues/10)
- Hermes Agency integration: [#81](https://github.com/DeployFaith/Hermes_Agency/issues/81)

## What Hermes Agency proves today

The permanent test at `hermes-agency/tests/test_golden_path.py` exercises the real Agency module seams and proves:

1. an offline specialist is selected from the persistent roster
2. the wake path is invoked
3. sender and receiver pass the Agency allowlist/trust gates
4. the receiver processes the task through Hermes delegation
5. a completion artifact returns to the sender
6. local orchestrator state becomes `completed`
7. Kanban moves through running to done and pending review
8. when wake fails, the task is durably queued and local/Kanban state reflects that truthfully

This is an **in-process loopback integration proof**. It uses the real Agency routing, trust, incoming-worker, delegation, artifact, orchestrator-state, and Kanban reconciliation code, with an in-memory transport adapter and board adapter.

It proves the Agency workflow. It does not claim a live multi-process Keryx network round trip.

## What Keryx proves today

The current Keryx source implements the one-way transport foundation:

```text
sender SDK
  -> sender keryxd SendTask
  -> relay PublishTask / mailbox
  -> destination keryx-node stream
  -> destination keryxd SubmitTask
  -> destination lifecycle row
```

It also implements registry discovery, local daemon lifecycle, leases, heartbeats, completion/failure, cancellation, deadlines, artifacts, routing policy, and relay security primitives.

## What remains for a complete remote Agency round trip

The current destination daemon stores a lifecycle record but does not durably retain enough of the submitted envelope for an Agency worker to reconstruct the prompt and context. There is no atomic claim-next/envelope-delivery API for a receiver worker. The Python SDK `serve_forever()` does not consume daemon work or invoke registered handlers. Terminal results and artifacts do not route back to the origin, and the compatibility `TaskHandle` is not connected to a remote status/result stream.

Phase 17 must therefore add:

- durable full-envelope inbox persistence
- an atomic, lease-aware claim-next worker API
- daemon-backed Python incoming-handler dispatch
- transport-authenticated sender identity
- terminal result and artifact routing to the origin
- a remotely updated `TaskHandle.wait()`
- a repeatable relay + two-daemon + two-edge-node E2E harness

## Communication rules until Phase 17 is complete

Safe current claims:

- Hermes Agency has a proven managed delegation workflow from roster selection through artifact and Kanban reconciliation.
- Offline specialists are valid targets; Agency can attempt wake and persistently queue work.
- Keryx is the primary transport and provides daemon, relay, registry, routing, mailbox, lifecycle, and security foundations.
- Keryx can publish a task through the relay and submit it into a destination daemon.

Claims that must remain future-tense:

- a remote Hermes Agency profile automatically consumes a relay-delivered Keryx task
- the remote specialist completes the task and sends its artifact back over Keryx
- `TaskHandle.wait()` follows a remote task to terminal completion
- the full cross-machine Agency loop is production-proven

## Release gate

The remote round trip becomes a shipped claim only when the cross-process E2E proves:

- receiver skill registration and sender discovery
- relay-backed remote delivery
- durable receiver claim and handler invocation
- terminal result/artifact return to the sender
- restart recovery before claim
- failure and cancellation propagation
- sender identity that cannot be spoofed through arbitrary task metadata
