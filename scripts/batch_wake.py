#!/usr/bin/env python3
"""Batch-wake all agency profiles on VPS (wake → register → sleep).

Usage:
  python3 batch_wake.py --dry-run              # list profiles
  python3 batch_wake.py --batch-size 10        # run wake-register-sleep
  python3 batch_wake.py --batch-size 10 --start-index 20  # resume
"""

import subprocess
import sys
import time
import shutil
import re
from pathlib import Path

PROFILES = Path.home() / ".hermes" / "profiles"
RELAY = "/ip4/100.123.57.115/tcp/4001/p2p/12D3KooWGE3zmqw2FJTyuNGAzSNCUxSNSeMvCtocULczXfX9Y8nK"
HERMES_BIN = Path.home() / ".hermes" / ".agentanycast" / "bin" / "agentanycastd"
STARTUP_WAIT = 10  # seconds to wait for daemon + relay connection


def get_agency_profiles():
    return sorted(
        p.name for p in PROFILES.iterdir()
        if p.is_dir() and p.name.startswith("agency-")
    )


def peer_id_from_log(log_path):
    """Extract peer_id from daemon log."""
    if not log_path.exists():
        return None
    try:
        text = log_path.read_text()
        for pattern in [
            r'"peer_id":"(12D3KooW[^"]+)"',
            r'peer_id=(12D3KooW\S+)',
            r'PeerID:\s+(12D3KooW\S+)',
            r'(12D3KooW[A-Za-z0-9]+)',
        ]:
            m = re.search(pattern, text)
            if m:
                pid = m.group(1).rstrip(')')
                if len(pid) > 20:
                    return pid
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


def wake_profile(name):
    """Start daemon, wait, resolve peer_id. Returns (peer_id, proc)."""
    bin_path = ensure_binary(name)
    if not bin_path:
        return None, None, "no binary"

    key = PROFILES / name / ".agency" / "key"
    sock = PROFILES / name / ".agency" / "daemon.sock"
    log = PROFILES / name / ".agency" / "logs" / "daemon.log"

    for d in [key.parent, log.parent]:
        d.mkdir(parents=True, exist_ok=True)

    # Kill stale daemon
    subprocess.run(
        ["pkill", "-f", f"profiles/{name}/.agency/bin/agentanycastd"],
        capture_output=True, timeout=3
    )
    time.sleep(0.3)
    if sock.exists():
        sock.unlink()

    # Truncate log so we only read fresh output
    log.write_text("") if log.exists() else log.touch()

    proc = subprocess.Popen(
        [str(bin_path), f"--key={key}", f"--grpc-listen=unix://{sock}",
         "--log-level=info", f"--bootstrap-peers={RELAY}"],
        stdout=open(log, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    # Wait for daemon startup + relay connection
    time.sleep(STARTUP_WAIT)

    # Resolve peer_id
    peer_id = peer_id_from_log(log)
    return peer_id, proc, None if peer_id else "no peer_id in log"


def sleep_proc(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--start-index", type=int, default=0)
    args = parser.parse_args()

    profiles = get_agency_profiles()
    print(f"Found {len(profiles)} agency profiles")

    if args.dry_run:
        for i, p in enumerate(profiles):
            print(f"  [{i}] {p}")
        return

    succeeded = []
    failed = []

    batch_start = args.start_index
    while batch_start < len(profiles):
        batch = profiles[batch_start:batch_start + args.batch_size]
        batch_num = batch_start // args.batch_size + 1
        total_batches = (len(profiles) + args.batch_size - 1) // args.batch_size
        print(f"\n{'='*60}")
        print(f"Batch {batch_num}/{total_batches}: {batch}")
        print(f"{'='*60}")

        woken = []
        for name in batch:
            print(f"  {name}...", end=" ", flush=True)
            peer_id, proc, err = wake_profile(name)
            if peer_id:
                print(f"✓ {peer_id[:24]}")
                succeeded.append(name)
                woken.append((name, proc))
            else:
                print(f"✗ {err}")
                failed.append(name)
                sleep_proc(proc)

        # Wait for registrations to propagate
        if woken:
            print(f"\n  Waiting 15s for {len(woken)} registrations to propagate...")
            time.sleep(15)

        # Sleep all in this batch
        print(f"  Sleeping batch...")
        for name, proc in woken:
            sleep_proc(proc)
            subprocess.run(
                ["pkill", "-f", f"profiles/{name}/.agency/bin/agentanycastd"],
                capture_output=True, timeout=3
            )

        print(f"  ✓ Batch {batch_num} done. "
              f"Running total: {len(succeeded)} ok, {len(failed)} failed")

        if batch_start + args.batch_size < len(profiles):
            time.sleep(3)

        batch_start += args.batch_size

    print(f"\n{'='*60}")
    print(f"COMPLETE: {len(succeeded)}/{len(profiles)} succeeded")
    if failed:
        print(f"Failed ({len(failed)}): {', '.join(failed[:15])}" +
              (f" +{len(failed)-15} more" if len(failed) > 15 else ""))


if __name__ == "__main__":
    main()
