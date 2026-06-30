---
name: vps-hardening
description: "Secure a fresh Linux VPS without locking out the operator: Tailscale/recovery access first, then firewall, SSH, update, logging, and verification hardening."
summary: "Secure a fresh Linux VPS without locking out the operator: audit exposure, establish a Tailscale recovery path first, then apply firewall, SSH, update, logging, and verification hardening."
triggers:
  - fresh VPS security audit
  - secure this box
  - VPS hardening
  - server lockdown
  - SSH/firewall hardening
  - Tailscale recovery access
---

# VPS Hardening

Use this for first-pass security audits and hardening of a fresh Linux VPS. The priority is a working, verified server, not a theoretical checklist. Never make lockout-prone changes until a recovery path is installed and verified.

## Core rule: access safety comes first

1. Keep the current SSH session open throughout hardening.
2. Before enabling a deny-by-default firewall or tightening SSH, install and log in Tailscale or another out-of-band recovery path.
3. Verify the recovery path from a second terminal before proceeding:
   - `tailscale status`
   - `tailscale ip -4`
   - `ssh <admin>@<tailscale-ip>`
4. Keep public SSH on the current port as a fallback during first-pass hardening. Do not move SSH to Tailscale-only, restrict public SSH to narrow source IPs, or change ports during the initial pass unless the user explicitly asks and confirms a tested alternate path.
5. Validate `sshd -t` and effective `sshd -T` before reloading SSH.

User preference learned: when securing a VPS, avoid any action that could lock the user out. Add Tailscale login and second-session verification to the plan before firewall/SSH lockdown.

## Working with the user

- **Batch sudo commands.** Group related sudo commands into a single `terminal()` call to avoid credential expiry between calls. When that's not possible (e.g., complex multi-step operations), prep files in `/tmp/` and give the user a clean list of commands to run manually.
- **Plan before executing.** For multi-phase hardening, create a structured plan with the `plan` skill before starting work. Break into phases: Phase 1 (critical security — firewall, SSH, exposure), Phase 2 (cleanup and QoL), Phase 3 (monitoring), Phase 4 (advanced). This gives the user a clear checkpoint structure.
- **Audit first, change nothing.** Always collect the full audit before making any changes. Present findings as a report, then create the implementation plan. The user wants to see what's wrong before fixing it.

## Audit checklist

Collect current state before changing anything:

- Identity and privileges: `id`, `whoami`, sudo ability, sudo/admin groups.
- OS/kernel/update state: `/etc/os-release`, `uname -a`, `apt-get -s upgrade`, `apt-get -s dist-upgrade`.
- Login-capable users: `getent passwd | awk -F: '$7 !~ /(nologin|false)$/ {print}'`.
- SSH config:
  - config excerpts from `/etc/ssh/sshd_config*`
  - effective config with root: `sshd -T`
  - selected settings: port, root login, password auth, keyboard-interactive, pubkey, X11, AllowUsers/AllowGroups, MaxAuthTries, LoginGraceTime.
- Network exposure: `ss -tulpn`. Pay special attention to non-standard ports (e.g., 9119, 8080, 3000) that may be web UIs bound to `0.0.0.0` — these are often overlooked exposure points.
- Firewall: `ufw status verbose`, `nft list ruleset`, or `iptables -S` depending on distro.
- Services: enabled/running units and `systemctl --failed`.
- Security packages: unattended-upgrades, ufw/nftables, fail2ban, auditd, needrestart, apparmor/selinux.
- Recent auth failures: `journalctl -u ssh --since '24 hours ago'`.
- Mounts and obvious hygiene: `findmnt`, world-writable dirs without sticky bit.

## Safe implementation sequence

1. Patch and install tools:
   - Debian/Ubuntu: `apt-get update && apt-get -y full-upgrade`
   - Install: `ca-certificates curl gnupg ufw fail2ban needrestart auditd audispd-plugins debsums apt-show-versions unattended-upgrades`.
2. Install Tailscale before firewall/SSH changes:
   - `curl -fsSL https://tailscale.com/install.sh | sh`
   - `systemctl enable --now tailscaled`
   - `tailscale up` or `tailscale up --ssh` if Tailscale SSH is desired.
   - Stop if no Tailscale IP is present.
