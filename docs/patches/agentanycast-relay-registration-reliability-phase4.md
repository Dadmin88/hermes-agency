# Hermes Agency Relay Registration Reliability — Phase 4 Completion Notes

## Scope

Phase 4 adds external watchdog coverage so Hermes Agency failures are caught outside the plugin's own re-registration loop.

Implemented two watchdog layers:

1. VPS-local health watchdog: checks local services/processes/compact health and restarts local user services when recoverable.
2. Local outside-in watchdog: uses a separate temporary Hermes Agency SDK node to verify the VPS is discoverable through the relay and can complete a real task.

## VPS-local watchdog

Files installed on VPS:

- `/home/dadmin/bin/agency-health-watchdog.py`
- `/home/dadmin/.config/systemd/user/agency-health-watchdog.service`
- `/home/dadmin/.config/systemd/user/agency-health-watchdog.timer`

Timer schedule:

- every 2 minutes
- enabled with `systemctl --user enable --now agency-health-watchdog.timer`

The watchdog checks:

- `agency-relay.service` is active
- `agency-node.service` is active
- exactly one `agencyd` process exists on the VPS
- exactly one `a2a-node.py` wrapper process exists on the VPS
- compact health file exists and is fresh:
  - `/home/dadmin/.hermes/.agency/health.json`
- registration health is true
- stale registration failures trigger node restart

Recoveries:

- restarts relay if relay service is inactive
- restarts node if node service is inactive
- restarts node if process counts are wrong
- restarts node if health file is missing/stale/malformed
- restarts node if registration is unhealthy

Validation output:

```text
agency-health-watchdog: OK actions=none healthy=True consecutive_failures=0 agencyd=1 wrapper=1
```

Timer verification:

```text
agency-health-watchdog.timer enabled
NEXT ... agency-health-watchdog.timer agency-health-watchdog.service
```

## VPS wrapper health file

Patched VPS wrapper:

- `/home/dadmin/agency-node.py`

Backup created before patching:

- `/home/dadmin/agency-node.py.bak-phase4-healthfile-*`

The wrapper now writes compact node health atomically to:

```text
/home/dadmin/.hermes/.agency/health.json
```

This lets the external VPS-local watchdog inspect the running wrapper's live state instead of importing a separate `NodeManager` instance.

## Outside-in watchdog

Files installed locally:

- `~/.local/bin/agency-outside-in-watchdog.py`
- `~/.config/systemd/user/agency-outside-in-watchdog.service`
- `~/.config/systemd/user/agency-outside-in-watchdog.timer`

Timer schedule:

- every 15 minutes
- enabled with `systemctl --user enable --now agency-outside-in-watchdog.timer`

The outside-in watchdog uses an isolated SDK home:

```text
~/.cache/agency-outside-in-watchdog
```

This avoids colliding with profile-owned daemon sockets for Katana or gpt.

The outside-in watchdog verifies:

- starts an isolated temporary Hermes Agency SDK node
- discovers agents for skill `airtable`
- confirms Hermes VPS peer is discoverable:
  - `12D3KooWKuxTvp5xsLvkU3KEbJWSdLE4GLE9LAEZV61S5wDXHhAo`
- sends a real direct task to Hermes VPS
- waits for completion
- requires non-empty artifact text
- stops its temporary node and removes stale socket afterward

Manual and systemd validation output:

```text
agency-outside-in-watchdog: OK target=Hermes (VPS) peer_id=12D3KooWKuxTvp5xsLvkU3KEbJWSdLE4GLE9LAEZV61S5wDXHhAo task_id=67162551-94e5-4cb2-b92a-24a33fb2dade elapsed=0.5s artifact="Hi! I'm Hermes (VPS), running as an Hermes Agency node on this machine.\nI have 79 skills installed."
```

Timer verification:

```text
agency-outside-in-watchdog.timer enabled
NEXT Mon 2026-06-22 02:32:09 EDT ... agency-outside-in-watchdog.timer agency-outside-in-watchdog.service
```

Process cleanup verification after outside-in run:

- Only the pre-existing Katana and gpt `agencyd` processes remained.
- The outside-in watchdog did not leave a third daemon running.

## Commands used for verification

VPS:

```bash
ssh hermes 'systemctl --user start agency-health-watchdog.service'
ssh hermes 'systemctl --user status agency-health-watchdog.service --no-pager -l'
ssh hermes 'systemctl --user list-timers --all | grep agency-health-watchdog'
ssh hermes 'journalctl --user -u agency-health-watchdog.service -n 10 --no-pager -o cat'
```

Local outside-in:

```bash
~/.hermes/profiles/gpt/hermes-agent/venv/bin/python3 ~/.local/bin/agency-outside-in-watchdog.py
systemctl --user start agency-outside-in-watchdog.service
systemctl --user status agency-outside-in-watchdog.service --no-pager -l
systemctl --user list-timers --all | grep agency-outside-in-watchdog
journalctl --user -u agency-outside-in-watchdog.service -n 10 --no-pager -o cat
```

## Phase 4 status

Complete.

Notes:

- Katana/gpt profile daemons were not restarted.
- The local systemd timer runs an isolated SDK node for outside-in checks and cleans it up; it does not use the Katana or gpt daemon sockets.
- The VPS timer is active and will repair local relay/node failures that are visible from service/process/health-file state.
- The outside-in timer is active and proves the higher-level condition: another machine can discover Hermes VPS and receive a completed task response.
