# Hermes Agency Troubleshooting

Start with the built-in diagnostics:

```bash
hermes agency doctor
hermes agency doctor --json
```

The doctor command checks plugin load, profile/config paths, SDK and daemon state, relay/registry configuration, trust/allowlist policy, AgentCard generation, Kanban availability, and development install state.

## Missing daemon / daemon not found

**Symptom:** `agentanycastd binary not found`, node start fails, or doctor reports `daemon_binary` failed.

**Cause:** No daemon binary is configured, present on `PATH`, or available under the profile's Agency home.

**Fix:** Install the daemon, add it to `PATH`, or set `agency.daemon_bin` to an executable binary path. Then run `hermes agency start` again.

## `agentanycast` not importable / SDK missing

**Symptom:** Agency tools are gated off, doctor reports `agentanycast SDK is not importable`, or imports fail during plugin startup.

**Cause:** The active Hermes runtime does not have the AgentAnycast Python SDK installed.

**Fix:** Install the package into the same Python environment used by Hermes, for example with an editable checkout during development:

```bash
python -m pip install -e ".[dev]"
```

Then restart the Hermes CLI/gateway/desktop session so tools are reloaded.

## No peers found / discovery empty

**Symptom:** `agency_discover` returns no agents even though other nodes are expected online.

**Cause:** The local node is not running, the relay/registry is not configured, the target peer has not registered skills, or discovery is limited to LAN only.

**Fix:** Run `hermes agency doctor`, verify `hermes agency start`, set `agency.relay` for cross-network transport, and set `AGENTANYCAST_REGISTRY_ADDRS=<registry-host>:50052` for skill discovery.

## Registry unhealthy / TTL expired

**Symptom:** The node is running but disappears from discovery after a short time, or compact status shows registration failures.

**Cause:** Relay skill-registry refresh is failing or the registry address is missing/unreachable.

**Fix:** Check `AGENTANYCAST_REGISTRY_ADDRS`, relay reachability, and node logs. Restart with `hermes agency stop && hermes agency start` after fixing the registry address.

## Relay not connected

**Symptom:** LAN discovery works but cross-network peers cannot connect.

**Cause:** `agency.relay` is missing, malformed, unreachable, or blocked by relay allowlist policy.

**Fix:** Set a valid relay address, verify relay service health, and ensure the peer ID is allowed by relay policy. If using a relay control URL, use HTTPS or localhost only.

## Remote task rejected / trust check failed

**Symptom:** Incoming tasks fail before processing, or logs mention blocked, missing, mismatched, or insufficient trust.

**Cause:** The sender is not trusted, is blocked, is outside the effective allowlist, or TOFU/name checks detected a mismatch.

**Fix:** Inspect the trust store, add or promote the trusted peer, remove stale/mismatched records only after verifying identity, and retry.

## Stale socket / daemon already running

**Symptom:** Start reports an existing daemon socket, connection refused, or a daemon already running with stale state.

**Cause:** A previous process left a socket file behind, or another Hermes/profile process owns the same daemon home.

**Fix:** Stop the owning process if it is still running. If the socket is stale, remove it only after confirming no daemon owns it, then run `hermes agency start`.

## Trust mismatch / peer not in allowlist

**Symptom:** Relay reservation or incoming task handling rejects a peer that appears discoverable.

**Cause:** Discovery is not trust. Empty allowlists deny by default unless `agency.relay.allow_all: true`; blocked peers override allow-all.

**Fix:** Add the peer to `agency.relay.allowlist` and/or the trust store. Use `allow_all` only on trusted development networks.

## `auto_start` not working

**Symptom:** The node does not start automatically when Hermes starts.

**Cause:** `agency.auto_start` is false, the plugin is disabled, the SDK is missing, or the current process loaded tools before the config change.

**Fix:** Enable the plugin and set `agency.auto_start: true`, install the SDK, then restart the Hermes CLI/gateway/desktop process. You can always start manually with `hermes agency start` or `/agency start`.