3. SSH hardening:
   - Use a drop-in that sorts before cloud-init drop-ins, e.g. `/etc/ssh/sshd_config.d/00-hardening.conf`.
   - Include: `PermitRootLogin no`, `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PubkeyAuthentication yes`, `PermitEmptyPasswords no`, `X11Forwarding no`, `MaxAuthTries 3`, `LoginGraceTime 30`, `ClientAliveInterval 300`, `ClientAliveCountMax 2`, and an explicit `AllowUsers <admin>` when appropriate.
   - Run `sshd -t`.
   - Run `sshd -T` and verify the effective values, especially `passwordauthentication no`.
   - Reload SSH, do not restart blindly.
4. Disable unnecessary public listeners:
   - On VPS hosts, disable systemd-resolved LLMNR/mDNS unless explicitly needed; verify TCP/UDP 5355 disappears from public listeners.
5. Firewall:
   - Default deny incoming, allow outgoing.
   - Allow the existing SSH port before enabling.
   - Allow Tailscale interface: `ufw allow in on tailscale0`.
   - Allow Tailscale direct UDP 41641 if using Tailscale.
   - Enable and verify `ufw status verbose`.
6. Brute-force protection:
   - Enable fail2ban sshd jail with systemd backend.
   - Verify `fail2ban-client status sshd`.
7. Kernel/sysctl/logging:
   - Enable ASLR, dmesg/kptr restrictions, protected links/fifos/regular files, syncookies.
   - Disable forwarding, redirects, and source routing unless this host routes traffic.
   - Enable persistent journald and auditd with basic watches for auth, sudoers, and SSH config.
8. Reboot only after both public SSH and Tailscale access are verified in a second terminal, especially after kernel upgrades.

## Pitfalls

- **Sudo credential expiry between terminal() calls.** Each `terminal()` call may start a fresh shell. Sudo credentials cached in one call do not persist to the next. When you need multiple sudo commands, either batch them into a single `terminal()` call (`sudo cmd1 && sudo cmd2 && sudo cmd3`), or ask the user to run the commands manually. Do NOT pipe passwords to `sudo -S` — the agent blocks this as a security measure. **Automated sudo:** Set `SUDO_PASSWORD=<password>` in `~/.hermes/.env` to enable passwordless sudo for the terminal tool. This is the only supported mechanism for automated sudo — piping to `sudo -S` is explicitly blocked.
- **`needrestart` interactive dialog during apt installs.** On Debian, `apt-get install` may trigger `needrestart`, which shows a ncurses dialog listing services that need restart (ssh, fail2ban, journald, etc.). Tell the user to press Enter or OK with the default selections — all listed services are safe to restart. If connected via Hermes gateway (not SSH directly), restarting ssh.service won't disconnect the session.
- OpenSSH include ordering matters. On Debian cloud images, `/etc/ssh/sshd_config` may include `/etc/ssh/sshd_config.d/*.conf` near the top, and `50-cloud-init.conf` can override expectations. Because OpenSSH uses the first obtained value for many global options, a `99-hardening.conf` may not win. Prefer `00-hardening.conf` and verify with `sshd -T`, not file contents.
- `PasswordAuthentication no` appearing in a file is not enough. The only acceptable proof is effective `sshd -T` showing `passwordauthentication no`.
- Do not assume a non-root audit sees every SSH include: cloud-init SSH drop-ins may be mode 0600.
- **Dashboard bind address may change on restart.** If a web dashboard (Hermes, etc.) is restarted, its bind address may revert to `0.0.0.0` or change from a previous configuration. Always re-verify with `ss -tlnp | grep <port>` and `curl` from the public IP after any dashboard restart. The `--host` flag in the startup command controls this — make sure startup scripts are updated, not just the running process.
- Tailscale installed is not the same as Tailscale authenticated. Stop before firewall/SSH changes unless `tailscale status` and `tailscale ip -4` prove login.
- `tailscale up` enables network access to the Tailscale IP; `tailscale up --ssh` additionally enables Tailscale's managed SSH. Normal OpenSSH over the Tailscale IP still works when sshd listens and firewall allows `tailscale0`.
- **`sed` for Netdata bind-to-localhost fails silently.** `sed -i 's/bind to = \*/bind to = 127.0.0.1/' /etc/netdata/netdata.conf` returns exit code 0 even when the pattern doesn't match (fresh installs have a bare comment-only config). The `|| fallback` branch never executes. Instead, always append the section directly: `echo -e '\n[web]\n    bind to = 127.0.0.1' | sudo tee -a /etc/netdata/netdata.conf`.
- **`swapon`/`mkswap` may not be in user PATH.** These live in `/usr/sbin/` which isn't in the default user PATH on some Debian installs. The swap still works fine — verify with `free -h` instead of relying on `swapon --show`. If the user reports "command not found", reassure them the swap is active.
- **`logrotate` not installed by default on Debian 13.** Always check with `dpkg -l logrotate` before referencing it. Install explicitly: `sudo apt-get install -y logrotate`.
- **Sysctl hardening may already be done on Debian 13+.** Many recommended values (`dmesg_restrict=1`, `kptr_restrict=2`, `protected_hardlinks=1`, `protected_fifos=2`, `yama/ptrace_scope=1`) are already at hardened defaults. Verify before writing a sysctl hardening file — applying redundant rules is harmless but noisy. Check individual values with `cat /proc/sys/...` if `sysctl` isn't available.
- `needrestart` may report a pending kernel upgrade. Do not reboot until alternate access has been tested.

