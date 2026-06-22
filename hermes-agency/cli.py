"""CLI and slash command handlers for the Hermes Agency Hermes plugin."""

from __future__ import annotations

import json
import time
from argparse import ArgumentParser, Namespace
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - Hermes normally depends on PyYAML
    yaml = None  # type: ignore[assignment]

from .node_manager import manager


def _format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m {secs}s"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def _load_user_config() -> tuple[dict[str, Any], Any]:
    """Load the raw user config so promote/demote do not dump merged defaults."""

    if yaml is None:
        raise RuntimeError("PyYAML is required to edit config.yaml")
    from hermes_cli.config import get_config_path

    path = get_config_path()
    if not path.exists():
        return {}, path
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}, path


def _save_user_config(config: dict[str, Any]) -> Any:
    from hermes_cli.config import ensure_hermes_home, get_config_path
    from utils import atomic_yaml_write

    ensure_hermes_home()
    path = get_config_path()
    atomic_yaml_write(path, config, sort_keys=False)
    return path


def _set_orchestrator_config(agent: str | None, *, enabled: bool) -> Any:
    config, _path = _load_user_config()
    agency = config.setdefault("agency", {})
    if not isinstance(agency, dict):
        agency = {}
        config["agency"] = agency
    orchestrator = agency.setdefault("orchestrator", {})
    if not isinstance(orchestrator, dict):
        orchestrator = {}
        agency["orchestrator"] = orchestrator
    orchestrator["enabled"] = bool(enabled)
    orchestrator["agent"] = agent if agent else None
    orchestrator.setdefault("auto_decompose", True)
    return _save_user_config(config)


def _restart_after_promotion_change() -> str:
    """Restart the local node if possible; a fresh Hermes session exposes tool changes."""

    try:
        was_started = bool(manager.info().get("started"))
        if was_started:
            manager.stop_sync(timeout=60)
        manager.auto_start_if_configured()
        node_text = "Hermes Agency node restarted." if was_started else "Hermes Agency node reload requested."
    except Exception as exc:  # pragma: no cover - runtime dependent
        node_text = f"Hermes Agency node restart failed: {type(exc).__name__}: {exc}"
    return node_text + " Start a new Hermes session or restart the gateway/desktop session for orch_* tool surface changes."


def _promote_text(agent: str) -> str:
    agent = (agent or "").strip()
    if not agent:
        return "Usage: hermes agency promote <agent>"
    path = _set_orchestrator_config(agent, enabled=True)
    return f"Promoted {agent} as Hermes Agency orchestrator in {path}.\n{_restart_after_promotion_change()}"


def _demote_text(agent: str) -> str:
    agent = (agent or "").strip()
    if not agent:
        return "Usage: hermes agency demote <agent>"
    path = _set_orchestrator_config(None, enabled=False)
    return f"Demoted {agent}; cleared Hermes Agency orchestrator config in {path}.\n{_restart_after_promotion_change()}"


def _peer_label(peer: Any) -> str:
    if isinstance(peer, dict):
        peer_id = peer.get("peer_id") or peer.get("id") or peer.get("did") or "unknown"
        card = peer.get("card") or {}
        name = card.get("name") if isinstance(card, dict) else None
        skills = card.get("skills") if isinstance(card, dict) else None
        skill_count = len(skills) if isinstance(skills, list) else None
        suffixes = []
        if name:
            suffixes.append(str(name))
        if skill_count is not None:
            suffixes.append(f"{skill_count} skill(s)")
        return f"{peer_id}" + (f" ({', '.join(suffixes)})" if suffixes else "")
    return str(peer)


def _status_text() -> str:
    info = manager.info()
    try:
        peers = manager.list_peers_sync()
        peers_error = None
    except Exception as exc:  # pragma: no cover - depends on daemon/runtime state
        peers = []
        peers_error = f"{type(exc).__name__}: {exc}"

    started_at = info.get("started_at")
    uptime = time.time() - float(started_at) if info.get("started") and started_at else None
    cfg = info.get("config") or {}

    lines = [
        "Hermes Agency status",
        f"  enabled: {cfg.get('enabled')}",
        f"  started: {info.get('started')}",
        f"  peer_id: {info.get('peer_id') or info.get('last_peer_id') or '-'}",
        f"  DID: {info.get('did_key') or '-'}",
        f"  card: {info.get('card_name') or '-'} ({info.get('skill_count', 0)} skill(s))",
        f"  uptime: {_format_duration(uptime)}",
        f"  serve_task_running: {info.get('serve_task_running')}",
        "  incoming queue:",
        f"    records: {info.get('incoming_task_count', 0)}",
        f"    queued: {info.get('incoming_queue_size', 0)}",
        f"    processing: {info.get('incoming_processing_count', 0)}",
        f"    completed: {info.get('incoming_completed_count', 0)}",
        f"    failed: {info.get('incoming_failed_count', 0)}",
        f"  connected peers: {len(peers)}",
    ]
    for peer in peers:
        lines.append(f"    - {_peer_label(peer)}")
    if peers_error:
        lines.append(f"  peer list error: {peers_error}")
    if info.get("last_status"):
        lines.append(f"  last status: {info['last_status']}")
    if info.get("error"):
        lines.append(f"  error: {info['error']}")
    return "\n".join(lines)


