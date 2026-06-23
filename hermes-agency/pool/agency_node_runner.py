#!/usr/bin/env python3
"""Long-lived per-profile Hermes Agency node runner used by the pool manager."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import sys
import time
from pathlib import Path

PLUGIN_PATH = Path(
    os.environ.get("HERMES_AGENCY_PLUGIN_PATH", "/home/dadmin/.hermes/plugins/hermes-agency")
)
PACKAGE_NAME = "hermes_agency"


def _load_plugin_package() -> None:
    if PACKAGE_NAME in sys.modules:
        return
    init_py = PLUGIN_PATH / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        init_py,
        submodule_search_locations=[str(PLUGIN_PATH)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Hermes Agency plugin from {init_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)


def main() -> int:
    profile = os.environ.get("HERMES_PROFILE", "").strip()
    if not profile:
        print("HERMES_AGENCY_NODE_ERROR missing HERMES_PROFILE", flush=True)
        return 2

    _load_plugin_package()
    from hermes_agency.node_manager import manager

    running = True

    def _shutdown(signum, frame):  # noqa: ARG001
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        state = manager.start_sync(timeout=120)
        print("HERMES_AGENCY_NODE_STATE " + json.dumps(state.as_dict(), default=str), flush=True)
        if not state.started or not state.peer_id:
            return 1
        while running:
            time.sleep(1)
        try:
            manager.stop_sync(timeout=60)
        except Exception as exc:  # pragma: no cover - shutdown best effort
            print(f"HERMES_AGENCY_NODE_STOP_ERROR {type(exc).__name__}: {exc}", flush=True)
        return 0
    except Exception as exc:
        print(f"HERMES_AGENCY_NODE_ERROR {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
