#!/usr/bin/env python3
"""Register the temporary Fabric migration scripts outside the product lint surface."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

pyproject = PYPROJECT.read_text(encoding="utf-8")
anchor = '"hermes-agency/tests/test_unit.py" = ["N802"]\n'
lines = (
    '"apps/fabric/scripts/*.py" = ["E", "F", "I", "N", "W", "UP"]\n'
    '"scripts/*fabric*.py" = ["E", "F", "I", "N", "W", "UP"]\n'
)
if lines not in pyproject:
    if anchor not in pyproject:
        raise RuntimeError("Ruff per-file-ignore anchor missing")
    pyproject = pyproject.replace(anchor, anchor + lines, 1)
    PYPROJECT.write_text(pyproject, encoding="utf-8")
    print("Registered Fabric migration tooling lint boundary")
else:
    print("Fabric migration tooling lint boundary already registered")
