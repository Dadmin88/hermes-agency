# Hermes Agency QA validation ladder

Status: active QA policy for this repository.

This document defines the validation truth table for Hermes Agency so contributors, reviewers, and release operators can say exactly what a green run proves and what it does not prove.

Core rule: default green CI proves the in-repo seam and workflow checks that actually ran. It must not be described as proving live daemon, live relay, or cross-machine remote-execution behavior unless the corresponding higher validation rung also ran and passed.

## Validation truth table

| Mode | Typical entry points | What it proves | What it does not prove | Prerequisites | Cost / risk | When it is required |
|---|---|---|---|---|---|---|
| Mocked and in-process seam tests | `ruff check .`, `ruff format --check .`, `make test-agency`, targeted `pytest` under `hermes-agency/tests/` | Core Agency logic, routing decisions, config handling, secret-safety, model/tool registration, and the permanent golden-path workflow proof using in-process loopback adapters. Confirms that the repository's default CI gate is green. | Live daemon health, live registry/relay wiring, Docker packaging, real profile homes, or cross-machine Keryx round trips. A green result here does not prove remote handler execution over a live network. | Python environment and repo checkout only. No real Hermes homes, daemons, relays, or Docker topology required. | Lowest cost, lowest operational risk, fastest signal. Safe for routine CI and pre-commit work. | Required for every code or doc change that affects behavior or contributor/operator guidance. This is the default green gate. |
| Local-daemon localhost integration | `make integration-agency` / `python3 hermes-agency/tests/test_e2e.py` | Real local daemon/node startup, localhost peer discovery/communication paths, and the lightweight standalone integration harness using isolated daemon homes. Validates that the code can exercise real runtime processes on one machine without accidentally depending on a developer's live relay or registry. | Docker packaging, real profile/Kanban assumptions, or a remote multi-process Keryx round trip. Does not prove cross-network delivery or remote artifact return. | Local Keryx-compatible runtime available to the script, ports free, host allows local process startup. | Moderate cost, moderate flake risk from local runtime/process state. Higher than default CI but still developer-friendly. | Required before merging changes that touch daemon lifecycle, local node wiring, discovery, or other runtime behavior that mocked tests cannot fully cover. |
| Docker integration | `docker compose up --build`, `docker compose --profile tools run --rm setup`, and related headless runtime checks | The packaged image, compose wiring, setup flow, and headless node runtime start correctly in the supported container path. Validates operator-facing packaging and bootstrapping assumptions. | Real profile behavior outside the container, manual reviewer workflows, or live cross-machine Keryx execution/result return. Unless an explicit remote gate is added on top, Docker green does not prove full remote Agency delivery. | Docker/Compose installed, image build works, enough local resources for containers. | Moderate-to-high cost, slower feedback, packaging/environment risk. | Required for Dockerfile, compose, setup, packaging, or runtime bootstrap changes. Recommended before release candidates that advertise Docker usage. |
| Real-profile manual validation | Explicit operator-run checks against real Hermes profiles, real Kanban wiring, and real local environment; typically a curated checklist rather than a single make target | Operator-facing behavior with the actual profile layout, Hermes plugin loading, real Kanban/Fabric trace surfaces, and human-observed workflow correctness. Useful for validating claims about real profile installs, review flows, and end-user operations. | A portable CI guarantee. Results may depend on the operator environment and should not be generalized to all installs. Also does not by itself prove live cross-machine Keryx E2E unless that exact remote topology was exercised. | Explicit operator authorization, accessible real profiles, and a known-safe environment. | High cost, high human time, higher risk of environment-specific false confidence if notes are not captured carefully. | Required before shipping claims about real profile UX/ops, release procedures, or Kanban/Fabric reconciliation behavior that only exists in a live operator environment. |
| Opt-in live Keryx E2E | Explicitly authorized, phase-gated live relay + daemon + edge-node validation across the intended topology | The highest-confidence proof: real discovery, live relay-backed delivery, durable receiver claim/handler execution, terminal result/artifact return, and the exact cross-process or cross-machine Keryx behavior that shipped claims depend on. | This remains optional and phase-gated until the missing Phase 17 pieces are implemented. A pass here should not be backported into claims about older commits or CI runs that did not execute the same gate. | Explicit authorization, live Keryx infrastructure, safe test identities, and a controlled environment for remote execution. | Highest cost and highest operational/security risk. Most realistic signal, but must stay rare and intentional. | Required only for changes or release claims that depend on live remote Keryx round-trip behavior. It must remain opt-in, never silently folded into default CI. |

## Validation ladder

1. Start with mocked and in-process seam tests for every change.
2. Add local-daemon localhost integration when runtime process or local transport behavior changed.
3. Add Docker integration when packaging, compose wiring, or container startup changed.
4. Add real-profile manual validation when the claim involves real Hermes profile behavior, Kanban/Fabric traceability, or operator workflows.
5. Add opt-in live Keryx E2E only when the change or release claim depends on actual remote round-trip behavior.

The ladder is cumulative. Running a higher rung does not erase the need for the lower deterministic checks; it supplements them with a stronger environment proof.

## Naming and reporting rules

- Say "default green CI" only for the mocked/in-process seam-test rung unless additional gates actually ran.
- Say "local-daemon validated" only when the localhost integration harness ran.
- Say "Docker validated" only when the container path ran.
- Say "real-profile/manual validated" only when an operator actually performed and recorded those checks.
- Say "live Keryx E2E validated" only when the explicit opt-in live gate ran against the intended topology.
- Never collapse these labels into a single generic "E2E passed" claim.

## Release and end-of-shift mapping

| Situation | Minimum validation evidence | Notes |
|---|---|---|
| End of shift after doc-only or low-risk logic work | Default green CI, plus notes naming any higher rungs intentionally skipped | Good default for routine progress reports. Must explicitly avoid implying live runtime proof. |
| End of shift after runtime/daemon/local transport changes | Default green CI + local-daemon localhost integration | Add Docker integration too if packaging or bootstrap files changed. |
| End of shift after Docker/setup changes | Default green CI + Docker integration | Add local-daemon localhost integration when the change also affects daemon behavior outside containers. |
| Release candidate for operator-facing workflow changes | Default green CI + the relevant higher rungs for the changed surfaces + real-profile manual validation | The report should enumerate which claims are backed by which rung. |
| Release claim that mentions live remote Keryx round trips | All lower relevant rungs + explicit opt-in live Keryx E2E | Without the live gate, the release report must keep remote round-trip language future-tense. |

## Recommended report fields

Future release or end-of-shift reports should capture at least:

- change scope
- validation modes run
- exact commands/checklists used
- pass/fail outcome per mode
- environment notes or prerequisites used
- claims that remain unproven because a higher rung did not run

This keeps status reports honest and makes it easy to feed a future single report target without overstating confidence.