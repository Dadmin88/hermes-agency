#!/usr/bin/env python3
"""Batch-wake agency profiles: keep N running simultaneously, rotate through all.

Starts daemons one at a time (avoids bolt-db lock contention), keeps up to
--batch-size running at once, sleeps the oldest when the batch is full.

Usage:
  python3 batch_wake.py --dry-run
  python3 batch_wake.py --batch-size 10
  python3 batch_wake.py --batch-size 10 --start-index 40
"""

import subprocess
import sys
import time
import shutil
import re
import json
from pathlib import Path
from datetime import datetime
from collections import OrderedDict

PROFILES = Path.home() / ".hermes" / "profiles"
RELAY = "/ip4/100.123.57.115/tcp/4001/p2p/12D3KooWGE3zmqw2FJTyuNGAzSNCUxSNSeMvCtocULczXfX9Y8nK"
HERMES_BIN = Path.home() / ".hermes" / ".agentanycast" / "bin" / "agentanycastd"
STARTUP_WAIT = 12
STATE_FILE = Path.home() / "batch_wake_state.json"


def get_agency_profiles():
    return sorted(
        p.name for p in PROFILES.iterdir()
        if p.is_dir() and p.name.startswith("agency-")
    )


def peer_id_from_log(log_path):
    if not log_path.exists():
        return None
    try:
        text = log_path.read_text()
        for pattern in [
            r'"peer_id":"(12D3KooW[^"]+)"',
            r'peer_id=(12D3KooW\S+)',
            r'PeerID:\s+(12D3KooW\S+)',
            r'(12D3KooW[A-Za-z0-9]{20,})',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1).rstrip(')')
    except Exception:
        pass
    return None


def ensure_binary(name):
    profile_bin = PROFILES / name / ".agency" / "bin" / "agentanycastd"
    if profile_bin.exists():
        return profile_bin
    if HERMES_BIN.exists():
        profile_bin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERMES_BIN, profile_bin)
        profile_bin.chmod(0o755)
        return profile_bin
    return None


def clean_stale(name):
    """Kill stale daemon and remove lock files."""
    subprocess.run(
        ["pkill", "-f", f"profiles/{name}/.agency/bin/agentanycastd"],
        capture_output=True, timeout=3
    )
    time.sleep(0.3)
    agency_dir = PROFILES / name / ".agency"
    for f in agency_dir.rglob("*.lock"):
        f.unlink(missing_ok=True)
    sock = agency_dir / "daemon.sock"
    sock.unlink(missing_ok=True)


def start_daemon(name):
    """Start daemon process. Returns (proc, log_path)."""
    bin_path = ensure_binary(name)
    if not bin_path:
        return None, None

    clean_stale(name)

    key = PROFILES / name / ".agency" / "key"
    sock = PROFILES / name / ".agency" / "daemon.sock"
    log = PROFILES / name / ".agency" / "logs" / "daemon.log"

    for d in [key.parent, log.parent]:
        d.mkdir(parents=True, exist_ok=True)
    log.write_text("")

    proc = subprocess.Popen(
        [str(bin_path), f"--key={key}", f"--grpc-listen=unix://{sock}",
         "--log-level=info", f"--bootstrap-peers={RELAY}"],
        stdout=open(log, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return proc, log


def stop_daemon(name, proc):
    if proc and proc.poll() is None:
        proc.kill()  # SIGKILL — bolt-db daemons ignore SIGTERM
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    clean_stale(name)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"succeeded": [], "failed": [], "last_index": 0}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--resume", action="store_true", help="Resume from saved state")
    args = parser.parse_args()

    profiles = get_agency_profiles()
    print(f"Found {len(profiles)} agency profiles")

    if args.dry_run:
        for i, p in enumerate(profiles):
            print(f"  [{i}] {p}")
        return

    state = load_state() if args.resume else {"succeeded": [], "failed": [], "last_index": 0}
    start = max(args.start_index, state.get("last_index", 0))
    succeeded = set(state.get("succeeded", []))
    failed = list(state.get("failed", []))

    # active = OrderedDict of name -> (proc, log_path)
    active = OrderedDict()

    def register_batch():
        """Wait for all active daemons to register, record results, then sleep them."""
        if not active:
            return
        print(f"\n  Waiting {STARTUP_WAIT}s for {len(active)} registrations...")
        time.sleep(STARTUP_WAIT)

        for name, (proc, log_path) in list(active.items()):
            peer_id = peer_id_from_log(log_path)
            if peer_id:
                print(f"    ✓ {name}: {peer_id[:24]}")
                succeeded.add(name)
            else:
                print(f"    ✗ {name}: no peer_id")
                failed.append(name)
            stop_daemon(name, proc)

        active.clear()
        # Clean all lock files between batches
        subprocess.run(
            ["find", str(PROFILES), "-name", "*.lock", "-delete"],
            capture_output=True, timeout=5
        )
        time.sleep(2)

    for i in range(start, len(profiles)):
        name = profiles[i]

        # If batch is full, register + sleep the current batch first
        if len(active) >= args.batch_size:
            print(f"\n--- Batch full ({len(active)}), registering ---")
            register_batch()
            state["succeeded"] = list(succeeded)
            state["failed"] = failed
            state["last_index"] = i
            save_state(state)

        # Start this daemon
        print(f"  [{i}] Starting {name}...", end=" ", flush=True)
        proc, log_path = start_daemon(name)
        if proc:
            print(f"pid={proc.pid}")
            active[name] = (proc, log_path)
        else:
            print("✗ failed to start")
            failed.append(name)

    # Register any remaining active daemons
    if active:
        print(f"\n--- Final batch ({len(active)}) ---")
        register_batch()

    state["succeeded"] = list(succeeded)
    state["failed"] = failed
    state["last_index"] = len(profiles)
    save_state(state)

    print(f"\n{'='*60}")
    print(f"COMPLETE: {len(succeeded)}/{len(profiles)} succeeded")
    if failed:
        print(f"Failed ({len(failed)}): {', '.join(failed[:15])}")
        if len(failed) > 15:
            print(f"  +{len(failed)-15} more")


if __name__ == "__main__":
    main()
