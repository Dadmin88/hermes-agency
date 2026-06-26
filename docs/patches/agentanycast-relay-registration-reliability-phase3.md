# Hermes Agency Relay Registration Reliability — Phase 3 Completion Notes

## Scope

Phase 3 adds compact health output so watchdogs and operators do not need to parse the huge full `a2a_info` / `manager.info()` payload. It also updates the VPS wrapper to use compact health.

## Source changes

Files changed:

- `hermes-agency/node_manager.py`
- `hermes-agency/tools.py`
- `hermes-agency/tests/test_unit.py`

Implemented:

- `NodeManager.compact_info()`
  - returns a small health-only payload
  - excludes full AgentCard data
  - excludes skill lists
  - excludes full team context
  - excludes announcements/task history
- `a2a_info({"compact": true})`
  - returns only top-level status, SDK availability, compact flag, and compact node health
  - does not include `card`
- `A2A_INFO_SCHEMA` now accepts optional `compact: boolean`
- Unit tests for:
  - compact health shape
  - compact payload excludes heavy fields
  - compact payload stays under 2KB
  - `a2a_info({"compact": true})` uses `manager.compact_info()`

## Compact health shape

Example live VPS registration subsection:

```json
{
  "healthy": true,
  "last_registration_time": 1782108510.6329336,
  "consecutive_failures": 0,
  "next_retry_at": 1782108530.982846,
  "loop_running": true,
  "loop_exited": false,
  "healthy_window_seconds": 60,
  "normal_interval_seconds": 20
}
```

Direct runtime compact `a2a_info` validation on VPS:

```text
bytes 702
has_card false
compact true
node_keys: card_name, incoming, node_started, ok, peer_id, registration, serve_task_running, team
```

Direct runtime compact `a2a_info` validation on gpt profile:

```text
bytes 702
has_card false
compact true
node_keys: card_name, incoming, node_started, ok, peer_id, registration, serve_task_running, team
```

## VPS wrapper update

File changed on VPS:

- `~/agency-node.py`

Changes:

- Added `_node_health()` helper.
- Uses `m.compact_info()` when available.
- Falls back to `m.info()` for compatibility.
- Watchdog now reads compact health.
- Alive loop now reads compact health.
- Startup log now prints `a2a_info compact registration` instead of pulling `registry_refresh` out of the full payload.

Backups created on VPS before patching:

- `~/.hermes/plugins/hermes-agency/node_manager.py.bak-phase3-compact-*`
- `~/.hermes/plugins/hermes-agency/tools.py.bak-phase3-compact-*`
- `~/agency-node.py.bak-phase3-compact-*`

## Validation commands run

```bash
cd ~/src/hermes-agentanycast
python3 -m py_compile hermes-agency/node_manager.py hermes-agency/tools.py hermes-agency/tests/test_unit.py
/tmp/hermes-agency-test-venv/bin/python -m pytest hermes-agency/tests/test_unit.py -q
```

Result:

```text
72 passed in 1.10s
```

Runtime syntax checks:

```bash
~/.hermes/profiles/gpt/hermes-agent/venv/bin/python3 -m py_compile \
  ~/.hermes/profiles/gpt/plugins/hermes-agency/node_manager.py \
  ~/.hermes/profiles/gpt/plugins/hermes-agency/tools.py

ssh hermes '~/.hermes/hermes-agent/venv/bin/python3 -m py_compile ~/.hermes/plugins/hermes-agency/node_manager.py ~/.hermes/plugins/hermes-agency/tools.py ~/agency-node.py'
```

## Live VPS validation

After restarting `agency-node.service`:

```text
active
active
VPS node started: 12D3KooWKuxTvp5xsLvkU3KEbJWSdLE4GLE9LAEZV61S5wDXHhAo
Skills: 79
a2a_info compact registration: {"healthy": true, "last_registration_time": 1782108510.6329336, "consecutive_failures": 0, "next_retry_at": 1782108530.982846, "loop_running": true, "loop_exited": false, "healthy_window_seconds": 60, "normal_interval_seconds": 20}
```

Follow-up alive logs confirmed the wrapper is using compact health successfully:

```text
alive: peers=1, incoming=0, serve=True, registration_healthy=True, consecutive_failures=0
```

Discovery still shows expected agents:

```text
local workstation
Hermes (VPS)
gpt
```

Direct task send to VPS completed:

```json
{
  "ok": true,
  "status": "completed",
  "artifact_text": "Hi! I'm Hermes (VPS), running as an Hermes Agency node on this machine.\nI have 79 skills installed."
}
```

## Phase 3 status

Complete.

Notes:

- The current chat's tool schema may not expose `compact` until a fresh Hermes session/tool reload because tool schemas are loaded at session start. The deployed plugin schema now includes it.
- The current `a2a_send` / `a2a_discover` responses still include huge full `node` payloads. Phase 3 only added compact `a2a_info` and updated the VPS wrapper/watchdog. A later phase should consider using compact node payloads in `a2a_send`, `a2a_discover`, and error responses too.
- local workstation's daemon was not restarted.
