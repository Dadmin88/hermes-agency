---
name: agency-dashboard-operations
description: Operate Hermes Agency dashboard deployments, including local/VPS access, safe network binding, systemd services, and health verification.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [agency, dashboard, vps, tailscale, systemd, operations]
---

# Agency Dashboard Operations

Use this skill when the operator asks to access, expose, run, persist, or troubleshoot the Hermes Agency dashboard.

## Triggers

- "How do I access the Hermes Agency dashboard?"
- Run the Agency dashboard on a VPS or remote host
- Make the dashboard reachable from another machine, especially over Tailscale/Tailnet
- Persist `hermes agency dashboard` under `systemd --user`
- Verify whether the dashboard is reachable versus whether the Agency runtime is healthy

## Operating pattern

1. Distinguish the two dashboards:
   - Hermes web dashboard: `hermes dashboard`, default port `9119`.
   - Hermes Agency dashboard: `hermes agency dashboard`, default port `8765`.
2. For local-only access, use:
   ```bash
   hermes agency dashboard --host 127.0.0.1 --no-open
   ```
3. For VPS-to-workstation access, prefer binding to the VPS Tailnet/Tailscale IP instead of `0.0.0.0` or the public VPS IP:
   ```bash
   hermes agency dashboard --host <tailscale-ip> --port 8765 --allow-lan --no-open
   ```
4. Verify the actual listener and HTTP reachability before reporting success:
   ```bash
   ss -ltnp | sed -n '1p;/8765/p'
   curl -fsS --max-time 5 http://<tailscale-ip>:8765/ | head -c 200
   curl -fsS --max-time 5 http://<tailscale-ip>:8765/api/health
   ```
5. If the user wants it to stay running, create a user `systemd` service and enable it.
6. Report the exact URL the remote machine should open, and state the network prerequisite (for example, "Katana must be on the same Tailnet").

## Persistent service pattern

For a long-lived dashboard server, use `systemd --user` rather than a terminal background process. Preserve the active profile explicitly in `ExecStart`:

```ini
[Unit]
Description=Hermes Agency Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/home/<user>/.local/bin/hermes -p <profile> agency dashboard --host <tailscale-ip> --port 8765 --allow-lan --no-open
Restart=on-failure
RestartSec=5
WorkingDirectory=/home/<user>

[Install]
WantedBy=default.target
```

Enable and verify:

```bash
systemctl --user daemon-reload
systemctl --user enable --now hermes-agency-dashboard.service
systemctl --user is-active hermes-agency-dashboard.service
systemctl --user status hermes-agency-dashboard.service --no-pager -l
ss -ltnp | sed -n '1p;/8765/p'
```

If it must survive logout/reboot, check linger with `loginctl show-user <user> -p Linger` and ask the human/admin to enable it if needed.

## Pitfalls

- Do not expose the Agency dashboard on the public VPS interface by default. Use Tailnet binding when available.
- `curl -I /` may return `405 Method Not Allowed` while the dashboard is reachable. Confirm with a GET to `/` or `/api/health`.
- Dashboard reachability is separate from Agency runtime health. `/api/health` can show SDK/node/daemon warnings even when the UI is correctly reachable.
- If launched from an orchestrator profile, preserve the profile explicitly in persistent services with `hermes -p <profile> agency dashboard ...`.
- The regular Hermes dashboard and the Agency dashboard use different commands and ports; do not conflate `hermes dashboard` on `9119` with `hermes agency dashboard` on `8765`.

## References

- `references/agency-dashboard-vps-access.md` — Tailscale/Tailnet VPS exposure and systemd user-service recipe.
