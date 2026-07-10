# Hermes Agency Hermes Plugin — Phase 8 PR-Prep Notes

> Status: testing only. Do **not** open PRs from this work without explicit maintainer approval.

> Historical note: this file records pre-Keryx PR-prep work. Current Hermes
> Agency docs should describe Keryx as the primary transport, the Keryx Python
> SDK as vendored under `src/keryx/`, and AgentAnycast as legacy/fallback only.

## Phase 8 goal

Prepare the Hermes Agency Hermes plugin for eventual upstream review by tightening docs, tests, dependency gating, license notes, and validation evidence.

This phase is **PR prep**, not PR submission.

## Target contribution shape

The safest eventual shape is an optional Hermes plugin, not a core tool addition:

- Plugin directory: `plugins/hermes-agency/` or equivalent bundled-plugin surface.
- Toolset: `agency`, gated by plugin enablement and SDK availability.
- SDK dependency: supplied by the vendored Keryx Python SDK under `src/keryx/` for this repository/package; still optional at Hermes plugin load time.
- Daemon/relay: external Keryx runtime components, not vendored into Hermes.
- Runtime config: `config.yaml` under `agency.keryx.*`; `HERMES_KERYX_*` / `KERYX_*` are runtime aliases, while `AGENTANYCAST_*` remains legacy fallback only.

## Required docs/AGENTS content

Covered by `hermes-agency/README.md` and `hermes-agency/AGENTS.md`:

- install modes for symlink/copy/future bundled plugin
- full config surface
- tool list including core `a2a_*`, autonomous helpers, and orchestrator-only `orch_*`
- security model for remote tasks
- Keryx relay/registry/daemon endpoint distinction
- vendored Python SDK vs external daemon/relay binaries
- validation commands
- local artifact hygiene
- explicit warning not to open PRs while still testing

## Test coverage checklist

Current unit coverage includes or now asserts:

- AgentCard generation from profile files
- AgentCard secret-safety for config/API-key/channel/path fields
- deterministic skill extraction/deduplication from `skills/**/SKILL.md`
- generic `hermes-chat` capability inclusion
- config defaults and nested overrides
- incoming task modes: safe stub, delegation, subprocess, template fallback
- skill-context injection for incoming target skills
- progress artifacts for incoming tasks when enabled
- tool schema structure
- `a2a_send` argument validation
- compact status/error paths
- team-context peer names/skills/fallbacks/budgeting
- relay registry refresh interval and registration behavior
- plugin registration when disabled: commands/hooks load, model tools do not register, daemon does not start
- plugin registration with SDK absent: tools register behind failing check functions, daemon does not start
- orchestrator tools only appear for the promoted/configured orchestrator profile

## Manual/integration coverage

Current standalone scripts:

```bash
make integration-agency
make integration-agency-full
```

`test_e2e.py` now runs its local SDK nodes with isolated temporary daemon homes and no relay/registry unless explicitly configured through environment variables. `test_e2e_full.py` still exercises real profile/Kanban/relay assumptions, so before upstream CI it should be converted to fixtures/skips or kept as explicit manual validation.

Phase 7 live validation already proved:

- `a2a_discover` found local workstation and remote agency host through the registry
- remote agent → local workstation completed with artifact text
- remote agent → remote agency host completed with artifact text
- isolated temp sender → remote agent completed with artifact text
- Kanban tasks reconciled to `done`
- VPS node and relay systemd services stayed active with `NRestarts=0`
- gateway logs had no Discord `No home channel` warnings during validation

## License / dependency notes

- Repository and Python SDK: Apache-2.0.
- Hermes upstream: MIT; if upstreaming, maintainers need an explicit compatibility/dual-license decision for plugin code.
- Daemon/relay: external runtime components with their own license; do not vendor binaries.
- Python dependency risk: SDK requires `protobuf>=7.34.1`; Hermes environments need compatible `googleapis-common-protos>=1.74.0` or an optional extra that isolates this dependency.
- `pip check` should be included in every validation report.

## Current validation evidence

Last local validation command set:

```bash
make test-agency
# 87 passed

make integration-agency
# PASS: Scenario A: Node lifecycle
# PASS: Scenario B: a2a_list_peers both directions
# PASS: Scenario B: Self-send (two localhost nodes)
# PASS: Scenario C: Error handling
# PASS: Scenario D: Incoming task queue
# All scenarios passed

make lint-agency
# All checks passed!

python -m pip check
# No broken requirements found.
```

Verification matrix results:

```json
{
  "plugin_absent": {"ok": true, "tool_count": 0},
  "plugin_disabled": {"ok": true, "start_calls": 0, "tool_count": 0},
  "sdk_absent": {"ok": true, "start_calls": 0, "tool_count": 14},
  "sdk_present": {"ok": true, "has_agency_sdk": true, "start_calls": 0, "tool_count": 14}
}
```

Note: the SDK-absent row intentionally registers tools behind failing `check_fn` gates and does not autostart the daemon. That is the current Hermes plugin pattern for fail-open plugin loading; unavailable tools should not be exposed to model execution.

## PR description draft for later

Do not submit this yet.

```markdown
## Summary

Adds an optional Hermes Agency Hermes plugin for P2P agent-to-agent communication between Hermes profiles.

Capabilities:
- per-profile AgentCard generation from SOUL.md + installed skills
- per-profile Hermes Agency node lifecycle
- peer discovery by skill
- direct A2A task send/status/inbox tools
- incoming task safe-stub/delegation/subprocess processing modes
- compact team-context injection
- Kanban task tracking/reconciliation
- optional orchestrator and autonomous collaboration tools

## Safety / footprint

- Plugin is opt-in through `plugins.enabled`.
- Hermes Agency SDK is optional; plugin load is fail-open when SDK is absent.
- Daemon/relay binaries are external runtime dependencies and are not vendored.
- Remote execution defaults to safe behavior (`allow_remote_tasks: false`, `incoming.tool_access: safe`).
- AgentCards expose only non-secret metadata.

## Validation

```bash
python -m pytest hermes-agency/tests/test_unit.py -q
python -m py_compile hermes-agency/*.py
python -m pip check
```

Manual/live validation also exercised local and cross-network A2A task completion with non-empty artifact return and Kanban reconciliation.

## Notes for reviewers

- Keryx relay, registry, and daemon endpoints are configured under `agency.keryx.*` or `HERMES_KERYX_*` / `KERYX_*`; legacy `agency.relay` and `AGENTANYCAST_REGISTRY_ADDRS` are rollback-only settings.
- The daemon's task lifecycle requires `SUBMITTED -> WORKING -> COMPLETED`.
- The artifact propagation regression is covered by integration/manual validation and should become an isolated CI test before merge.
```

## Remaining blockers before any upstream PR

- Convert standalone e2e scripts away from developer-specific profile/relay assumptions.
- Decide plugin code license/dual-license story for Hermes MIT upstream.
- Decide dependency packaging: optional extra vs bundled plugin dependency metadata.
- Add or adapt Hermes-core tests if moving from user plugin to bundled plugin.
- Re-run a clean fresh-venv install + `pip check` before proposing upstream.
- Run the exact upstream Hermes lint/format target after the bundled-plugin layout is chosen; current Phase 8 validation proves syntax plus `ruff --select F`, but full line-length/style cleanup may still be required by upstream CI.
- Get explicit maintainer approval before opening any PR.
