#!/usr/bin/env python3
"""Three-way merge a normalized upstream update into Hermes Fabric.

The normalized baseline is the merge ancestor, the normalized incoming snapshot
is "theirs", and apps/fabric is "ours". Local-only Hermes files are untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".turbo", ".next"}
LOCAL_ONLY_PREFIXES = {
    ".upstream/",
    "scripts/normalize-upstream-import.py",
    "scripts/merge-upstream-snapshots.py",
}


@dataclass
class Conflict:
    path: str
    reason: str
    artifact: str | None = None


def file_map(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        relative_text = relative.as_posix()
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if any(relative_text == prefix.rstrip("/") or relative_text.startswith(prefix) for prefix in LOCAL_ONLY_PREFIXES):
            continue
        if path.is_symlink():
            result[relative_text] = path
        elif path.is_file():
            result[relative_text] = path
    return result


def bytes_or_none(path: Path | None) -> bytes | None:
    if path is None or not path.exists() or path.is_symlink():
        return None
    return path.read_bytes()


def digest(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def is_binary(content: bytes) -> bool:
    return b"\0" in content[:8192]


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_conflict_artifact(
    conflict_root: Path,
    relative: str,
    current: bytes | None,
    base: bytes | None,
    incoming: bytes | None,
) -> str:
    safe = relative.replace("/", "__")
    folder = conflict_root / safe
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in (("current", current), ("base", base), ("incoming", incoming)):
        if content is not None:
            (folder / name).write_bytes(content)
    return str(folder)


def merge_text(current: bytes, base: bytes, incoming: bytes) -> tuple[bytes | None, str | None]:
    with tempfile.TemporaryDirectory(prefix="fabric-merge-") as temp:
        temp_root = Path(temp)
        current_path = temp_root / "current"
        base_path = temp_root / "base"
        incoming_path = temp_root / "incoming"
        current_path.write_bytes(current)
        base_path.write_bytes(base)
        incoming_path.write_bytes(incoming)
        completed = subprocess.run(
            ["git", "merge-file", "-p", str(current_path), str(base_path), str(incoming_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode == 0:
            return completed.stdout, None
        if completed.returncode == 1:
            return completed.stdout, "text merge conflict"
        return None, completed.stderr.decode("utf-8", errors="replace") or "git merge-file failed"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--incoming", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--conflict-root", required=True, type=Path)
    args = parser.parse_args()

    base_root = args.base.resolve()
    incoming_root = args.incoming.resolve()
    current_root = args.current.resolve()
    report_path = args.report.resolve()
    conflict_root = args.conflict_root.resolve()
    if conflict_root.exists():
        shutil.rmtree(conflict_root)

    base_files = file_map(base_root)
    incoming_files = file_map(incoming_root)
    current_files = file_map(current_root)
    changed_paths = sorted(
        path
        for path in set(base_files) | set(incoming_files)
        if digest(bytes_or_none(base_files.get(path))) != digest(bytes_or_none(incoming_files.get(path)))
        or (base_files.get(path) is not None and base_files[path].is_symlink())
        or (incoming_files.get(path) is not None and incoming_files[path].is_symlink())
    )

    conflicts: list[Conflict] = []
    applied: list[str] = []
    deleted: list[str] = []
    unchanged: list[str] = []

    for relative in changed_paths:
        base_path = base_files.get(relative)
        incoming_path = incoming_files.get(relative)
        current_path = current_files.get(relative)
        output_path = current_root / relative

        if any(path is not None and path.is_symlink() for path in (base_path, incoming_path, current_path)):
            artifact = write_conflict_artifact(
                conflict_root,
                relative,
                bytes_or_none(current_path),
                bytes_or_none(base_path),
                bytes_or_none(incoming_path),
            )
            conflicts.append(Conflict(relative, "symlink changes require manual review", artifact))
            continue

        base = bytes_or_none(base_path)
        incoming = bytes_or_none(incoming_path)
        current = bytes_or_none(current_path)

        if base is None and incoming is not None:
            if current is None:
                ensure_parent(output_path)
                output_path.write_bytes(incoming)
                applied.append(relative)
            elif current == incoming:
                unchanged.append(relative)
            else:
                artifact = write_conflict_artifact(conflict_root, relative, current, base, incoming)
                conflicts.append(Conflict(relative, "upstream addition collides with local file", artifact))
            continue

        if base is not None and incoming is None:
            if current is None:
                unchanged.append(relative)
            elif current == base:
                output_path.unlink()
                deleted.append(relative)
            else:
                artifact = write_conflict_artifact(conflict_root, relative, current, base, incoming)
                conflicts.append(Conflict(relative, "upstream deleted a locally modified file", artifact))
            continue

        assert base is not None and incoming is not None
        if current is None:
            artifact = write_conflict_artifact(conflict_root, relative, current, base, incoming)
            conflicts.append(Conflict(relative, "local file is missing while upstream modified it", artifact))
            continue
        if current == base:
            output_path.write_bytes(incoming)
            applied.append(relative)
            continue
        if current == incoming or incoming == base:
            unchanged.append(relative)
            continue
        if is_binary(base) or is_binary(incoming) or is_binary(current):
            artifact = write_conflict_artifact(conflict_root, relative, current, base, incoming)
            conflicts.append(Conflict(relative, "binary file changed on both sides", artifact))
            continue

        merged, error = merge_text(current, base, incoming)
        if error is None and merged is not None:
            output_path.write_bytes(merged)
            applied.append(relative)
        else:
            artifact = write_conflict_artifact(conflict_root, relative, current, base, incoming)
            if merged is not None:
                (Path(artifact) / "conflicted-merge").write_bytes(merged)
            conflicts.append(Conflict(relative, error or "merge failed", artifact))

    report = {
        "schemaVersion": 1,
        "changedPaths": changed_paths,
        "applied": applied,
        "deleted": deleted,
        "unchanged": unchanged,
        "conflicts": [asdict(item) for item in conflicts],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: len(value) for key, value in report.items() if isinstance(value, list)}, indent=2))
    if conflicts:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
