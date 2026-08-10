#!/usr/bin/env python3
"""Install the Hermes Agency profile pack into Hermes Agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "agency.json"

def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)

def main() -> int:
    parser = argparse.ArgumentParser(description="Install all or selected Hermes Agency profiles.")
    parser.add_argument("profiles", nargs="*", help="Profile names to install. Omit to install the complete Agency.")
    parser.add_argument("--force", action="store_true", help="Re-apply distributions over existing profiles.")
    args = parser.parse_args()

    hermes = shutil.which("hermes")
    if not hermes:
        print("error: 'hermes' was not found on PATH", file=sys.stderr)
        return 2

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    catalog = {item["name"]: item for item in manifest["profiles"]}
    requested = args.profiles or list(catalog)
    unknown = [name for name in requested if name not in catalog]
    if unknown:
        print("error: unknown profile(s): " + ", ".join(sorted(unknown)), file=sys.stderr)
        print("available: " + ", ".join(catalog), file=sys.stderr)
        return 2

    for name in requested:
        item = catalog[name]
        source = ROOT / item["path"]
        if not (source / "distribution.yaml").is_file():
            print(f"error: invalid profile distribution: {source}", file=sys.stderr)
            return 2

        cmd = [hermes, "profile", "install", str(source), "--alias", "--yes"]
        if args.force:
            cmd.append("--force")
        print(f"\n==> Installing {name}")
        run(cmd)
        run([hermes, "profile", "describe", name, "--text", item["description"]])

    print(f"\nInstalled {len(requested)} Hermes Agency profile(s).")
    print(f"Orchestrator: {manifest['orchestrator']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