def _start_text() -> str:
    try:
        state = manager.start_sync()
        status = "started" if state.started and state.error is None else "not started"
        lines = [f"Hermes Agency node {status}.", _status_text()]
        if state.error:
            lines.append(f"Start error: {state.error}")
        return "\n".join(lines)
    except Exception as exc:  # pragma: no cover - depends on daemon/runtime state
        return f"Hermes Agency start failed: {type(exc).__name__}: {exc}\n\n{_status_text()}"


def _stop_text() -> str:
    try:
        state = manager.stop_sync()
        lines = ["Hermes Agency node stopped.", _status_text()]
        if state.error:
            lines.append(f"Stop error: {state.error}")
        return "\n".join(lines)
    except Exception as exc:  # pragma: no cover - depends on daemon/runtime state
        return f"Hermes Agency stop failed: {type(exc).__name__}: {exc}\n\n{_status_text()}"


def _discover_text(skill: str) -> str:
    skill = (skill or "").strip()
    if not skill:
        return "Usage: /agency discover <skill>"
    try:
        agents = manager.discover_sync(skill=skill)
        lines = [f"Hermes Agency discovery for skill '{skill}': {len(agents)} result(s)"]
        if agents:
            lines.append(_json(agents))
        return "\n".join(lines)
    except Exception as exc:  # pragma: no cover - depends on daemon/runtime state
        return (
            f"Hermes Agency discovery failed for skill '{skill}': "
            f"{type(exc).__name__}: {exc}\n\n{_status_text()}"
        )


def handle_agency_slash(raw_args: str = "") -> str:
    """Handle the in-session ``/agency`` slash command."""

    parts = (raw_args or "").strip().split()
    if not parts:
        return _status_text()

    verb = parts[0].lower()
    if verb == "status":
        return _status_text()
    if verb == "start":
        return _start_text()
    if verb == "stop":
        return _stop_text()
    if verb == "discover":
        return _discover_text(" ".join(parts[1:]))
    if verb == "promote":
        return _promote_text(" ".join(parts[1:]))
    if verb == "demote":
        return _demote_text(" ".join(parts[1:]))
    if verb == "registry":
        return _json(manager.info().get("registration") or {})
    return "Usage: /agency [status|start|stop|discover <skill>|promote <agent>|demote <agent>|registry]"


def setup_agency_parser(parser: ArgumentParser) -> None:
    """Configure ``hermes agency`` argparse subcommands."""

    parser.set_defaults(func=cmd_agency, agency_command="status")
    subparsers = parser.add_subparsers(dest="agency_command")

    status_parser = subparsers.add_parser("status", help="Show Hermes Agency node status")
    status_parser.set_defaults(func=cmd_agency)

    start_parser = subparsers.add_parser("start", help="Start the Hermes Agency node")
    start_parser.set_defaults(func=cmd_agency)

    stop_parser = subparsers.add_parser("stop", help="Stop the Hermes Agency node")
    stop_parser.set_defaults(func=cmd_agency)

    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover agents offering a skill",
    )
    discover_parser.add_argument("skill", help="Skill ID/name to discover")
    discover_parser.set_defaults(func=cmd_agency)

    registry_parser = subparsers.add_parser("registry", help="Show live Hermes Agency self-registration records")
    registry_parser.set_defaults(func=cmd_agency)

    promote_parser = subparsers.add_parser(
        "promote",
        help="Promote a Hermes profile as the Hermes Agency orchestrator",
    )
    promote_parser.add_argument("agent", help="Hermes profile name to promote")
    promote_parser.set_defaults(func=cmd_agency)

    demote_parser = subparsers.add_parser(
        "demote",
        help="Demote/clear the configured Hermes Agency orchestrator",
    )
    demote_parser.add_argument("agent", help="Hermes profile name to demote")
    demote_parser.set_defaults(func=cmd_agency)


def cmd_agency(args: Namespace) -> None:
    """Dispatch ``hermes agency`` verbs."""

    verb = getattr(args, "agency_command", "status") or "status"
    if verb == "status":
        print(_status_text())
    elif verb == "start":
        print(_start_text())
    elif verb == "stop":
        print(_stop_text())
    elif verb == "discover":
        print(_discover_text(getattr(args, "skill", "")))
    elif verb == "registry":
        print(_json(manager.info().get("registration") or {}))
    elif verb == "promote":
        print(_promote_text(getattr(args, "agent", "")))
    elif verb == "demote":
        print(_demote_text(getattr(args, "agent", "")))
    else:
        raise SystemExit(f"Unknown agency command: {verb}")
