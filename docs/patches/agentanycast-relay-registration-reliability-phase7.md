# Hermes Agency Relay Registration Reliability — Phase 7 Completion Notes

## Scope

Phase 7 finishes compacting routine Hermes Agency model-tool responses that still used the full `manager.info()` payload.

Previous phases handled:

- Phase 3: compact `a2a_info({"compact": true})` and watchdog health paths
- Phase 5: compact `a2a_send` and `a2a_discover`
- Phase 6: bound injected team-context prompt size

Phase 7 covers the remaining routine tools:

- `a2a_list_peers`
- `a2a_status`
- `a2a_inbox`
- `a2a_start_node` exception path
- `a2a_stop_node` exception path

The explicit full `a2a_info()` path remains available for troubleshooting. The compact health path remains `a2a_info({"compact": true})`.

## Source changes

Files changed:

- `hermes-agency/tools.py`
- `hermes-agency/tests/test_unit.py`

Implemented:

- `a2a_list_peers(...)` now returns `_compact_node()` on success and errors.
- `a2a_status(...)` now returns `_compact_node()` on:
  - missing `task_id` validation errors
  - unknown task errors
  - success
  - exceptions
- `a2a_inbox(...)` now returns `_compact_node()` on success and errors.
- `a2a_start_node(...)` and `a2a_stop_node(...)` now return `_compact_node()` on exception paths instead of full `manager.info()`.

Remaining `manager.info()` calls in `tools.py` are now limited to:

- `_compact_node()` fallback for compatibility when a manager lacks `compact_info()`
- explicit full `a2a_info()` troubleshooting output

## Tests added/updated

Updated:

- `test_a2a_status_requires_task_id`
  - now expects compact node payload instead of full state

Added:

- `test_routine_tools_use_compact_node_payloads`
  - proves `a2a_list_peers`, `a2a_status`, and `a2a_inbox` do not call full `manager.info()`
  - validates success, validation, and unknown-task paths
  - checks representative combined payload stays under 2KB
- `test_lifecycle_tool_errors_use_compact_node_payloads`
  - proves `a2a_start_node` and `a2a_stop_node` exception paths do not call full `manager.info()`

## RED/GREEN evidence

The new tests failed first because the tools still called full `manager.info()`:

```text
3 failed
AssertionError: routine tools should not use full manager.info()
AssertionError: lifecycle error paths should not use full manager.info()
```

After implementation, targeted tests passed:

```text
3 passed in 0.05s
```

Full unit suite passed:

```text
79 passed in 1.14s
```

## Validation commands

```bash
cd ~/src/hermes-agentanycast
python3 -m py_compile hermes-agency/tools.py hermes-agency/tests/test_unit.py
/tmp/hermes-agency-test-venv/bin/python -m pytest hermes-agency/tests/test_unit.py -q
```

Result:

```text
79 passed in 1.14s
```

Confirmed only intentional full-info references remain:

```text
_compact_node() fallback: return manager.info()
a2a_info() explicit full path: "node": manager.info()
```

## Runtime deployment

### gpt profile

The active gpt plugin path resolves to the source tree/fresh plugin files:

```text
~/.hermes/profiles/<profile>/plugins/hermes-agency/tools.py
```

Runtime syntax check passed:

```bash
~/.hermes/profiles/<profile>/hermes-agent/venv/bin/python3 -m py_compile \
  ~/.hermes/profiles/<profile>/plugins/hermes-agency/tools.py
```

Direct runtime verification passed using the gpt profile plugin package.

### VPS profile

Deployed to:

```text
/home/dadmin/.hermes/plugins/hermes-agency/tools.py
```

Backup created:

```text
/home/dadmin/.hermes/plugins/hermes-agency/tools.py.bak-phase7-routine-compact-*
```

Runtime syntax check passed:

```bash
ssh hermes '~/.hermes/hermes-agent/venv/bin/python3 -m py_compile ~/.hermes/plugins/hermes-agency/tools.py'
```

Direct runtime verification passed using the VPS plugin package.

## Direct runtime verification

A fake manager whose `info()` raises was injected into both local and VPS runtime plugin imports. The following tools all completed without calling `info()`:

- `a2a_list_peers`
- `a2a_status` validation path
- `a2a_status` unknown-task path
- `a2a_status` success path
- `a2a_inbox`
- `a2a_start_node` exception path
- `a2a_stop_node` exception path

Representative output sizes:

```text
list_peers: 164 bytes
status_validation: 124 bytes
status_missing: 151 bytes
status_success: 191 bytes
inbox: 172 bytes
start_error: 129 bytes
stop_error: 128 bytes
```

Each response included compact node health:

```json
{
  "ok": true,
  "node_started": true,
  "registration": {
    "healthy": true
  }
}
```

## Live health after deployment

VPS services remained active:

```text
agency-node.service: active
agency-relay.service: active
```

VPS-local watchdog passed:

```text
agency-health-watchdog: OK actions=none healthy=True consecutive_failures=0 agencyd=1 wrapper=1
```

Outside-in watchdog passed:

```text
agency-outside-in-watchdog: OK target=Hermes (VPS) peer_id=12D3KooWKuxTvp5xsLvkU3KEbJWSdLE4GLE9LAEZV61S5wDXHhAo task_id=d7e9e8f5-869b-4a50-99d2-e96ee8604e39 elapsed=0.5s artifact="Hi! I'm Hermes (VPS), running as an Hermes Agency node on this machine.\nI have 79 skills installed."
```

## Phase 7 status

Complete.

Notes:

- I did not restart the VPS node because Phase 7 only changes Hermes model-tool response formatting in `tools.py`; the standalone VPS node wrapper does not need to import the updated tool handler for relay health.
- I did not restart Katana or the local gpt GUI/session.
- Fresh Hermes sessions will pick up the updated tool handlers. The current chat may still have stale tool handlers until session/tool reload.
