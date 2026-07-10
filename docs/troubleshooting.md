# Hermes Agency Troubleshooting

Start with the built-in diagnostics:

```bash
hermes agency doctor
hermes agency doctor --json
```

The doctor command checks plugin load, profile/config paths, transport SDK and daemon state, relay/registry configuration, trust/allowlist policy, AgentCard generation, Kanban availability, and development install state.

## Keryx daemon unreachable / node start fails

**Symptom:** `hermes agency start` fails, `agency_info` reports a transport error, or doctor reports that the Keryx daemon is not reachable.

**Cause:** `agency.transport_backend` is `keryx`, but `keryxd` is not running, the daemon endpoint is wrong, or the process cannot open the configured socket/TCP target.

**Fix:** Start `keryxd`, verify its health, then set one of:

```yaml
agency:
  transport_backend: keryx
  keryx:
    daemon_endpoint: <daemon-endpoint>
```

or export `HERMES_KERYX_DAEMON_ENDPOINT=<daemon-endpoint>` / `KERYX_DAEMON_ENDPOINT=<daemon-endpoint>` in the Hermes runtime environment. Restart the Hermes CLI/gateway/desktop process after changing environment variables.

## `keryx` not importable / SDK missing

**Symptom:** Agency tools are gated off, doctor reports that the Keryx SDK is not importable, or imports fail during plugin startup.

**Cause:** The active Hermes runtime does not include the vendored SDK package from this repository. This usually means a partial plugin copy, stripped source checkout, or broken editable install.

**Fix:** Install Hermes Agency into the same Python environment used by Hermes:

```bash
cd <workspace>/Hermes_Agency
python -m pip install -e ".[dev]"
```

This installs the vendored SDK from `src/keryx/`. Do not install a sibling `Hermes_Keryx/sdk/python` checkout unless intentionally testing an alternate SDK. Restart the Hermes CLI/gateway/desktop session so tools are reloaded.

## No peers found / discovery empty

**Symptom:** `agency_discover` returns no agents even though other nodes are expected online.

**Cause:** The local node is not running, Keryx relay/registry endpoints are missing or unreachable, the target peer has not registered skills, trust policy blocks the peer, or discovery is limited to a local network/runtime.

**Fix:** Run `hermes agency doctor`, verify `hermes agency start`, and configure Keryx endpoints under `agency.keryx.*` (or `HERMES_KERYX_*` / `KERYX_*` environment variables):

```yaml
agency:
  transport_backend: keryx
  keryx:
    relay_endpoint: <relay-endpoint>
    registry_endpoint: <registry-address>
```

Legacy `agency.relay` and `AGENTANYCAST_REGISTRY_ADDRS` only apply when `agency.transport_backend: agentanycast` is explicitly selected.

## Registry unhealthy / TTL expired

**Symptom:** The node is running but disappears from discovery after a short time, or compact status shows registration failures.

**Cause:** Skill registration refresh is failing, the Keryx registry endpoint is missing/unreachable, or the legacy registry variable is being used while the backend is set to Keryx.

**Fix:** Check `agency.keryx.registry_endpoint` or `HERMES_KERYX_REGISTRY_ENDPOINT`, verify registry service health, and restart with `hermes agency stop && hermes agency start` after fixing the endpoint.

## Relay not connected

**Symptom:** LAN/local discovery works but cross-network peers cannot connect.

**Cause:** `agency.keryx.relay_endpoint` is missing, malformed, unreachable, or blocked by relay/trust policy.

**Fix:** Set a valid Keryx relay endpoint, verify relay service health, and ensure the peer is trusted/allowed by policy. Keep relay endpoints generic in committed docs/config examples and do not publish private relay addresses.

## Remote task rejected / trust check failed

**Symptom:** Incoming tasks fail before processing, or logs mention blocked, missing, mismatched, or insufficient trust.

**Cause:** The sender is not trusted, is blocked, is outside the effective allowlist, or TOFU/name checks detected a mismatch.

**Fix:** Inspect the trust store, add or promote the trusted peer, remove stale/mismatched records only after verifying identity, and retry. Discovery is not trust; a discoverable peer can still be rejected.

## Stale socket / daemon already running

**Symptom:** Start reports an existing daemon socket, connection refused, or a daemon already running with stale state.

**Cause:** A previous process left a socket file behind, another Hermes/profile process owns the same runtime home, or `HERMES_KERYX_DAEMON_ENDPOINT` points at an old socket.

**Fix:** Stop the owning process if it is still running. If the socket is stale, remove it only after confirming no daemon owns it, then run `hermes agency start`.

## Legacy AgentAnycast fallback selected

**Symptom:** Logs, doctor output, or status mention AgentAnycast when Keryx was expected.

**Cause:** `agency.transport_backend` is set to `agentanycast`, an old config default is still present, or the Keryx SDK import failed and the runtime fell back to the compatibility path.

**Fix:** Set `agency.transport_backend: keryx`, install this package so `src/keryx/` is importable, and move relay/registry settings from legacy `agency.relay` / `AGENTANYCAST_*` to `agency.keryx.*` or `HERMES_KERYX_*`.

## MCP HTTP endpoint exposed to network

**Symptom:** MCP HTTP endpoint is reachable from other hosts, or doctor reports `mcp_http_exposure` as a warning.

**Cause:** MCP HTTP mode serves tools without built-in authentication. If bound beyond localhost, any network client that can reach the endpoint may be able to invoke tools.

**Fix:** Bind MCP HTTP mode to localhost only, put it behind a reverse proxy with authentication and network restrictions, or disable MCP HTTP mode when it is not explicitly needed.

## `auto_start` not working

**Symptom:** The node does not start automatically when Hermes starts.

**Cause:** `agency.auto_start` is false, the plugin is disabled, the Keryx SDK is missing, the daemon endpoint is unreachable, or the current process loaded tools before the config change.

**Fix:** Enable the plugin, set `agency.auto_start: true`, verify `keryx` imports and `keryxd` is reachable, then restart the Hermes CLI/gateway/desktop process. You can always start manually with `hermes agency start` or `/agency start`.
