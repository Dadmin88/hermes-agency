#!/usr/bin/env python3
"""Container entrypoint for the Hermes Agency dashboard.

The dashboard source lives in the Hermes plugin directory, which is loaded as a
synthetic package so its relative imports work outside a full Hermes runtime.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "hermes-agency"
PACKAGE_NAME = "hermes_plugin"


def _load_plugin_module(module_name: str):
    package = sys.modules.get(PACKAGE_NAME)
    if package is None:
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(PLUGIN_ROOT)]  # type: ignore[attr-defined]
        sys.modules[PACKAGE_NAME] = package

    full_name = f"{PACKAGE_NAME}.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    path = PLUGIN_ROOT / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(full_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    dashboard = _load_plugin_module("dashboard_server")
    host = os.environ.get("HERMES_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("HERMES_DASHBOARD_PORT", "8765"))
    token = os.environ.get("HERMES_DASHBOARD_TOKEN") or None
    dashboard.start_server(
        host=host,
        port=port,
        open_browser=False,
        allow_lan=_bool_env("HERMES_DASHBOARD_ALLOW_LAN", default=False),
        session_token=token,
    )


if __name__ == "__main__":
    main()
