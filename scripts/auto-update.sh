#!/usr/bin/env bash
# Hermes Agency Auto-Updater
# Pulls latest from origin/main and restarts all running Hermes gateways.
# Works on any machine — discovers gateways dynamically via systemd.
#
# Usage:
#   ./scripts/auto-update.sh              # defaults to repo root as REPO_DIR
#   REPO_DIR=/path/to/repo ./scripts/auto-update.sh
#
# Environment:
#   REPO_DIR   — path to Hermes_Agency git clone (default: script's parent dir)
#   LOG_DIR    — where to write logs (default: ~/.hermes/agency-update/)
#   DRY_RUN    — set to "1" to check without pulling or restarting

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(dirname "$SCRIPT_DIR")}"
LOG_DIR="${LOG_DIR:-${HOME}/.hermes/agency-update}"
DRY_RUN="${DRY_RUN:-0}"

mkdir -p "$LOG_DIR"
LOGFILE="$LOG_DIR/update.log"

log() {
    local msg
    msg="$(date '+%Y-%m-%d %H:%M:%S') $*"
    echo "$msg" >> "$LOGFILE"
    echo "$msg"
}

# ── Sanity checks ───────────────────────────────────────────────────────────

if [ ! -d "$REPO_DIR/.git" ]; then
    log "ERROR: $REPO_DIR is not a git repository"
    exit 1
fi

cd "$REPO_DIR"

# ── Fetch and compare ───────────────────────────────────────────────────────

if ! git fetch origin main --quiet 2>/dev/null; then
    log "WARNING: git fetch failed (no network or auth issue), skipping"
    exit 0
fi

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    # Already up to date — exit silently (no log spam)
    exit 0
fi

log "UPDATE: $LOCAL -> $REMOTE"

if [ "$DRY_RUN" = "1" ]; then
    log "DRY_RUN: would pull and restart, skipping"
    exit 0
fi

# ── Pull (stash if needed) ──────────────────────────────────────────────────

STASHED=false
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    git stash push -m "auto-stash before update $(date +%s)" --quiet && STASHED=true
    log "Stashed local changes"
fi

if ! git pull --ff-only origin main --quiet 2>/dev/null; then
    log "ERROR: git pull failed (non-fast-forward), manual intervention needed"
    [ "$STASHED" = true ] && git stash pop --quiet 2>/dev/null || true
    exit 1
fi

NEW=$(git rev-parse --short HEAD)
log "Pulled $NEW"

if [ "$STASHED" = true ]; then
    if git stash pop --quiet 2>/dev/null; then
        log "Restored stashed changes"
    else
        log "WARNING: stash pop had conflicts — stash preserved, resolve manually"
    fi
fi

# ── Discover and restart all running Hermes gateways ────────────────────────
# Finds any systemd user service matching hermes*gateway* or *gateway*hermes*
# This works for any configured gateway service name without hard-coded profile assumptions.

RESTARTED=0
FAILED=0

restart_gateway() {
    local svc="$1"
    if systemctl --user is-active "$svc" >/dev/null 2>&1; then
        log "Restarting $svc..."
        if systemctl --user restart "$svc" 2>/dev/null; then
            log "Restarted $svc ✓"
            ((RESTARTED++)) || true
        else
            log "ERROR: Failed to restart $svc"
            ((FAILED++)) || true
        fi
    fi
}

# Find all running gateway services
for svc in $(systemctl --user list-units --type=service --state=running --no-legend --no-pager 2>/dev/null \
    | awk '{print $1}' \
    | grep -iE 'gateway' 2>/dev/null || true); do
    restart_gateway "$svc"
done

# ── Also restart any running MCP/agent connectors that depend on the plugin ─

for svc in $(systemctl --user list-units --type=service --state=running --no-legend --no-pager 2>/dev/null \
    | awk '{print $1}' \
    | grep -iE 'hermes.*mcp|mcp.*hermes|hermes.*connector' 2>/dev/null || true); do
    restart_gateway "$svc"
done

# ── Summary ─────────────────────────────────────────────────────────────────

log "Deploy complete ($NEW) — restarted $RESTARTED service(s), $FAILED failure(s)"

# Trim log to last 500 lines to prevent unbounded growth
if [ -f "$LOGFILE" ] && [ "$(wc -l < "$LOGFILE")" -gt 500 ]; then
    tail -200 "$LOGFILE" > "$LOGFILE.tmp" && mv "$LOGFILE.tmp" "$LOGFILE"
fi
