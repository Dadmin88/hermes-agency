#!/usr/bin/env python3
"""Batch-wake all agency profiles on the VPS.

The pool manager handles batching internally: when max_active_agents is
reached, it sleeps the oldest non-persistent agent to make room.

Usage: python3 batch_wake.py [--dry-run] [--batch-size 10] [--set-limit N]
"""

import subprocess
import sys
import time
from pathlib import Path

REPO = Path.home() / "Hermes_Agency"
PROFILES = Path.home() / ".hermes" / "profiles"


def get_agency_profiles():
    """List all agency-* profile directories."""
    return sorted(
        p.name for p in PROFILES.iterdir()
        if p.is_dir() and p.name.startswith("agency-")
    )


def wake_profile(name, venv_python):
    """Wake a single profile by starting its daemon directly."""
    key = PROFILES / name / ".agency" / "key"
    sock = PROFILES / name / ".agency" / "daemon.sock"
    log = PROFILES / name / ".agency" / "logs" / "daemon.log"
    bin_path = PROFILES / name / ".agency" / "bin" / "agentanycastd"

    if not bin_path.exists():
        # Copy binary from hermes profile or download
        hermes_bin = Path.home() / ".hermes" / ".agentanycast" / "bin" / "agentanycastd"
        if hermes_bin.exists():
            bin_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(hermes_bin, bin_path)
            bin_path.chmod(0o755)
        else:
            return None, "no binary"

    # Ensure directories exist
    key.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)

    # Generate key if missing
    if not key.exists():
        # Let the daemon generate it
        pass

    # Start daemon
    cmd = [
        str(bin_path),
        f"--key={key}",
        f"--grpc-listen=unix://{sock}",
        "--log-level=info",
        f"--bootstrap-peers=/ip4/100.123.57.115/tcp/4001/p2p/12D3KooWGE3zmqw2FJTyuNGAzSNCUxSNSeMvCtocULczXfX9Y8nK",
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=open(log, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    # Wait for daemon to start and register
    time.sleep(5)

    # Read peer_id from log
    peer_id = None
    if log.exists():
        for line in log.read_text().splitlines():
            if "peer_id" in line and "12D3KooW" in line:
                import re
                m = re.search(r'"peer_id":"(12D3KooW[^"]+)"', line)
                if m:
                    peer_id = m.group(1)
                    break
                m = re.search(r'peer_id=(12D3KooW\S+)', line)
                if m:
                    peer_id = m.group(1)
                    break

    return peer_id, proc


def sleep_profile(name):
    """Stop a profile's daemon."""
    import signal
    sock = PROFILES / name / ".agency" / "daemon.sock"
    pid_file = PROFILES / name / ".agency" / "daemon.pid"

    # Find and kill the daemon process
    try:
        result = subprocess.run(
            ["pkill", "-f", f"profiles/{name}/.agency/bin/agentanycastd"],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch-wake agency profiles")
    parser.add_argument("--dry-run", action="store_true", help="List profiles without waking")
    parser.add_argument("--batch-size", type=int, default=10, help="Profiles to wake simultaneously")
    parser.add_argument("--set-limit", type=int, help="Update pool max_active_agents config")
    parser.add_argument("--register-only", action="store_true",
                        help="Wake, wait for registration, then sleep (lighter)")
    parser.add_argument("--start-index", type=int, default=0, help="Start from this profile index")
    args = parser.parse_args()

    profiles = get_agency_profiles()
    print(f"Found {len(profiles)} agency profiles")

    if args.dry_run:
        for i, p in enumerate(profiles):
            print(f"  [{i}] {p}")
        return

    venv_python = str(Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python3")

    # Process in batches
    batch_start = args.start_index
    while batch_start < len(profiles):
        batch = profiles[batch_start:batch_start + args.batch_size]
        print(f"\n=== Batch {batch_start // args.batch_size + 1}: "
              f"profiles {batch_start}-{batch_start + len(batch) - 1} ===")

        woken = []
        for name in batch:
            print(f"  Waking {name}...", end=" ", flush=True)
            peer_id, proc = wake_profile(name, venv_python)
            if peer_id:
                print(f"✓ {peer_id[:20]}...")
                woken.append((name, peer_id, proc))
            elif isinstance(proc, str):
                print(f"✗ {proc}")
            else:
                print(f"✗ no peer_id (proc={proc.pid if proc else 'None'})")
                woken.append((name, None, proc))

        if args.register_only:
            # Wait for registration to propagate
            print(f"  Waiting 15s for registration to propagate...")
            time.sleep(15)

            # Sleep all in this batch
            for name, peer_id, proc in woken:
                print(f"  Sleeping {name}...", end=" ", flush=True)
                if proc and hasattr(proc, 'pid'):
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                        print("✓")
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        print("✓ (killed)")
                else:
                    ok = sleep_profile(name)
                    print("✓" if ok else "✗ (not found)")

            print(f"  Batch complete. Waiting 5s before next batch...")
            time.sleep(5)
        else:
            # Keep running — just wait a bit before next batch
            print(f"  Batch woken. Waiting 5s before next batch...")
            time.sleep(5)

        batch_start += args.batch_size

    print(f"\n=== Done! ===")
    total = len(profiles)
    print(f"Processed {total} profiles in {(total + args.batch_size - 1) // args.batch_size} batches")

    if not args.register_only:
        print(f"\nAll daemons are running. To sleep them all later:")
        print(f"  python3 batch_wake.py --sleep-all")


if __name__ == "__main__":
    main()
