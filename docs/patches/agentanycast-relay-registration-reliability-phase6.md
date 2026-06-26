# Hermes Agency Relay Registration Reliability — Phase 6 Completion Notes

## Scope

Phase 6 bounds the injected Hermes Agency team context so peer discovery cannot bloat every model turn.

This is separate from Phase 5 tool-output compaction. Phase 5 reduced `a2a_send` / `a2a_discover` responses. Phase 6 reduces the `pre_llm_call` team-context block that appears in prompts.

## Source changes

Files changed:

- `hermes-agency/config.py`
- `hermes-agency/team_context.py`
- `hermes-agency/tests/test_unit.py`

Implemented new team-context budget config:

```yaml
agency:
  team:
    max_context_peers: 5
    max_context_skills: 5
    context_max_chars: 4000
```

Defaults preserve the current compact behavior for small teams while preventing runaway prompt growth.

## Rendering behavior

`build_team_context(...)` now:

- sorts peers by display name
- renders at most `max_context_peers`
- renders at most `max_context_skills` per peer
- appends a per-peer omitted-skills count when more skills exist
- appends an omitted-peer hint when more peers exist
- hard-caps the final context block at `context_max_chars`
- uses an ellipsis when hard truncation occurs

Example omitted-peer line:

```text
2 more teammate agent(s) omitted from this compact prompt context. Use a2a_discover for the full live directory.
```

Example omitted-skills suffix:

```text
… (+3 more)
```

## Tests added

Added tests for:

- peer limit enforcement
- skill limit enforcement
- omitted-peer hint
- final character budget enforcement
- ellipsis suffix on truncation
- config parsing for the new limits

## RED/GREEN evidence

The new tests failed first because `TeamConfig` did not yet support the budget fields:

```text
TypeError: TeamConfig.__init__() got an unexpected keyword argument 'max_context_peers'
TypeError: TeamConfig.__init__() got an unexpected keyword argument 'context_max_chars'
```

After implementation, targeted tests passed:

```text
2 passed in 0.04s
```

Full unit suite passed:

```text
77 passed in 1.14s
```

## Validation commands

```bash
cd ~/src/hermes-agentanycast
python3 -m py_compile hermes-agency/config.py hermes-agency/team_context.py hermes-agency/tests/test_unit.py
/tmp/hermes-agency-test-venv/bin/python -m pytest hermes-agency/tests/test_unit.py -q
```

Result:

```text
77 passed in 1.14s
```

## Runtime deployment

### gpt profile

The active gpt plugin path resolves to the source tree, so source changes are already visible for future fresh Hermes plugin loads:

```text
~/.hermes/profiles/<profile>/plugins/hermes-agency/config.py
~/.hermes/profiles/<profile>/plugins/hermes-agency/team_context.py
```

Runtime syntax check passed:

```bash
~/.hermes/profiles/<profile>/hermes-agent/venv/bin/python3 -m py_compile \
  ~/.hermes/profiles/<profile>/plugins/hermes-agency/config.py \
  ~/.hermes/profiles/<profile>/plugins/hermes-agency/team_context.py
```

### VPS profile

Deployed to:

```text
~/.hermes/plugins/hermes-agency/config.py
~/.hermes/plugins/hermes-agency/team_context.py
```

Backups created:

```text
~/.hermes/plugins/hermes-agency/config.py.bak-phase6-team-context-budget-*
~/.hermes/plugins/hermes-agency/team_context.py.bak-phase6-team-context-budget-*
```

Runtime syntax check passed:

```bash
ssh hermes '~/.hermes/hermes-agent/venv/bin/python3 -m py_compile ~/.hermes/plugins/hermes-agency/config.py ~/.hermes/plugins/hermes-agency/team_context.py'
```

The VPS node wrapper was restarted so the long-running Python process imports the updated `team_context.py` and `config.py`:

```text
agency-node.service: active
agency-relay.service: active
VPS node started: 12D3KooWKuxTvp5xsLvkU3KEbJWSdLE4GLE9LAEZV61S5wDXHhAo
a2a_info compact registration: {"healthy": true, "consecutive_failures": 0, "loop_running": true, "loop_exited": false, ...}
```

## Direct runtime verification

A direct import verification on both local gpt plugin files and VPS plugin files used 7 fake peers with 6 skills each and config:

```python
TeamConfig(max_context_peers=3, max_context_skills=2, context_max_chars=900)
```

Both runtimes returned:

```text
context_len: 779
has_agent_0: True
has_agent_3: False
has_skill_0_2: False
has_omitted_peers: True
parsed max_context_peers: 4
parsed max_context_skills: 3
parsed context_max_chars: 1000
```

This confirms:

- peers are capped
- skills are capped
- omitted-peer hint is present
- config parsing works from string values
- final context stays within budget

## Live health after restart

Outside-in watchdog passed after VPS restart:

```text
agency-outside-in-watchdog: OK target=Hermes (VPS) peer_id=12D3KooWKuxTvp5xsLvkU3KEbJWSdLE4GLE9LAEZV61S5wDXHhAo task_id=d528e862-9be8-438d-9a50-d896a43b8c59 elapsed=0.4s artifact="Hi! I'm Hermes (VPS), running as an Hermes Agency node on this machine.\nI have 79 skills installed."
```

VPS-local watchdog passed:

```text
agency-health-watchdog: OK actions=none healthy=True consecutive_failures=0 agencyd=1 wrapper=1
```

## Phase 6 status

Complete.

Notes:

- I restarted the VPS `agency-node.service` to activate the updated team-context code in the long-running wrapper.
- I did not restart local workstation or the local gpt GUI/session.
- Fresh Hermes sessions will pick up the new config fields and bounded team-context rendering.
