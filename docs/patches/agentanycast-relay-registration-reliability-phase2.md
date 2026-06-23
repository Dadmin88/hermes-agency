# Hermes Agency Relay Registration Reliability — Phase 2 Completion Notes

## Scope

Phase 2 deploys or confirms the canonical relay-registration reliability fix on the active Hermes Agency plugin targets, then validates live service behavior.

## Deployment targets checked

### VPS runtime

- Plugin path: `/home/dadmin/.hermes/plugins/hermes-agency/node_manager.py`
- Wrapper path: `/home/dadmin/agency-node.py`
- Service: `agency-node.service`
- Relay service: `agency-relay.service`

Status:

- Reliability fix present in VPS plugin runtime.
- VPS wrapper watchdog present in `~/agency-node.py`.
- Syntax check passed with the VPS Hermes venv.
- `agency-node.service` active.
- `agency-relay.service` active.
- One VPS `agencyd` process.
- One VPS `a2a-node.py` wrapper process.

### gpt profile

- Plugin path: `~/.hermes/profiles/<profile>/plugins/hermes-agency/node_manager.py`

Status:

- Reliability fix present.
- Syntax check passed.

### Katana profile

- Plugin path: `~/.hermes/profiles/<profile>/plugins/hermes-agency/node_manager.py`

Status:

- Reliability fix present.
- Syntax check passed.
- No laptop daemon restart was performed.
- No Katana daemon/runtime process was modified.

## Verification commands run

```bash
# Local source validation
cd ~/src/hermes-agentanycast
python3 -m py_compile hermes-agency/node_manager.py hermes-agency/tools.py hermes-agency/tests/test_unit.py

# gpt/Katana deployed plugin syntax validation, no daemon restart
python3 -m py_compile \
  ~/.hermes/profiles/katana/plugins/hermes-agency/node_manager.py \
  ~/.hermes/profiles/gpt/plugins/hermes-agency/node_manager.py

# VPS runtime validation
ssh hermes '~/.hermes/hermes-agent/venv/bin/python3 -m py_compile ~/.hermes/plugins/hermes-agency/node_manager.py ~/agency-node.py'
ssh hermes 'systemctl --user is-active agency-node.service agency-relay.service'
```

## Live health evidence

VPS service state:

```text
agency-node.service: active
agency-relay.service: active
VPS agencyd process count: 1
VPS a2a-node.py wrapper count: 1
```

Recent VPS node health logs:

```text
alive: peers=1, incoming=3, serve=True, registration_healthy=True, consecutive_failures=0
```

Recent relay logs show continuing VPS skill registration:

```text
"msg":"skills registered","peer_id":"12D3KooWKuxTvp5xsLvkU3KEbJWSdLE4GLE9LAEZV61S5wDXHhAo","agent_name":"Hermes (VPS)","skill_count":79
```

Discovery check showed all expected agents:

```text
gpt
Katana
Hermes (VPS)
```

Direct task send to VPS completed:

```json
{
  "ok": true,
  "status": "completed",
  "artifact_text": "Hi! I'm Hermes (VPS), running as an Hermes Agency node on this machine.\nI have 79 skills installed."
}
```

## Phase 2 status

Complete.

Notes:

- The VPS runtime already had the hotfix from the previous deployment and was verified rather than overwritten from the dirty local source tree.
- The local source tree still contains unrelated Hermes Agency changes, so no git commit was created during Phase 2.
- Katana's plugin file already contains the reliability fix, so no write/restart was needed. The laptop daemon was not touched.