## Verification checklist

Before finalizing:

- `tailscale status` shows the node logged in.
- `tailscale ip -4` returns an address.
- A second terminal can SSH over public IP and over Tailscale IP.
- `ufw status verbose` is active and allows only intended inbound paths.
- `ss -tulpn` has no unexpected public listeners.
- `sshd -T` confirms hardened values.
- `fail2ban-client status sshd` is healthy.
- `systemctl --failed --no-pager` is empty or explained.
- `apt-get -s upgrade` reports no pending upgrades.
- If a kernel upgrade is pending, reboot only after access verification, then re-run the verification checklist.

## Post-hardening recommendations

After the core hardening is complete, address these common findings:

- **Swap.** Most VPS instances ship with no swap. If the box has ≤16 GB RAM, add a swapfile as an OOM-killer buffer: `sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`. Persist in `/etc/fstab`. Set `vm.swappiness=10` in `/etc/sysctl.d/99-swap.conf`.
- **Log rotation for application logs.** If apps write to `~/.user/logs/`, create a logrotate config in `/etc/logrotate.d/` with `copytruncate` (avoids needing to signal the app to reopen files). Prep the config in `/tmp/` and ask the user to `sudo cp` it into place.
- **Unnecessary services.** Common unnecessary services on VPS: `exim4` (MTA, rarely needed), `ModemManager`, `bluetooth`. Disable with `sudo systemctl disable --now <service>`.
- **Web UIs.** Any web dashboard (Hermes, Netdata, Grafana, etc.) should be bound to `127.0.0.1` or the Tailscale IP, never `0.0.0.0`. If TLS is needed, use Caddy as a reverse proxy with Tailscale certs (`tailscale cert <hostname>`).
- **Netdata.** Install via official kickstart script. Bind to localhost by appending `[web]\n    bind to = 127.0.0.1` to `/etc/netdata/netdata.conf`. Access via Tailscale IP at port 19999.
- **Caddy + Tailscale HTTPS** for secure dashboard access. See `references/caddy-tailscale-setup.md` for the full pattern and pitfalls. Key points:
  - Tailscale cert/key pairs can be mismatched if generated at different times. Always verify with `openssl x509 -noout -modulus` and `openssl ec -noout -text` — moduli must match.
  - Caddy runs as the `caddy` user and **cannot access files in `/home/dadmin/`**. Copy certs to `/etc/caddy/` and `chown caddy:caddy`.
  - `tls internal` creates Caddy's own CA but fails to install the root cert (expected, non-fatal). Works fine for Tailscale access since devices don't need to trust the CA — just accept the self-signed cert.
  - **If TLS setup is problematic, use HTTP on a custom port (e.g., `:8080`) instead.** Tailscale encrypts all mesh traffic end-to-end, so HTTP over Tailscale is already secure. This is often simpler and more reliable than fighting cert issues.
- **Tailscale Funnel for public HTTPS exposure without opening service ports.** Use `sudo tailscale funnel --bg <port>` for persistence; plain `tailscale funnel <port>` is foreground and may not leave a serve config. Ensure the tailnet policy has `nodeAttrs` granting `"funnel"` to the exact node IP or server tag, and verify persistence with `tailscale serve status --json` showing `AllowFunnel` and a `Proxy` mapping. See `references/tailscale-funnel-service-exposure.md`.

## References

- `references/debian-tailscale-first-hardening.md` captures the session-specific lesson on Tailscale-first hardening and OpenSSH drop-in ordering on Debian cloud images.
- `references/vps-audit-template.md` is a ready-to-use audit template with exact commands and report structure for full VPS audits.
- `references/tailscale-funnel-service-exposure.md` captures the Tailscale Funnel policy, `--bg` persistence, systemd-user linger, and verification pattern for exposing local VPS services safely.
