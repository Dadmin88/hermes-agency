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
        node_text = (
            "Hermes Agency node restarted."
            if was_started
            else "Hermes Agency node reload requested."
        )
    except Exception as exc:  # pragma: no cover - runtime dependent
        node_text = f"Hermes Agency node restart failed: {type(exc).__name__}: {exc}"
    return (
        node_text
        + " Start a new Hermes session or restart the gateway/desktop session for orch_* tool surface changes."
    )


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


def _staff_list_text(category: str = "") -> str:
    """List available default staff profiles."""
    from .default_staff import list_default_staff

    profiles = list_default_staff()
    if not profiles:
        return "No default staff profiles found. The default_staff directory may be missing."

    cat_filter = (category or "").strip().lower()
    if cat_filter:
        profiles = [p for p in profiles if p.get("category", "").lower() == cat_filter]
        if not profiles:
            return f"No default staff profiles in category '{category}'."

    # Group by category
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for p in profiles:
        cat = p.get("category", "other")
        by_cat.setdefault(cat, []).append(p)

    lines = [f"Default staff profiles ({len(profiles)}):"]
    for cat in sorted(by_cat):
        lines.append(f"\n  [{cat}]")
        for p in sorted(by_cat[cat], key=lambda x: x.get("name", "")):
            name = p.get("name", "?")
            summary = p.get("summary", "")
            short = summary[:80] + "..." if len(summary) > 80 else summary
            lines.append(f"    {name:<40} {short}")
    return "\n".join(lines)


def _staff_install_text(names: list[str], *, dry_run: bool = False, force: bool = False) -> str:
    """Install default staff profiles into local Hermes profiles directory."""
    from .default_staff import install_default_staff

    result = install_default_staff(names=names or None, force=force, dry_run=dry_run)
    if not result.get("ok") and result.get("error"):
        return f"Error: {result['error']}"

    lines = []
    if dry_run:
        lines.append("Dry run — no changes made.")
    installed = result.get("installed", [])
    skipped = result.get("skipped", [])
    errors = result.get("errors", [])

    if installed:
        label = "Would install" if dry_run else "Installed"
        lines.append(f"{label} ({len(installed)}):")
        for item in installed:
            lines.append(f"  + {item}")
    if skipped:
        lines.append(f"Skipped ({len(skipped)}):")
        for item in skipped:
            lines.append(f"  - {item}")
    if errors:
        lines.append(f"Errors ({len(errors)}):")
        for item in errors:
            lines.append(f"  ! {item}")
    if not installed and not skipped and not errors:
        lines.append("Nothing to do.")
    return "\n".join(lines)


def _staff_info_text(name: str) -> str:
    """Show info about a specific default staff profile."""
    from .default_staff import get_profile_info, read_profile_soul

    name = (name or "").strip()
    if not name:
        return "Usage: hermes agency staff info <profile-name>"

    info = get_profile_info(name)
    if info is None:
        return f"Profile '{name}' not found in default staff manifest."

    lines = [
        f"Profile: {info.get('name', name)}",
        f"Display: {info.get('display_name', '-')}",
        f"Category: {info.get('category', '-')}",
        f"Summary: {info.get('summary', '-')}",
        f"Primary role: {info.get('primary_role', '-')}",
    ]
    delegates = info.get("delegates_to", [])
    if delegates:
        lines.append(f"Delegates to: {', '.join(delegates)}")
    tags = info.get("tags", [])
    if tags:
        lines.append(f"Tags: {', '.join(tags)}")

    soul = read_profile_soul(name)
    if soul:
        lines.append("")
        lines.append("--- SOUL.md (excerpt) ---")
        # Show first ~40 lines
        soul_lines = soul.strip().split("\n")
        for line in soul_lines[:40]:
            lines.append(line)
        if len(soul_lines) > 40:
            lines.append(f"... ({len(soul_lines) - 40} more lines)")
    return "\n".join(lines)


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
    if verb == "staff":
        sub = parts[1].lower() if len(parts) > 1 else "list"
        if sub == "list":
            cat = parts[2] if len(parts) > 2 else ""
            return _staff_list_text(category=cat)
        if sub == "install":
            names = [p for p in parts[2:] if not p.startswith("--")]
            dry_run = "--dry-run" in parts
            force = "--force" in parts
            return _staff_install_text(names, dry_run=dry_run, force=force)
        if sub == "info":
            name = parts[2] if len(parts) > 2 else ""
            return _staff_info_text(name)
        return "Usage: /agency staff [list [category]|install [--dry-run] [--force] [names...]|info <name>]"
    return "Usage: /agency [status|start|stop|discover <skill>|promote <agent>|demote <agent>|registry|staff]"


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

    registry_parser = subparsers.add_parser(
        "registry", help="Show live Hermes Agency self-registration records"
    )
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

    staff_parser = subparsers.add_parser(
        "staff",
        help="Manage default agency staff profiles",
    )
    staff_sub = staff_parser.add_subparsers(dest="staff_command")

    staff_list = staff_sub.add_parser("list", help="List available default staff profiles")
    staff_list.add_argument("category", nargs="?", default="", help="Filter by category")
    staff_list.set_defaults(func=cmd_agency, agency_command="staff")

    staff_install = staff_sub.add_parser("install", help="Install default staff profiles")
    staff_install.add_argument(
        "names", nargs="*", default=[], help="Profile names to install (default: all)"
    )
    staff_install.add_argument("--dry-run", action="store_true", help="Preview without installing")
    staff_install.add_argument("--force", action="store_true", help="Overwrite existing profiles")
    staff_install.set_defaults(func=cmd_agency, agency_command="staff")

    staff_info = staff_sub.add_parser("info", help="Show info about a default staff profile")
    staff_info.add_argument("name", help="Profile name (e.g. agency-orchestrator)")
    staff_info.set_defaults(func=cmd_agency, agency_command="staff")


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
    elif verb == "staff":
        staff_cmd = getattr(args, "staff_command", "list") or "list"
        if staff_cmd == "list":
            print(_staff_list_text(getattr(args, "category", "")))
        elif staff_cmd == "install":
            print(
                _staff_install_text(
                    getattr(args, "names", []),
                    dry_run=getattr(args, "dry_run", False),
                    force=getattr(args, "force", False),
                )
            )
        elif staff_cmd == "info":
            print(_staff_info_text(getattr(args, "name", "")))
        else:
            raise SystemExit(f"Unknown staff command: {staff_cmd}")
    else:
        raise SystemExit(f"Unknown agency command: {verb}")
