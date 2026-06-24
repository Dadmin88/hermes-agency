#!/usr/bin/env python3
"""Long-lived per-profile Hermes Agency node runner used by the pool manager."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

PLUGIN_PATH = Path(
    os.environ.get("HERMES_AGENCY_PLUGIN_PATH", "/home/dadmin/.hermes/plugins/hermes-agency")
)
PACKAGE_NAME = "hermes_agency"
DEFAULT_STARTUP_TIMEOUT = 120.0
DEFAULT_CHECK_INTERVAL = 5.0
DEFAULT_RETRY_INTERVAL = 5.0
DEFAULT_PROFILE_NAMES = {"", "default"}


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


def _float_env(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _state_started(state: Any) -> bool:
    return bool(getattr(state, "started", False) and getattr(state, "peer_id", None))


def _state_payload(state: Any) -> dict[str, Any]:
    as_dict = getattr(state, "as_dict", None)
    if callable(as_dict):
        return cast(dict[str, Any], as_dict())
    return {
        "started": getattr(state, "started", False),
        "peer_id": getattr(state, "peer_id", None),
        "error": getattr(state, "error", None),
    }


def _emit(prefix: str, payload: Any) -> None:
    print(f"{prefix} " + json.dumps(payload, default=str), flush=True)



def _current_hermes_home() -> Path:
    """Return the Hermes home visible to this runner before plugin imports."""

    return Path(os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()


def _root_home_for(home: Path) -> Path:
    """Return the root Hermes home for either root or named-profile homes."""

    expanded = home.expanduser()
    if expanded.parent.name == "profiles":
        return expanded.parent.parent
    return expanded


def _minimal_yaml_mapping(text: str) -> dict[str, Any]:
    """Parse the small nested mapping subset needed for root Agency config."""

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        key, sep, value = raw_line.strip().partition(":")
        if not sep or not key:
            continue
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        raw_value = value.strip()
        if not raw_value:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
            continue
        parsed: Any = raw_value.strip("\"'")
        if parsed.lower() in {"null", "none"}:
            parsed = None
        elif parsed.lower() == "true":
            parsed = True
        elif parsed.lower() == "false":
            parsed = False
        parent[key] = parsed
    return root


def _load_yaml_config(path: Path) -> dict[str, Any]:
    """Best-effort YAML config loader used before Hermes modules are imported."""

    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml

        data = yaml.safe_load(text) or {}
    except ModuleNotFoundError:
        data = _minimal_yaml_mapping(text)
    except Exception as exc:
        _emit(
            "HERMES_AGENCY_RUNNER_CONFIG_WARNING",
            {"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
        )
        return {}
    return data if isinstance(data, dict) else {}


def _cfg_get(config: dict[str, Any], *path: str, default: Any = None) -> Any:
    value: Any = config
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _configured_orchestrator_agent(config: dict[str, Any]) -> str:
    agent = str(_cfg_get(config, "agency", "orchestrator", "agent", default="") or "").strip()
    return agent


def _find_orchestrator_agent(root_home: Path, current_home: Path) -> str:
    """Find the configured orchestrator profile without importing plugin modules."""

    candidates = [root_home / "config.yaml"]
    if current_home != root_home:
        candidates.append(current_home / "config.yaml")
    try:
        active_profile = (root_home / "active_profile").read_text(encoding="utf-8").strip()
    except OSError:
        active_profile = ""
    if active_profile and active_profile not in DEFAULT_PROFILE_NAMES:
        candidates.append(root_home / "profiles" / active_profile / "config.yaml")

    seen: set[Path] = set()
    for config_path in candidates:
        if config_path in seen:
            continue
        seen.add(config_path)
        agent = _configured_orchestrator_agent(_load_yaml_config(config_path))
        if agent:
            return agent

    profiles_dir = root_home / "profiles"
    try:
        profile_dirs = sorted(path for path in profiles_dir.iterdir() if path.is_dir())
    except OSError:
        return ""
    for profile_dir in profile_dirs:
        config = _load_yaml_config(profile_dir / "config.yaml")
        enabled = bool(_cfg_get(config, "agency", "orchestrator", "enabled", default=False))
        agent = _configured_orchestrator_agent(config)
        if enabled and agent:
            return agent
    return ""


def _resolve_runner_profile() -> str:
    """Resolve the profile whose config this runner should load.

    Gateway/systemd invocations can start the long-lived runner with
    ``HERMES_HOME`` pointing at the root/default Hermes home. In that case the
    active Agency node should still be the configured orchestrator profile from
    ``agency.orchestrator.agent``, not the root/default node.

    Pool-managed per-agent runners already pass a concrete ``HERMES_PROFILE``;
    those must not be rewritten just because the root config names an
    orchestrator.
    """

    requested_profile = os.environ.get("HERMES_PROFILE", "").strip()
    current_home = _current_hermes_home()
    root_home = _root_home_for(current_home)
    orchestrator_agent = _find_orchestrator_agent(root_home, current_home)
    if not orchestrator_agent:
        return requested_profile

    if requested_profile not in DEFAULT_PROFILE_NAMES and requested_profile != orchestrator_agent:
        return requested_profile

    profile_home = root_home / "profiles" / orchestrator_agent
    os.environ["HERMES_PROFILE"] = orchestrator_agent
    os.environ["HERMES_HOME"] = str(profile_home)
    _emit(
        "HERMES_AGENCY_RUNNER_PROFILE",
        {
            "profile": orchestrator_agent,
            "home": str(profile_home),
            "source": "agency.orchestrator.agent",
        },
    )
    return orchestrator_agent

def _sleep_while_running(seconds: float, should_run: Callable[[], bool]) -> None:
    deadline = time.time() + max(0.0, seconds)
    while should_run() and time.time() < deadline:
        time.sleep(min(0.5, max(0.0, deadline - time.time())))


def _manager_health(manager: Any) -> tuple[bool, str]:
    """Return whether the owned node looks healthy enough to keep serving tasks."""

    try:
        info = manager.compact_info()
    except Exception as exc:
        return False, f"compact_info failed: {type(exc).__name__}: {exc}"
    if not info.get("node_started"):
        return False, "node_started is false"
    if not info.get("serve_task_running"):
        return False, "serve_task_running is false"
    if info.get("ok") is False:
        return False, "manager health ok is false"
    return True, "healthy"


def _start_until_running(
    manager: Any,
    *,
    should_run: Callable[[], bool],
    startup_timeout: float,
    retry_seconds: float,
) -> bool:
    """Start the node, retrying forever until healthy or shutdown is requested."""

    while should_run():
        try:
            state = manager.start_sync(timeout=startup_timeout)
            payload = _state_payload(state)
            _emit("HERMES_AGENCY_NODE_STATE", payload)
            if _state_started(state):
                return True
            reason = payload.get("error") or "state.started/peer_id not set"
            _emit("HERMES_AGENCY_NODE_START_RETRY", {"reason": reason})
        except Exception as exc:
            _emit(
                "HERMES_AGENCY_NODE_START_ERROR",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        _sleep_while_running(retry_seconds, should_run)
    return False


def _restart_node(
    manager: Any,
    *,
    should_run: Callable[[], bool],
    startup_timeout: float,
    retry_seconds: float,
) -> bool:
    """Stop the current node best-effort, then retry startup until it is running."""

    try:
        manager.stop_sync(timeout=60)
    except Exception as exc:
        _emit(
            "HERMES_AGENCY_NODE_STOP_ERROR",
            {"error": f"{type(exc).__name__}: {exc}"},
        )
    return _start_until_running(
        manager,
        should_run=should_run,
        startup_timeout=startup_timeout,
        retry_seconds=retry_seconds,
    )


def main() -> int:
    profile = _resolve_runner_profile()
    if not profile:
        print("HERMES_AGENCY_NODE_ERROR missing HERMES_PROFILE", flush=True)
        return 2

    _load_plugin_package()
    from hermes_agency.node_manager import manager

    running = True

    def _shutdown(signum, frame):  # noqa: ARG001
        nonlocal running
        running = False

    def _should_run() -> bool:
        return running

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    startup_timeout = _float_env("HERMES_AGENCY_RUNNER_STARTUP_TIMEOUT", DEFAULT_STARTUP_TIMEOUT)
    check_interval = _float_env("HERMES_AGENCY_RUNNER_CHECK_SECONDS", DEFAULT_CHECK_INTERVAL)
    retry_seconds = _float_env("HERMES_AGENCY_RUNNER_RETRY_SECONDS", DEFAULT_RETRY_INTERVAL)

    if not _start_until_running(
        manager,
        should_run=_should_run,
        startup_timeout=startup_timeout,
        retry_seconds=retry_seconds,
    ):
        return 0

    while running:
        _sleep_while_running(check_interval, _should_run)
        if not running:
            break
        healthy, reason = _manager_health(manager)
        if healthy:
            continue
        _emit("HERMES_AGENCY_NODE_UNHEALTHY", {"reason": reason})
        if not _restart_node(
            manager,
            should_run=_should_run,
            startup_timeout=startup_timeout,
            retry_seconds=retry_seconds,
        ):
            break

    try:
        manager.stop_sync(timeout=60)
    except Exception as exc:  # pragma: no cover - shutdown best effort
        _emit("HERMES_AGENCY_NODE_STOP_ERROR", {"error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
