#!/usr/bin/env python3
"""Guided operator golden-path checklist for Hermes Agency.

Prints and optionally executes the safe first-run sequence:
  staff starter install (dry-run capable) → doctor → status.

This is an operator helper, not a live multi-process Keryx E2E.
Use scripts/e2e_agency_keryx.py for the Phase 17 transport proof.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, dry_run: bool) -> int:
    printable = " ".join(cmd)
    print(f"$ {printable}")
    if dry_run:
        return 0
    completed = subprocess.run(cmd, cwd=ROOT, check=False)
    return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes Agency operator golden path helper")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip starter staff install steps",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter for hermes-agency module entry",
    )
    args = parser.parse_args()
    py = args.python

    def agency(*parts: str) -> list[str]:
        # Console entry is hermes_agency.cli:main; keep argv forwarding explicit.
        return [
            py,
            "-c",
            (
                "from hermes_agency.cli import main; import sys; "
                "raise SystemExit(main(sys.argv[1:]) or 0)"
            ),
            *parts,
        ]

    steps: list[list[str]] = [agency("--help")]
    if not args.skip_install:
        steps.extend(
            [
                agency("staff", "starter"),
                agency("staff", "install", "--starter", "--dry-run"),
                agency("staff", "install", "--starter"),
                agency("setup-plugins"),
            ]
        )
    steps.extend(
        [
            agency("doctor"),
            agency("status"),
        ]
    )

    print("Hermes Agency operator golden path")
    print("Docs: docs/operator-golden-path.md")
    print()
    failures = 0
    for cmd in steps:
        code = _run(cmd, dry_run=args.dry_run)
        if code != 0:
            failures += 1
            print(f"! command failed with exit {code}")
    print()
    if args.dry_run:
        print("Dry-run complete. Re-run without --dry-run to execute.")
        return 0
    if failures:
        print(f"Completed with {failures} failed step(s).")
        return 1
    print("Golden-path checklist finished. Next:")
    print("  - hermes-agency models plan <set> && hermes-agency models apply <set> --yes --backup")
    print("  - pytest hermes-agency/tests/test_golden_path.py -q")
    print("  - optional live Keryx: python scripts/e2e_agency_keryx.py ...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
