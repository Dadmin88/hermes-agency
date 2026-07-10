#!/usr/bin/env python3
"""Deterministic tests for Hermes Fabric upstream sync tooling."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
NORMALIZER = SCRIPT_DIR / "normalize-upstream-import.py"
MERGER = SCRIPT_DIR / "merge-upstream-snapshots.py"


def run(command: list[str], *, env: dict[str, str] | None = None, expected: int = 0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, text=True, capture_output=True, env=env)
    if completed.returncode != expected:
        raise AssertionError(
            f"command returned {completed.returncode}, expected {expected}: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def normalizer_env() -> dict[str, str]:
    env = dict(os.environ)
    env["FABRIC_UPSTREAM_LEGACY_ALIASES"] = "LegacyBoard,LegacyBoardAI"
    env["FABRIC_UPSTREAM_LEGACY_SCOPES"] = "@legacyboard"
    return env


def test_normalizer() -> None:
    with tempfile.TemporaryDirectory(prefix="fabric-normalizer-test-") as temp:
        root = Path(temp)
        (root / "docs").mkdir()
        (root / "docs" / "LegacyBoard.md").write_text(
            "# LegacyBoard\n\nUse `@legacyboard/server` with `LEGACY_BOARD_HOME`.\n",
            encoding="utf-8",
        )
        (root / "package.json").write_text(
            json.dumps({"name": "@legacyboard/server", "description": "LegacyBoard operator UI"}) + "\n",
            encoding="utf-8",
        )
        run([sys.executable, str(NORMALIZER), "--root", str(root)], env=normalizer_env())
        paths = [path.relative_to(root).as_posix() for path in root.rglob("*")]
        assert not any("legacyboard" in path.lower() for path in paths)
        content = "\n".join(
            path.read_text(encoding="utf-8")
            for path in root.rglob("*")
            if path.is_file()
        )
        assert "LegacyBoard" not in content
        assert "legacyboard" not in content.lower()
        assert "Hermes Fabric" in content
        assert "@hermes-fabric/server" in content
        assert "HERMES_FABRIC" in content


def write_snapshot(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_clean_three_way_merge() -> None:
    with tempfile.TemporaryDirectory(prefix="fabric-merge-test-") as temp:
        temp_root = Path(temp)
        base = temp_root / "base"
        incoming = temp_root / "incoming"
        current = temp_root / "current"
        for root in (base, incoming, current):
            root.mkdir()
        write_snapshot(base, {"src/value.txt": "header\nmiddle\nfooter\n", "delete.txt": "delete me\n"})
        write_snapshot(incoming, {"src/value.txt": "header\nmiddle\nupstream footer\n", "added.txt": "new\n"})
        write_snapshot(current, {"src/value.txt": "local header\nmiddle\nfooter\n", "delete.txt": "delete me\n", "local.txt": "keep\n"})
        report = temp_root / "report.json"
        conflicts = temp_root / "conflicts"
        run([
            sys.executable,
            str(MERGER),
            "--base", str(base),
            "--incoming", str(incoming),
            "--current", str(current),
            "--report", str(report),
            "--conflict-root", str(conflicts),
        ])
        merged = (current / "src/value.txt").read_text(encoding="utf-8")
        assert "local header" in merged
        assert "upstream footer" in merged
        assert not (current / "delete.txt").exists()
        assert (current / "added.txt").read_text(encoding="utf-8") == "new\n"
        assert (current / "local.txt").read_text(encoding="utf-8") == "keep\n"
        assert json.loads(report.read_text())["conflicts"] == []


def test_conflict_report() -> None:
    with tempfile.TemporaryDirectory(prefix="fabric-conflict-test-") as temp:
        temp_root = Path(temp)
        base = temp_root / "base"
        incoming = temp_root / "incoming"
        current = temp_root / "current"
        for root in (base, incoming, current):
            root.mkdir()
        write_snapshot(base, {"same.txt": "value=base\n"})
        write_snapshot(incoming, {"same.txt": "value=incoming\n"})
        write_snapshot(current, {"same.txt": "value=current\n"})
        report = temp_root / "report.json"
        conflicts = temp_root / "conflicts"
        run([
            sys.executable,
            str(MERGER),
            "--base", str(base),
            "--incoming", str(incoming),
            "--current", str(current),
            "--report", str(report),
            "--conflict-root", str(conflicts),
        ], expected=2)
        payload = json.loads(report.read_text())
        assert len(payload["conflicts"]) == 1
        assert payload["conflicts"][0]["path"] == "same.txt"
        assert conflicts.exists()


def main() -> None:
    test_normalizer()
    test_clean_three_way_merge()
    test_conflict_report()
    print("Hermes Fabric upstream sync tests passed")


if __name__ == "__main__":
    main()
