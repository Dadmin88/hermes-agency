# Hermes Agency Relay Registration Reliability — Phase 5 Completion Notes

## Scope

Phase 5 reduces high-volume Hermes Agency model-tool output so normal `a2a_discover` and `a2a_send` calls do not return huge full node/task-context payloads.

This phase addresses the Phase 3 note:

> The current `a2a_send` / `a2a_discover` responses still include huge full `node` payloads. A later phase should consider using compact node payloads in `a2a_send`, `a2a_discover`, and error responses too.

## Source changes

Files changed:

- `hermes-agency/tools.py`
- `hermes-agency/tests/test_unit.py`

Implemented:

- `_compact_node()` helper
  - uses `manager.compact_info()` when available
  - falls back to `manager.info()` only when compact info is absent
- `a2a_discover(...)` now uses compact node payloads on:
  - validation errors
  - success
  - exception/error responses
- `a2a_send(...)` now uses compact node payloads on:
  - validation errors
  - success
  - exception/error responses
- `a2a_discover(...)` now compacts discovered agents by default:
  - keeps `peer_id`
  - keeps `agent_name`
  - keeps `agent_description`
  - adds `skill_count`
  - adds up to 5 `matching_skills`
  - omits full `skills` lists by default
- `a2a_discover` schema now has optional `include_skills: boolean`
  - default false keeps output compact
  - true restores full per-agent skill lists when explicitly needed

## Tests added/updated

Added regression tests for:

- `a2a_discover` success uses compact node payload
- `a2a_discover` validation errors use compact node payload
- `a2a_discover` default response omits full agent skill lists
- `a2a_send` validation and success responses use compact node payload
- compact send/discover responses stay under 2KB for representative fake payloads

Updated older `a2a_send` validation test expectations from full `manager.info()` to compact node health.

## RED/GREEN evidence

New tests initially failed because `a2a_discover` and `a2a_send` still called `manager.info()` and returned full agents:

```text
3 failed
AssertionError: a2a_discover should not use full manager.info()
AssertionError: validation errors should not use full manager.info()
AssertionError: a2a_send should not use full manager.info()
```

After implementing compact node handling, the targeted tests passed:

```text
3 passed in 0.05s
```

After adding compact agent output, the targeted discover test first failed because the full `skills` list was still present, then passed after implementing `_compact_agent()` / `_compact_agents()`.

## Full validation

Command:

```bash
cd ~/src/hermes-agentanycast
python3 -m py_compile hermes-agency/tools.py hermes-agency/tests/test_unit.py
/tmp/hermes-agency-test-venv/bin/python -m pytest hermes-agency/tests/test_unit.py -q
```

Result:

```text
75 passed in 1.15s
```

## Runtime deployment

### gpt profile

The active gpt profile plugin path is the source file itself:

```text
~/.hermes/profiles/<profile>/plugins/hermes-agency/tools.py -> ~/src/hermes-agentanycast/hermes-agency/tools.py
```

Runtime syntax check:

```bash
~/.hermes/profiles/<profile>/hermes-agent/venv/bin/python3 -m py_compile \
  ~/.hermes/profiles/<profile>/plugins/hermes-agency/tools.py
```

Result: passed.

### VPS profile

Deployed to:

```text
~/.hermes/plugins/hermes-agency/tools.py
```

Backup created before replacement:

```text
~/.hermes/plugins/hermes-agency/tools.py.bak-phase5-compact-tools-*
```

Runtime syntax check:

```bash
ssh hermes '~/.hermes/hermes-agent/venv/bin/python3 -m py_compile ~/.hermes/plugins/hermes-agency/tools.py'
```

Result: passed.

## Payload-size verification

A direct import verification with a fake manager returning 101 skills confirmed the new compact defaults on both local and VPS runtime plugin files.

Representative output:

```json
{
  "discover_bytes": 295,
  "discover_has_full_skills": false,
  "discover_skill_count": 101,
  "send_bytes": 191,
  "send_node": {
    "node_started": true,
    "ok": true,
    "registration": {
      "healthy": true
    }
  },
  "validation_node": {
    "node_started": true,
    "ok": true,
    "registration": {
      "healthy": true
    }
  }
}
```

## Live service status after deployment

VPS remained healthy:

```text
agency-node.service: active
agency-relay.service: active
agency-health-watchdog.timer: enabled
agency-health-watchdog: OK actions=none healthy=True consecutive_failures=0 agencyd=1 wrapper=1
```

Local outside-in watchdog remained enabled and recently successful:

```text
agency-outside-in-watchdog.timer: enabled
agency-outside-in-watchdog: OK target=Hermes (VPS) peer_id=12D3KooWKuxTvp5xsLvkU3KEbJWSdLE4GLE9LAEZV61S5wDXHhAo ... artifact="Hi! I'm Hermes (VPS), running as an Hermes Agency node on this machine.\nI have 79 skills installed."
```

## Phase 5 status

Complete.

Notes:

- The current Hermes chat session still has stale tool handlers/schemas loaded, so a direct `a2a_discover` call from this same session can still show the old large response until a fresh Hermes session/tool reload. The deployed plugin files are patched and verified for future sessions.
- I did not restart local workstation or gpt profile daemons.
- I did not restart the VPS node; this phase only changed model-tool response formatting and does not affect the long-running VPS wrapper.
