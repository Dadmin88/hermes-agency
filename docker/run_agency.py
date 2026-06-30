#!/usr/bin/env python3
"""Container entrypoint for the full Hermes Agency stack.

Modes:
  setup      Prepare config, install packaged staff profiles, and initialize boards.
  node       Start the local Hermes Agency node manager and keep it alive.
  all        Run setup, then start the node manager.

The entrypoint works with a full Hermes runtime when present and falls back to a
small standalone compatibility layer for local Docker use.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import sys
import time
import types
from pathlib import Path
from typing import Any

from hermes_compat import install as install_compat

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "hermes-agency"
PACKAGE_NAME = "hermes_plugin"


def _load_plugin_module(module_name: str):
    package = sys.modules.get(PACKAGE_NAME)
    if package is None:
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(PLUGIN_ROOT)]  # type: ignore[attr-defined]
        sys.modules[PACKAGE_NAME] = package

    parts = module_name.split(".")
    for index in range(1, len(parts)):
        parent_name = f"{PACKAGE_NAME}." + ".".join(parts[:index])
        if parent_name not in sys.modules:
            parent = types.ModuleType(parent_name)
            parent.__path__ = [str(PLUGIN_ROOT.joinpath(*parts[:index]))]  # type: ignore[attr-defined]
            sys.modules[parent_name] = parent

    full_name = f"{PACKAGE_NAME}.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    path = PLUGIN_ROOT.joinpath(*parts).with_suffix(".py")
    if not path.exists():
        package_path = PLUGIN_ROOT.joinpath(*parts) / "__init__.py"
        if package_path.exists():
            path = package_path
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


def _csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _merge_dict(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_dict(target[key], value)
        else:
            target[key] = value
    return target


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", "/data/hermes")).expanduser()


def configure() -> None:
    """Create a usable container config without overwriting user customizations."""
    home = _hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "profiles").mkdir(parents=True, exist_ok=True)
    config_path = home / "config.yaml"
    config = _load_yaml(config_path)
    orchestrator = os.environ.get("HERMES_AGENCY_ORCHESTRATOR", "agency-orchestrator")
    active_model_set = os.environ.get("HERMES_AGENCY_MODEL_SET", "openai-codex-only")
    patch = {
        "agency": {
            "enabled": True,
            "auto_start": _bool_env("HERMES_AGENCY_AUTO_START", True),
            "allow_remote_tasks": _bool_env("HERMES_AGENCY_ALLOW_REMOTE_TASKS", False),
            "relay": os.environ.get("AGENTANYCAST_RELAY") or None,
            "incoming": {
                "mode": os.environ.get("HERMES_AGENCY_INCOMING_MODE", "delegation"),
                "tool_access": os.environ.get("HERMES_AGENCY_TOOL_ACCESS", "safe"),
                "persist_queue": True,
            },
            "team": {
                "auto_discover": True,
                "kanban_integration": True,
                "self_serve": True,
                "context_filter": "agency-only",
                "tenant": os.environ.get("HERMES_AGENCY_TENANT", "default"),
            },
            "models": {"active_set": active_model_set},
            "orchestrator": {
                "enabled": _bool_env("HERMES_AGENCY_ORCHESTRATOR_ENABLED", True),
                "agent": orchestrator,
                "auto_decompose": True,
            },
        }
    }
    _merge_dict(config, patch)
    _write_yaml(config_path, config)
    print(f"Configured Hermes Agency home at {home}")


def setup() -> None:
    configure()
    default_staff = _load_plugin_module("default_staff")
    names = _csv_env("HERMES_AGENCY_STAFF")
    install_staff = _bool_env("HERMES_AGENCY_INSTALL_STAFF", True)
    if install_staff:
        result = default_staff.install_default_staff(
            names=names or None,
            force=_bool_env("HERMES_AGENCY_FORCE_STAFF", False),
            dry_run=False,
        )
        print(f"Staff install: {result}")

    try:
        plugin_setup = _load_plugin_module("pool.plugin_setup")
        result = plugin_setup.setup_all_profile_plugins()
        print(f"Profile plugin setup: {result}")
    except Exception as exc:
        print(f"Profile plugin setup skipped: {type(exc).__name__}: {exc}")

    try:
        kb = _load_plugin_module("kanban_bridge")
        boards = [
            "engineering",
            "design",
            "content",
            "marketing",
            "operations",
            "quality",
            "management",
            "research",
            "product",
            "business",
        ]
        for board in boards:
            kb.create_task(
                title=f"Initialize {board} board",
                description="Container bootstrap marker task.",
                assigned_to=None,
                metadata={"department": board, "source": "container-bootstrap"},
                priority=0,
            )
        print("Initialized agency Kanban boards")
    except Exception as exc:
        print(f"Kanban initialization skipped: {type(exc).__name__}: {exc}")


def start_node() -> Any | None:
    if not _bool_env("HERMES_AGENCY_START_NODE", True):
        print("Hermes Agency node start disabled by HERMES_AGENCY_START_NODE=0")
        return None
    node_manager = _load_plugin_module("node_manager")
    try:
        state = node_manager.manager.start_sync()
        print(f"Hermes Agency node started={state.started} error={state.error}")
        return node_manager.manager
    except Exception as exc:
        print(f"Hermes Agency node start failed: {type(exc).__name__}: {exc}")
        return None


def wait_forever() -> None:
    stopped = False

    def _stop(_signum: int, _frame: Any) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while not stopped:
        time.sleep(1)


def main() -> None:
    install_compat()
    parser = argparse.ArgumentParser(description="Run Hermes Agency in a container")
    parser.add_argument("mode", nargs="?", default=os.environ.get("HERMES_AGENCY_MODE", "all"))
    args = parser.parse_args()
    mode = args.mode
    if mode == "setup":
        setup()
        return
    if mode == "node":
        setup()
        start_node()
        wait_forever()
        return
    if mode == "all":
        setup()
        start_node()
        wait_forever()
        return
    raise SystemExit(f"Unknown mode: {mode}")


if __name__ == "__main__":
    main()
