#!/usr/bin/env python3
"""Apply the one-time PR #84 builder unblock, then remove this helper."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / ".github/workflows/fabric-rebrand-builder.yml"
PYPROJECT = ROOT / "pyproject.toml"
SELF = Path(__file__)
WORKFLOW = ROOT / ".github/workflows/fabric-builder-unblock.yml"

builder = BUILDER.read_text(encoding="utf-8")
start_marker = "      - name: Normalize Python migration tooling\n"
end_marker = "      - name: Normalize workspace lockfile\n"
start = builder.index(start_marker)
end = builder.index(end_marker, start)
builder = builder[:start] + end_marker + builder[end + len(end_marker):]
BUILDER.write_text(builder, encoding="utf-8")

pyproject = PYPROJECT.read_text(encoding="utf-8")n