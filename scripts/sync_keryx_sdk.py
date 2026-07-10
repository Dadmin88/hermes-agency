#!/usr/bin/env python3
"""Synchronize a reviewed Hermes Keryx Python SDK revision into Hermes Agency."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "keryx"


def copy_sdk(source: Path, revision: str) -> None:
    source = source.resolve()
    if not (source / "__init__.py").is_file():
        raise SystemExit(f"Keryx package root is invalid: {source}")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(
        source,
        TARGET,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )
    manifest = {
        "schemaVersion": 1,
        "sourceRepository": "DeployFaith/hermes-keryx",
        "sourceRevision": revision,
        "sourcePath": "sdk/python/keryx",
    }
    (TARGET / "_sync_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def verify_tree() -> None:
    required = [
        "client.py",
        "node.py",
        "task.py",
        "models.py",
        "proto/hermes/keryx/v1/daemon_pb2.py",
        "proto/hermes/keryx/v1/daemon_pb2_grpc.py",
        "proto/hermes/keryx/v1/result_pb2.py",
        "proto/hermes/keryx/v1/relay_pb2.py",
    ]
    missing = [relative for relative in required if not (TARGET / relative).is_file()]
    if missing:
        raise SystemExit(f"synchronized Keryx SDK is incomplete: {missing}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    copy_sdk(args.source, args.revision.strip())
    verify_tree()
    print(f"Synchronized Keryx SDK {args.revision.strip()} into {TARGET}")


if __name__ == "__main__":
    main()
