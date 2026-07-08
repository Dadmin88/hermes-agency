# Hermes Agency Troubleshooting

Start with the built-in diagnostics:

```bash
hermes agency doctor
hermes agency doctor --json
hermes-agency status --extended
```

Doctor checks plugin load, profile/config paths, transport SDK availability, daemon/relay state, trust/allowlist policy, AgentCard generation, Kanban availability, and development install state.

## Confirm transport backend

```yaml
agency:
  transport_backend: keryx   # primary
  # agentanycast = legacy fallback only
```

Compact status/info should include `transport_backend` and `effective_transport_backend`.

## Missing Keryx daemon / daemon not found

**Symptom:** Node start fails, doctor reports missing Keryx daemon, or no listener on the daemon endpoint.

**Cause:** `keryxd` is not running, not on `PATH`, or `agency.keryx.daemon_endpoint` / `HERMES_KERYX_DAEMON_ENDPOINT` points at the wrong place.

**Fix:**

```bash
# from hermes-keryx checkout
./scripts/keryx-dual-run.sh --start
./scripts/keryx-dual-run.sh --status
```

Typical daemon endpoint: `127.0.0.1:50051`.

## Keryx SDK not importable

**Symptom:** Agency tools gated off, doctor reports Keryx/SDK unavailable, `from keryx import KeryxNode` fails.

**Cause:** Hermes is using a Python environment without the Agency package (and vendored `src/keryx/`) installed.

**Fix:**

```bash
cd <workspace>/Hermes_Agency
python -m pip install -e ".[dev]"
```

Restart the Hermes CLI/gateway session so tools reload.

## No peers found / discovery empty

**Symptom:** `agency_discover` returns no agents.

**Cause:** Local node not running, Keryx registry/relay not configured, peer has not registered skills, or still pointing at legacy AgentAnycast registry vars only.

**Fix:**

1. `hermes agency doctor` + `hermes agency start`
2. Confirm Keryx registry endpoint (dual-run default `127.0.0.1:51053`)
3. Confirm relay health (dual-run default `127.0.0.1:51052`) and libp2p (`4101` dual-run)
4. Ensure target peer registered skills

Legacy fallback only:

```bash
export AGENTANYCAST_REGISTRY_ADDRS=<registry-host>:50052
```

## Registry unhealthy / TTL expired

**Symptom:** Node runs but drops from discovery; compact status shows registration failures.

**Cause:** Registry endpoint missing/unreachable, or relay not healthy.

**Fix:** Check `agency.keryx.registry_endpoint` / `HERMES_KERYX_REGISTRY_ENDPOINT`, dual-run status, and node logs. Restart after correcting endpoints:

```bash
hermes agency stop && hermes agency start
```

## Relay not connected

**Symptom:** Same-host works but multi-host peers cannot connect.

**Cause:** Relay config missing/malformed/unreachable, or peer blocked by allowlist.

**Fix:** Validate `HERMES_KERYX_RELAY_CONFIG` / relay.toml/json, relay process health, and allowlist policy. Prefer loopback-only dual-run for single-host installs.

## Remote task rejected / trust check failed

**Symptom:** Incoming tasks fail before processing; trust/allowlist errors in logs.

**Cause:** Sender not trusted, blocked, outside allowlist, or identity mismatch.

**Fix:** Inspect trust store and allowlist policy; add/promote trusted peers only after verifying identity.

## Stale socket / daemon already running

**Symptom:** Start reports existing daemon socket, connection refused, or stale daemon home ownership.

**Cause:** Previous process left state behind, or another profile owns the same daemon home/socket.

**Fix:** Stop the owning process. Remove stale sockets only after confirming no process owns them, then restart.

## Fallback to AgentAnycast

If Keryx is intentionally unavailable:

```yaml
agency:
  transport_backend: agentanycast
```

Then ensure legacy AgentAnycast package/daemon/relay are installed and configured. Prefer returning to Keryx once dual-run validation passes (`hermes-keryx` migration + dual-run scripts).

## Migration / rollback

From the hermes-keryx repo:

```bash
./scripts/migrate-to-keryx.sh --dry-run
./scripts/migrate-to-keryx.sh
./scripts/migrate-to-keryx.sh --revert
```

Keep a known-good config backup before cutover.
