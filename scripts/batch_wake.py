#!/usr/bin/env python3
"""Batch-register agency profiles on VPS: wake one at a time, register, sleep.

Usage:
  python3 batch_wake.py --dry-run
  python3 batch_wake.py --resume
"""

import subprocess
import sys
import time
import shutil
import re
import json
from pathlib import Path

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
    subprocess.run(
        ["pkill", "-9", "-f", f"profiles/{name}/.agency/bin/agentanycastd"],
        capture_output=True, timeout=3
    )
    time.sleep(0.3)
    agency_dir = PROFILES / name / ".agency"
    for f in agency_dir.rglob("*.lock"):
        f.unlink(missing_ok=True)
    sock = agency_dir / "daemon.sock"
    sock.unlink(missing_ok=True)


def wake_and_register(name):
    """Start daemon, wait for registration, return peer_id, then kill daemon."""
    bin_path = ensure_binary(name)
    if not bin_path:
        return None, "no binary"

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

    time.sleep(STARTUP_WAIT)

    # Retry reading peer_id — log may not be flushed yet
    peer_id = None
    for attempt in range(3):
        peer_id = peer_id_from_log(log)
        if peer_id:
            break
        time.sleep(2)

    # Kill daemon
    proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    clean_stale(name)

    return peer_id, None if peer_id else "no peer_id in log"


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
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    profiles = get_agency_profiles()
    print(f"Found {len(profiles)} agency profiles")

    if args.dry_run:
        for i, p in enumerate(profiles):
            print(f"  [{i}] {p}")
        return

    state = load_state() if args.resume else {"succeeded": [], "failed": [], "last_index": 0}
    start = max(args.start_index, state.get("last_index", 0))
    succeeded = list(state.get("succeeded", []))
    failed = list(state.get("failed", []))

    for i in range(start, len(profiles)):
        name = profiles[i]
        print(f"  [{i}/{len(profiles)}] {name}...", end=" ", flush=True)

        peer_id, err = wake_and_register(name)
        if peer_id:
            print(f"✓ {peer_id[:24]}")
            succeeded.append(name)
        else:
            print(f"✗ {err}")
            failed.append(name)

        # Save progress every 5 profiles
        if (i + 1) % 5 == 0:
            state["succeeded"] = succeeded
            state["failed"] = failed
            state["last_index"] = i + 1
            save_state(state)
            print(f"  [checkpoint: {len(succeeded)} ok, {len(failed)} failed]")

    state["succeeded"] = succeeded
    state["failed"] = failed
    state["last_index"] = len(profiles)
    save_state(state)

    print(f"\n{'='*60}")
    print(f"COMPLETE: {len(succeeded)}/{len(profiles)} succeeded")
    if failed:
        print(f"Failed ({len(failed)}): {', '.join(failed[:15])}")


if __name__ == "__main__":
    main()
