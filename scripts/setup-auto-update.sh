#!/usr/bin/env bash
# Hermes Agency Auto-Update Setup
# Installs a systemd timer that keeps Hermes Agency up to date automatically.
#
# Usage:
#   ./scripts/setup-auto-update.sh           # install timer (polls every 5 min)
#   ./scripts/setup-auto-update.sh --remove   # uninstall timer
#   POLL_SECONDS=600 ./scripts/setup-auto-update.sh  # custom interval (default: 300)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
UPDATE_SCRIPT="$SCRIPT_DIR/auto-update.sh"
POLL_SECONDS="${POLL_SECONDS:-300}"

UNIT_NAME="hermes-agency-update"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

# ── Remove ──────────────────────────────────────────────────────────────────

if [ "${1:-}" = "--remove" ]; then
    systemctl --user disable --now "${UNIT_NAME}.timer" 2>/dev/null || true
    rm -f "$UNIT_DIR/${UNIT_NAME}.timer"
    rm -f "$UNIT_DIR/${UNIT_NAME}.service"
    systemctl --user daemon-reload 2>/dev/null || true
    echo "✓ Removed ${UNIT_NAME} timer and service"
    exit 0
fi

# ── Pre-flight ──────────────────────────────────────────────────────────────

if [ ! -d "$REPO_DIR/.git" ]; then
    echo "ERROR: $REPO_DIR is not a git repository"
    exit 1
fi

if [ ! -x "$UPDATE_SCRIPT" ]; then
    chmod +x "$UPDATE_SCRIPT"
fi

# Ensure systemd --user works (some headless servers need this)
if ! systemctl --user status >/dev/null 2>&1; then
    echo "WARNING: systemd --user may not be available."
    echo "  For headless servers, ensure lingering is enabled:"
    echo "    loginctl enable-linger \$(whoami)"
    echo "  Falling back to cron-based setup..."
    
    # Offer cron fallback
    CRON_LINE="*/5 * * * * REPO_DIR=$REPO_DIR $UPDATE_SCRIPT >> ${HOME}/.hermes/agency-update/cron.log 2>&1"
    
    if crontab -l 2>/dev/null | grep -qF "auto-update.sh"; then
        echo "  Cron entry already exists, skipping"
    else
        (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
        echo "  ✓ Added cron entry (runs every 5 minutes)"
    fi
    echo ""
    echo "Logs: ~/.hermes/agency-update/"
    exit 0
fi

# ── Install systemd timer ──────────────────────────────────────────────────

mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/${UNIT_NAME}.service" <<EOF
[Unit]
Description=Hermes Agency auto-update from GitHub
After=network-online.target

[Service]
Type=oneshot
ExecStart=$UPDATE_SCRIPT
Environment="REPO_DIR=$REPO_DIR"
Environment="HOME=$HOME"
Environment="PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
EOF

cat > "$UNIT_DIR/${UNIT_NAME}.timer" <<EOF
[Unit]
Description=Hermes Agency auto-update poller

[Timer]
OnBootSec=60
OnUnitActiveSec=${POLL_SECONDS}
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "${UNIT_NAME}.timer"

echo "✓ Hermes Agency auto-update installed"
echo ""
echo "  Timer:     ${UNIT_NAME}.timer (every ${POLL_SECONDS}s)"
echo "  Service:   ${UNIT_NAME}.service"
echo "  Script:    $UPDATE_SCRIPT"
echo "  Logs:      ~/.hermes/agency-update/update.log"
echo ""
echo "  Commands:"
echo "    systemctl --user status ${UNIT_NAME}.timer"
echo "    journalctl --user -u ${UNIT_NAME}.service -f"
echo "    $0 --remove"
