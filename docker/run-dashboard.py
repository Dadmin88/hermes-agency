#!/usr/bin/env python3
"""Backward-compatible dashboard-only container entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_agency import main  # type: ignore  # noqa: E402

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "dashboard", *sys.argv[1:]]
    main()
