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

from .doctor import render_doctor_report, run_doctor
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


def _status_extended_text(*, json_output: bool = False) -> str:
    from .extended_status import extended_status, render_extended_status

    payload = extended_status()
    return _json(payload) if json_output else render_extended_status(payload)


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
    if not dry_run:
        lines.append("")
        lines.append(_setup_plugins_text())
    if not installed and not skipped and not errors:
        lines.append("Nothing to do.")
    return "\n".join(lines)


def _setup_plugins_text() -> str:
    """Symlink Hermes Agency into every Hermes profile's plugins directory."""
    from .pool.plugin_setup import setup_all_profile_plugins

    summary = setup_all_profile_plugins(include_main=True)
    lines = [
        "Hermes Agency plugin setup complete.",
        f"  Source: {summary['source']}",
        f"  Profiles scanned: {summary['profiles_total']}",
        f"  Profiles updated: {summary['profiles_updated']}",
        f"  Profiles already linked: {summary['profiles_already']}",
        f"  Profile errors: {summary['profiles_errors']}",
        f"  Main/default plugin: {summary['main_status']} ({summary['main_path']})",
    ]
    if summary.get("errors"):
        lines.append("  Errors:")
        for item in summary["errors"]:
            lines.append(
                f"    ! {item.get('profile')}: {item.get('error', 'unknown error')} "
                f"({item.get('path')})"
            )
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


def _sign_off_board_text(board: str, signed_off_by: str = "") -> str:
    board = (board or "").strip()
    if not board:
        return "Usage: hermes agency sign-off-board <board> [--by <name>]"
    try:
        result = manager.sign_off_board_sync(board, signed_off_by=signed_off_by or None)
    except Exception as exc:  # pragma: no cover - depends on host Kanban install
        return f"Hermes Agency board sign-off failed: {type(exc).__name__}: {exc}"
    if not result.get("ok"):
        return "Hermes Agency board sign-off failed: " + str(result.get("error") or result)
    board_data = result.get("board") or {}
    return (
        f"Board {board_data.get('slug') or board!r} signed off by "
        f"{board_data.get('signed_off_by') or signed_off_by or 'human'}."
    )


def _cleanup_boards_text(days: int | None = None) -> str:
    try:
        result = manager.cleanup_signed_off_boards_sync(older_than_days=days)
    except Exception as exc:  # pragma: no cover - depends on host Kanban install
        return f"Hermes Agency board cleanup failed: {type(exc).__name__}: {exc}"
    archived = result.get("archived") or []
    lines = [
        f"Hermes Agency board cleanup complete (older_than_days={result.get('older_than_days')}).",
        f"  archived: {len(archived)}",
    ]
    for item in archived:
        lines.append(f"    - {item.get('slug')} -> {item.get('new_path')}")
    return "\n".join(lines)


def _models_list_text(*, json_output: bool = False) -> str:
    from .model_sets import active_model_set_name, discover_model_set_files, user_model_sets_dir

    config, _path = _load_user_config()
    active = active_model_set_name(config=config)
    user_dir = user_model_sets_dir()
    items = []
    for name, path in sorted(discover_model_set_files().items()):
        source = "user" if user_dir in path.parents else "packaged"
        items.append({"name": name, "source": source, "path": str(path), "active": name == active})
    if json_output:
        return _json({"active": active, "model_sets": items})
    lines = [f"Hermes Agency model sets (active: {active})"]
    for item in items:
        marker = "*" if item["active"] else " "
        lines.append(f"  {marker} {item['name']:<12} {item['source']:<9} {item['path']}")
    return "\n".join(lines)


def _models_show_text(name: str, *, json_output: bool = False, strict: bool = False) -> str:
    from .model_sets import load_model_set, model_set_summary

    model_set = load_model_set(name)
    summary = model_set_summary(model_set, strict=strict)
    if json_output:
        return _json(summary)
    validation = summary["validation"]
    lines = [
        f"Model set: {summary['name']}",
        f"Description: {summary['description']}",
        f"Source: {summary['source_path']}",
        f"Valid: {validation['ok']}",
        "",
        "Families:",
    ]
    for family, data in summary["families"].items():
        lines.append(
            f"  {family:<16} {data['provider']}/{data['model']} — {data.get('reason') or ''}"
        )
    if summary["profiles"]:
        lines.extend(["", "Explicit profile mappings:"])
        for profile, family in sorted(summary["profiles"].items()):
            lines.append(f"  {profile:<36} {family}")
    if validation["warnings"]:
        lines.extend(["", "Warnings:"] + [f"  - {item}" for item in validation["warnings"]])
    if validation["errors"]:
        lines.extend(["", "Errors:"] + [f"  - {item}" for item in validation["errors"]])
    return "\n".join(lines)


def _models_validate_text(
    name: str, *, json_output: bool = False, strict: bool = False
) -> tuple[str, int]:
    from .model_sets import load_model_set, resolve_roster, validate_model_set

    model_set = load_model_set(name)
    result = validate_model_set(model_set, strict=strict)
    roster = []
    if result.ok:
        try:
            roster = [item.__dict__ for item in resolve_roster(model_set)]
        except Exception as exc:
            result.error(f"Default staff roster resolution failed: {type(exc).__name__}: {exc}")
    payload = {
        "model_set": model_set.name,
        "validation": result.as_dict(),
        "profiles_checked": len(roster),
    }
    if json_output:
        return _json(payload), 0 if result.ok else 2
    lines = [
        f"Model set {model_set.name}: {'ok' if result.ok else 'failed'}",
        f"Profiles checked: {len(roster)}",
    ]
    if result.warnings:
        lines.extend(["Warnings:"] + [f"  - {item}" for item in result.warnings])
    if result.errors:
        lines.extend(["Errors:"] + [f"  - {item}" for item in result.errors])
    return "\n".join(lines), 0 if result.ok else 2


def _models_resolve_text(profile: str, set_name: str = "", *, json_output: bool = False) -> str:
    from .model_sets import active_model_set_name, load_model_set, resolve_profile_model

    config, _path = _load_user_config()
    model_set = load_model_set(active_model_set_name(set_name or None, config=config))
    resolved = resolve_profile_model(profile, model_set)
    payload = resolved.__dict__
    if json_output:
        return _json(payload)
    lines = [
        f"{resolved.profile} -> {resolved.provider}/{resolved.model}",
        f"  model_set: {resolved.source_preset}",
        f"  family: {resolved.family}",
        f"  source: {resolved.resolution_source}",
    ]
    if resolved.reason:
        lines.append(f"  reason: {resolved.reason}")
    if resolved.warnings:
        lines.extend(["  warnings:"] + [f"    - {item}" for item in resolved.warnings])
    return "\n".join(lines)


def _models_plan_text(name: str, *, json_output: bool = False) -> str:
    from .model_sets import active_model_set_name, load_model_set
    from .profile_config_writer import plan_model_set

    config, _path = _load_user_config()
    model_set = load_model_set(active_model_set_name(name or None, config=config))
    results = plan_model_set(model_set)
    payload = {
        "model_set": model_set.name,
        "profiles_checked": len(results),
        "results": [r.as_dict() for r in results],
    }
    if json_output:
        return _json(payload)
    if not results:
        return "No installed agency-* profiles found. Run `hermes agency staff install` first."
    lines = [f"Model-set dry-run plan: {model_set.name}"]
    for result in results:
        lines.append(
            f"  {result.profile:<36} {result.status:<10} {result.current or '-':<30} -> {result.target}"
        )
    return "\n".join(lines)


def _models_use_text(
    name: str, *, apply: bool = False, yes: bool = False, backup: bool = True, dry_run: bool = False
) -> str:
    from .model_sets import load_model_set

    name = load_model_set(name).name
    config, _path = _load_user_config()
    agency = config.setdefault("agency", {})
    if not isinstance(agency, dict):
        agency = {}
        config["agency"] = agency
    models = agency.setdefault("models", {})
    if not isinstance(models, dict):
        models = {}
        agency["models"] = models
    models["active_set"] = name
    path = _save_user_config(config)
    lines = [f"Set agency.models.active_set={name!r} in {path}."]
    if apply:
        lines.append(_models_apply_text(name, dry_run=dry_run, yes=yes, backup=backup))
    else:
        lines.append(f"Next: hermes agency models plan {name}")
    return "\n".join(lines)


def _models_apply_text(
    name: str,
    *,
    dry_run: bool = True,
    yes: bool = False,
    backup: bool = True,
    profiles: list[str] | None = None,
    json_output: bool = False,
) -> str:
    from .model_sets import load_model_set
    from .profile_config_writer import apply_model_set

    model_set = load_model_set(name)
    payload = apply_model_set(model_set, profiles=profiles, dry_run=dry_run, yes=yes, backup=backup)
    if json_output:
        return _json(payload)
    lines = [f"Model-set apply {'dry-run' if dry_run else 'complete'}: {model_set.name}"]
    if payload.get("message"):
        lines.append(str(payload["message"]))
    if payload.get("backup_id"):
        lines.append(f"Backup ID: {payload['backup_id']}")
    for item in payload.get("results", []):
        lines.append(
            f"  {item['profile']:<36} {item['status']:<10} {item.get('current') or '-':<30} -> {item.get('target')}"
        )
    return "\n".join(lines)


def _models_restore_text(backup_id: str, *, force: bool = False, json_output: bool = False) -> str:
    from .profile_config_writer import restore_backup

    payload = restore_backup(backup_id, force=force)
    if json_output:
        return _json(payload)
    lines = [f"Restore backup {backup_id}: {'ok' if payload.get('ok') else 'failed'}"]
    for item in payload.get("restored", []):
        lines.append(f"  restored {item['profile']} from {item['backup_path']}")
    for error in payload.get("errors", []):
        lines.append(f"  ! {error}")
    return "\n".join(lines)


def _gpt_bridge_format_task(task: dict[str, Any]) -> str:
    task_id = str(task.get("task_id") or "-")
    status = str(task.get("status") or "unknown")
    urgency = str(task.get("urgency") or "normal")
    source = str(task.get("source_profile") or "-")
    description = str(task.get("task_description") or "").strip()
    if len(description) > 120:
        description = description[:119].rstrip() + "…"
    return f"  {task_id:<28} {status:<10} {urgency:<8} {source:<28} {description}"


def _gpt_bridge_inbox_text(
    *, status: str = "", limit: int = 25, include_terminal: bool = True, json_output: bool = False
) -> str:
    from .gpt_bridge import list_tasks

    payload = list_tasks(status=status or None, include_terminal=include_terminal, limit=limit)
    if json_output:
        return _json(payload)
    tasks = payload.get("tasks") or []
    lines = [f"GPT bridge inbox ({len(tasks)} task(s))", f"  dir: {payload.get('dir')}"]
    if not tasks:
        lines.append("  No matching tasks.")
        return "\n".join(lines)
    lines.append(
        "  task_id                      status     urgency  source                       description"
    )
    for task in tasks:
        lines.append(_gpt_bridge_format_task(task))
    return "\n".join(lines)


def _gpt_bridge_show_text(task_id: str, *, json_output: bool = False) -> str:
    from .gpt_bridge import get_task

    payload = get_task(task_id)
    if json_output:
        return _json(payload)
    if not payload.get("ok"):
        return f"Error: {payload.get('error')}"
    task = payload.get("task") or {}
    lines = [
        f"Task: {task.get('task_id')}",
        f"Status: {task.get('status')}",
        f"Urgency: {task.get('urgency')}",
        f"Source: {task.get('source_profile')}",
        f"Created: {task.get('created_at')}",
        "",
        "Description:",
        str(task.get("task_description") or ""),
    ]
    if task.get("reason"):
        lines.extend(["", "Reason:", str(task.get("reason"))])
    if task.get("expected_output"):
        lines.extend(["", "Expected output:", str(task.get("expected_output"))])
    if task.get("result"):
        lines.extend(["", "Result:", str(task.get("result"))])
    if task.get("error"):
        lines.extend(["", "Error:", str(task.get("error"))])
    return "\n".join(lines)


def _gpt_bridge_claim_text(
    task_id: str, *, claimed_by: str = "ChatGPT", json_output: bool = False
) -> str:
    from .gpt_bridge import claim_task

    payload = claim_task(task_id, claimed_by=claimed_by)
    if json_output:
        return _json(payload)
    if not payload.get("ok"):
        return f"Error: {payload.get('error')}"
    task = payload.get("task") or {}
    return f"Claimed {task.get('task_id')} as {task.get('claimed_by')}."


def _gpt_bridge_complete_text(
    task_id: str, result: str, *, completed_by: str = "ChatGPT", json_output: bool = False
) -> str:
    from .gpt_bridge import complete_task

    payload = complete_task(task_id, result, completed_by=completed_by)
    if json_output:
        return _json(payload)
    if not payload.get("ok"):
        return f"Error: {payload.get('error')}"
    task = payload.get("task") or {}
    return f"Completed {task.get('task_id')}."


def _gpt_bridge_fail_text(
    task_id: str, error: str, *, failed_by: str = "ChatGPT", json_output: bool = False
) -> str:
    from .gpt_bridge import fail_task

    payload = fail_task(task_id, error, failed_by=failed_by)
    if json_output:
        return _json(payload)
    if not payload.get("ok"):
        return f"Error: {payload.get('error')}"
    task = payload.get("task") or {}
    return f"Failed {task.get('task_id')}: {task.get('error')}"


def _gpt_bridge_status_text(*, json_output: bool = False) -> str:
    from .gpt_bridge import summary

    payload = summary()
    if json_output:
        return _json(payload)
    counts = payload.get("counts") or {}
    parts = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"
    return (
        f"GPT bridge status: total={payload.get('total', 0)}; {parts}\n  dir: {payload.get('dir')}"
    )


def _discord_poll_text(
    *, limit: int = 25, dry_run: bool = False, ack: bool = True, json_output: bool = False
) -> str:
    from .discord_intake import poll_discord_tasks, render_poll_result

    payload = poll_discord_tasks(limit=limit, dry_run=dry_run, ack=ack)
    return _json(payload) if json_output else render_poll_result(payload)


def handle_agency_slash(raw_args: str = "") -> str:
    """Handle the in-session ``/agency`` slash command."""

    parts = (raw_args or "").strip().split()
    if not parts:
        return _status_text()

    verb = parts[0].lower()
    if verb == "status":
        return (
            _status_extended_text(json_output="--json" in parts)
            if "--extended" in parts
            else _status_text()
        )
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
    if verb == "doctor":
        return render_doctor_report(run_doctor(), json_output="--json" in parts[1:])
    if verb == "models":
        sub = parts[1].lower() if len(parts) > 1 else "list"
        json_output = "--json" in parts
        strict = "--strict" in parts
        if sub == "list":
            return _models_list_text(json_output=json_output)
        if sub == "show":
            return _models_show_text(
                parts[2] if len(parts) > 2 else "", json_output=json_output, strict=strict
            )
        if sub == "validate":
            text, _code = _models_validate_text(
                parts[2] if len(parts) > 2 else "", json_output=json_output, strict=strict
            )
            return text
        if sub == "resolve":
            set_name = ""
            if "--set" in parts:
                idx = parts.index("--set")
                if len(parts) > idx + 1:
                    set_name = parts[idx + 1]
            return _models_resolve_text(
                parts[2] if len(parts) > 2 else "", set_name=set_name, json_output=json_output
            )
        if sub == "plan":
            return _models_plan_text(parts[2] if len(parts) > 2 else "", json_output=json_output)
        if sub == "use":
            return _models_use_text(
                parts[2] if len(parts) > 2 else "",
                apply="--apply" in parts,
                yes="--yes" in parts,
                dry_run="--dry-run" in parts,
                backup="--no-backup" not in parts,
            )
        if sub == "apply":
            names = [p for p in parts[3:] if not p.startswith("--")]
            profiles = None
            if "--profiles" in parts:
                idx = parts.index("--profiles")
                if len(parts) > idx + 1:
                    profiles = [p.strip() for p in parts[idx + 1].split(",") if p.strip()]
            return _models_apply_text(
                parts[2] if len(parts) > 2 else "",
                dry_run="--dry-run" in parts or "--yes" not in parts,
                yes="--yes" in parts,
                backup="--no-backup" not in parts,
                profiles=profiles or names or None,
                json_output=json_output,
            )
        if sub == "restore":
            backup_id = ""
            if "--backup-id" in parts:
                idx = parts.index("--backup-id")
                if len(parts) > idx + 1:
                    backup_id = parts[idx + 1]
            return _models_restore_text(
                backup_id, force="--force" in parts, json_output=json_output
            )
        return "Usage: /agency models [list|show|validate|resolve|plan|use|apply|restore]"
    if verb == "discord":
        sub = parts[1].lower() if len(parts) > 1 else "poll"
        json_output = "--json" in parts
        if sub in {"poll", "intake"}:
            limit = 25
            if "--limit" in parts:
                idx = parts.index("--limit")
                if len(parts) > idx + 1:
                    try:
                        limit = int(parts[idx + 1])
                    except ValueError:
                        return "Usage: /agency discord poll [--limit N] [--dry-run] [--no-ack] [--json]"
            return _discord_poll_text(
                limit=limit,
                dry_run="--dry-run" in parts,
                ack="--no-ack" not in parts,
                json_output=json_output,
            )
        return "Usage: /agency discord poll [--limit N] [--dry-run] [--no-ack] [--json]"
    if verb == "gpt-bridge":
        sub = parts[1].lower() if len(parts) > 1 else "inbox"
        json_output = "--json" in parts
        if sub in {"inbox", "list"}:
            status = ""
            limit = 25
            if "--status" in parts:
                idx = parts.index("--status")
                if len(parts) > idx + 1:
                    status = parts[idx + 1]
            if "--limit" in parts:
                idx = parts.index("--limit")
                if len(parts) > idx + 1:
                    try:
                        limit = int(parts[idx + 1])
                    except ValueError:
                        return "Usage: /agency gpt-bridge inbox [--status status] [--limit N]"
            return _gpt_bridge_inbox_text(
                status=status,
                limit=limit,
                include_terminal="--active" not in parts,
                json_output=json_output,
            )
        if sub == "show":
            return _gpt_bridge_show_text(
                parts[2] if len(parts) > 2 else "", json_output=json_output
            )
        if sub == "claim":
            return _gpt_bridge_claim_text(
                parts[2] if len(parts) > 2 else "", json_output=json_output
            )
        if sub == "complete":
            task_id = parts[2] if len(parts) > 2 else ""
            result = " ".join(p for p in parts[3:] if p != "--json")
            return _gpt_bridge_complete_text(task_id, result, json_output=json_output)
        if sub == "fail":
            task_id = parts[2] if len(parts) > 2 else ""
            error = " ".join(p for p in parts[3:] if p != "--json")
            return _gpt_bridge_fail_text(task_id, error, json_output=json_output)
        if sub == "status":
            return _gpt_bridge_status_text(json_output=json_output)
        return "Usage: /agency gpt-bridge [inbox|show|claim|complete|fail|status]"
    if verb == "sign-off-board":
        signed_off_by = ""
        if "--by" in parts:
            idx = parts.index("--by")
            signed_off_by = " ".join(parts[idx + 1 :])
            board = " ".join(parts[1:idx])
        else:
            board = " ".join(parts[1:])
        return _sign_off_board_text(board, signed_off_by=signed_off_by)
    if verb == "cleanup-boards":
        days = None
        if "--days" in parts:
            idx = parts.index("--days")
            if len(parts) > idx + 1:
                try:
                    days = int(parts[idx + 1])
                except ValueError:
                    return "Usage: /agency cleanup-boards [--days N]"
        return _cleanup_boards_text(days)
    if verb == "setup-plugins":
        return _setup_plugins_text()
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
    return "Usage: /agency [status|start|stop|discover <skill>|doctor [--json]|setup-plugins|promote <agent>|demote <agent>|registry|sign-off-board <board>|cleanup-boards [--days N]|staff]"


def setup_agency_parser(parser: ArgumentParser) -> None:
    """Configure ``hermes agency`` argparse subcommands."""

    parser.set_defaults(func=cmd_agency, agency_command="status")
    subparsers = parser.add_subparsers(dest="agency_command")

    status_parser = subparsers.add_parser("status", help="Show Hermes Agency node status")
    status_parser.add_argument(
        "--extended",
        action="store_true",
        help="Show department, throughput, roster, and bridge health",
    )
    status_parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON with --extended"
    )
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

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run Hermes Agency self-diagnostics",
        description="Check Hermes Agency plugin health and print actionable remediation.",
    )
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    doctor_parser.set_defaults(func=cmd_agency)

    setup_plugins_parser = subparsers.add_parser(
        "setup-plugins",
        help="Symlink Hermes Agency into every Hermes profile",
        description="Ensure all ~/.hermes/profiles/*/plugins/hermes-agency links exist.",
    )
    setup_plugins_parser.set_defaults(func=cmd_agency)

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

    signoff_parser = subparsers.add_parser(
        "sign-off-board",
        help="Mark an Agency task board as human-signed-off",
    )
    signoff_parser.add_argument("board", help="Agency Kanban board slug")
    signoff_parser.add_argument("--by", default="", help="Human/reviewer name")
    signoff_parser.set_defaults(func=cmd_agency)

    cleanup_boards_parser = subparsers.add_parser(
        "cleanup-boards",
        help="Archive signed-off Agency boards older than the cleanup window",
    )
    cleanup_boards_parser.add_argument(
        "--days", type=int, default=None, help="Override agency.kanban.board_cleanup_days"
    )
    cleanup_boards_parser.set_defaults(func=cmd_agency)

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

    models_parser = subparsers.add_parser("models", help="Manage Hermes Agency model sets")
    models_sub = models_parser.add_subparsers(dest="models_command")

    models_list = models_sub.add_parser("list", help="List available model sets")
    models_list.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    models_list.set_defaults(func=cmd_agency, agency_command="models")

    models_show = models_sub.add_parser("show", help="Show a model set")
    models_show.add_argument("name", help="Model set name")
    models_show.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    models_show.add_argument("--strict", action="store_true", help="Treat unknown models as errors")
    models_show.set_defaults(func=cmd_agency, agency_command="models")

    models_validate = models_sub.add_parser("validate", help="Validate a model set")
    models_validate.add_argument("name", help="Model set name")
    models_validate.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    models_validate.add_argument(
        "--strict", action="store_true", help="Treat unknown models as errors"
    )
    models_validate.set_defaults(func=cmd_agency, agency_command="models")

    models_resolve = models_sub.add_parser("resolve", help="Resolve one profile's target model")
    models_resolve.add_argument("profile", help="Profile name, e.g. agency-backend-engineer")
    models_resolve.add_argument("--set", default="", help="Model set name")
    models_resolve.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    models_resolve.set_defaults(func=cmd_agency, agency_command="models")

    models_plan = models_sub.add_parser(
        "plan", help="Dry-run all installed agency profile model changes"
    )
    models_plan.add_argument("name", help="Model set name")
    models_plan.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    models_plan.set_defaults(func=cmd_agency, agency_command="models")

    models_use = models_sub.add_parser("use", help="Set agency.models.active_set in active config")
    models_use.add_argument("name", help="Model set name")
    models_use.add_argument(
        "--apply", action="store_true", help="Also apply to installed agency profiles"
    )
    models_use.add_argument("--dry-run", action="store_true", help="Preview apply without writing")
    models_use.add_argument("--yes", action="store_true", help="Confirm non-dry-run apply")
    models_use.add_argument(
        "--no-backup", action="store_true", help="Skip config backups during apply"
    )
    models_use.set_defaults(func=cmd_agency, agency_command="models")

    models_apply = models_sub.add_parser(
        "apply", help="Apply a model set to installed agency profile configs"
    )
    models_apply.add_argument("name", help="Model set name")
    models_apply.add_argument("--dry-run", action="store_true", help="Preview without writing")
    models_apply.add_argument("--yes", action="store_true", help="Confirm non-dry-run bulk apply")
    models_apply.add_argument("--backup", action="store_true", help="Create backups before writing")
    models_apply.add_argument("--no-backup", action="store_true", help="Do not create backups")
    models_apply.add_argument("--profiles", default="", help="Comma-separated profile list")
    models_apply.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    models_apply.set_defaults(func=cmd_agency, agency_command="models")

    models_restore = models_sub.add_parser("restore", help="Restore model config backups")
    models_restore.add_argument("--backup-id", required=True, help="Backup ID returned by apply")
    models_restore.add_argument(
        "--force", action="store_true", help="Ignore backup metadata path mismatch"
    )
    models_restore.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    models_restore.set_defaults(func=cmd_agency, agency_command="models")

    discord_parser = subparsers.add_parser(
        "discord", help="Poll Discord channel messages into agency tasks"
    )
    discord_sub = discord_parser.add_subparsers(dest="discord_command")
    discord_poll = discord_sub.add_parser("poll", help="Poll Discord for !agency task messages")
    discord_poll.add_argument(
        "--limit", type=int, default=25, help="Maximum recent Discord messages to inspect"
    )
    discord_poll.add_argument(
        "--dry-run", action="store_true", help="Preview matching messages without queueing tasks"
    )
    discord_poll.add_argument(
        "--no-ack", action="store_true", help="Do not post queued acknowledgements back to Discord"
    )
    discord_poll.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    discord_poll.set_defaults(func=cmd_agency, agency_command="discord")

    gpt_bridge_parser = subparsers.add_parser(
        "gpt-bridge", help="Manage the pull-based ChatGPT bridge inbox"
    )
    gpt_bridge_sub = gpt_bridge_parser.add_subparsers(dest="gpt_bridge_command")

    gpt_inbox = gpt_bridge_sub.add_parser("inbox", help="List GPT bridge inbox tasks")
    gpt_inbox.add_argument("--status", default="", help="Filter by task status")
    gpt_inbox.add_argument("--limit", type=int, default=25, help="Maximum tasks to show")
    gpt_inbox.add_argument(
        "--active", action="store_true", help="Hide completed/failed/cancelled tasks"
    )
    gpt_inbox.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    gpt_inbox.set_defaults(func=cmd_agency, agency_command="gpt-bridge")

    gpt_show = gpt_bridge_sub.add_parser("show", help="Show one GPT bridge task")
    gpt_show.add_argument("task_id", help="GPT bridge task ID")
    gpt_show.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    gpt_show.set_defaults(func=cmd_agency, agency_command="gpt-bridge")

    gpt_claim = gpt_bridge_sub.add_parser("claim", help="Claim one GPT bridge task")
    gpt_claim.add_argument("task_id", help="GPT bridge task ID")
    gpt_claim.add_argument("--by", default="ChatGPT", help="Claimant label")
    gpt_claim.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    gpt_claim.set_defaults(func=cmd_agency, agency_command="gpt-bridge")

    gpt_complete = gpt_bridge_sub.add_parser("complete", help="Complete one GPT bridge task")
    gpt_complete.add_argument("task_id", help="GPT bridge task ID")
    gpt_complete.add_argument("result", nargs="*", help="Completion result text")
    gpt_complete.add_argument("--result-file", default="", help="Read completion result from file")
    gpt_complete.add_argument("--by", default="ChatGPT", help="Completer label")
    gpt_complete.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    gpt_complete.set_defaults(func=cmd_agency, agency_command="gpt-bridge")

    gpt_fail = gpt_bridge_sub.add_parser("fail", help="Mark one GPT bridge task failed")
    gpt_fail.add_argument("task_id", help="GPT bridge task ID")
    gpt_fail.add_argument("error", nargs="*", help="Failure reason")
    gpt_fail.add_argument("--by", default="ChatGPT", help="Failure reporter label")
    gpt_fail.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    gpt_fail.set_defaults(func=cmd_agency, agency_command="gpt-bridge")

    gpt_status = gpt_bridge_sub.add_parser("status", help="Summarize GPT bridge inbox status")
    gpt_status.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    gpt_status.set_defaults(func=cmd_agency, agency_command="gpt-bridge")

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Start the local Hermes Agency dashboard",
        description="Launch a local web dashboard for Hermes Agency.",
    )
    dashboard_parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)"
    )
    dashboard_parser.add_argument(
        "--port", type=int, default=8765, help="Port to bind (default: 8765)"
    )
    dashboard_parser.add_argument(
        "--no-open", action="store_true", help="Do not open browser automatically"
    )
    dashboard_parser.add_argument(
        "--allow-lan", action="store_true", help="Allow LAN access (not recommended)"
    )
    dashboard_parser.set_defaults(func=cmd_agency)

    roster_parser = subparsers.add_parser("roster", help="Show agency pool roster")
    roster_parser.add_argument("query", nargs="?", default="", help="Filter by name/skill")
    roster_parser.set_defaults(func=cmd_agency, agency_command="roster")

    wake_parser = subparsers.add_parser("wake", help="Wake an agency agent")
    wake_parser.add_argument("agent", help="Agent name (e.g. agency-frontend-engineer)")
    wake_parser.set_defaults(func=cmd_agency, agency_command="wake")

    sleep_parser = subparsers.add_parser("sleep", help="Sleep an agency agent")
    sleep_parser.add_argument("agent", help="Agent name")
    sleep_parser.set_defaults(func=cmd_agency, agency_command="sleep")


def cmd_agency(args: Namespace) -> None:
    """Dispatch ``hermes agency`` verbs."""

    verb = getattr(args, "agency_command", "status") or "status"
    if verb == "status":
        print(
            _status_extended_text(json_output=getattr(args, "json", False))
            if getattr(args, "extended", False)
            else _status_text()
        )
    elif verb == "start":
        print(_start_text())
    elif verb == "stop":
        print(_stop_text())
    elif verb == "discover":
        print(_discover_text(getattr(args, "skill", "")))
    elif verb == "registry":
        print(_json(manager.info().get("registration") or {}))
    elif verb == "doctor":
        report = run_doctor()
        print(render_doctor_report(report, json_output=getattr(args, "json", False)))
        if report.exit_code:
            raise SystemExit(report.exit_code)
    elif verb == "setup-plugins":
        print(_setup_plugins_text())
    elif verb == "promote":
        print(_promote_text(getattr(args, "agent", "")))
    elif verb == "demote":
        print(_demote_text(getattr(args, "agent", "")))
    elif verb == "sign-off-board":
        print(_sign_off_board_text(getattr(args, "board", ""), getattr(args, "by", "")))
    elif verb == "cleanup-boards":
        print(_cleanup_boards_text(getattr(args, "days", None)))
    elif verb == "models":
        models_cmd = getattr(args, "models_command", "list") or "list"
        if models_cmd == "list":
            print(_models_list_text(json_output=getattr(args, "json", False)))
        elif models_cmd == "show":
            print(
                _models_show_text(
                    getattr(args, "name", ""),
                    json_output=getattr(args, "json", False),
                    strict=getattr(args, "strict", False),
                )
            )
        elif models_cmd == "validate":
            text, code = _models_validate_text(
                getattr(args, "name", ""),
                json_output=getattr(args, "json", False),
                strict=getattr(args, "strict", False),
            )
            print(text)
            if code:
                raise SystemExit(code)
        elif models_cmd == "resolve":
            print(
                _models_resolve_text(
                    getattr(args, "profile", ""),
                    set_name=getattr(args, "set", ""),
                    json_output=getattr(args, "json", False),
                )
            )
        elif models_cmd == "plan":
            print(
                _models_plan_text(
                    getattr(args, "name", ""), json_output=getattr(args, "json", False)
                )
            )
        elif models_cmd == "use":
            print(
                _models_use_text(
                    getattr(args, "name", ""),
                    apply=getattr(args, "apply", False),
                    yes=getattr(args, "yes", False),
                    dry_run=getattr(args, "dry_run", False),
                    backup=not getattr(args, "no_backup", False),
                )
            )
        elif models_cmd == "apply":
            profiles_arg = getattr(args, "profiles", "") or ""
            profiles = [p.strip() for p in profiles_arg.split(",") if p.strip()] or None
            dry_run = getattr(args, "dry_run", False) or not getattr(args, "yes", False)
            backup = not getattr(args, "no_backup", False)
            print(
                _models_apply_text(
                    getattr(args, "name", ""),
                    dry_run=dry_run,
                    yes=getattr(args, "yes", False),
                    backup=backup,
                    profiles=profiles,
                    json_output=getattr(args, "json", False),
                )
            )
        elif models_cmd == "restore":
            print(
                _models_restore_text(
                    getattr(args, "backup_id", ""),
                    force=getattr(args, "force", False),
                    json_output=getattr(args, "json", False),
                )
            )
        else:
            raise SystemExit(f"Unknown models command: {models_cmd}")
    elif verb == "discord":
        discord_cmd = getattr(args, "discord_command", "poll") or "poll"
        if discord_cmd == "poll":
            print(
                _discord_poll_text(
                    limit=getattr(args, "limit", 25),
                    dry_run=getattr(args, "dry_run", False),
                    ack=not getattr(args, "no_ack", False),
                    json_output=getattr(args, "json", False),
                )
            )
        else:
            raise SystemExit(f"Unknown discord command: {discord_cmd}")
    elif verb == "gpt-bridge":
        bridge_cmd = getattr(args, "gpt_bridge_command", "inbox") or "inbox"
        if bridge_cmd == "inbox":
            print(
                _gpt_bridge_inbox_text(
                    status=getattr(args, "status", ""),
                    limit=getattr(args, "limit", 25),
                    include_terminal=not getattr(args, "active", False),
                    json_output=getattr(args, "json", False),
                )
            )
        elif bridge_cmd == "show":
            print(
                _gpt_bridge_show_text(
                    getattr(args, "task_id", ""), json_output=getattr(args, "json", False)
                )
            )
        elif bridge_cmd == "claim":
            print(
                _gpt_bridge_claim_text(
                    getattr(args, "task_id", ""),
                    claimed_by=getattr(args, "by", "ChatGPT"),
                    json_output=getattr(args, "json", False),
                )
            )
        elif bridge_cmd == "complete":
            result_text = " ".join(getattr(args, "result", []) or [])
            if getattr(args, "result_file", ""):
                from pathlib import Path

                result_text = (
                    Path(getattr(args, "result_file")).expanduser().read_text(encoding="utf-8")
                )
            print(
                _gpt_bridge_complete_text(
                    getattr(args, "task_id", ""),
                    result_text,
                    completed_by=getattr(args, "by", "ChatGPT"),
                    json_output=getattr(args, "json", False),
                )
            )
        elif bridge_cmd == "fail":
            print(
                _gpt_bridge_fail_text(
                    getattr(args, "task_id", ""),
                    " ".join(getattr(args, "error", []) or []),
                    failed_by=getattr(args, "by", "ChatGPT"),
                    json_output=getattr(args, "json", False),
                )
            )
        elif bridge_cmd == "status":
            print(_gpt_bridge_status_text(json_output=getattr(args, "json", False)))
        else:
            raise SystemExit(f"Unknown gpt-bridge command: {bridge_cmd}")
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
    elif verb == "roster":
        from .pool.roster import load_roster

        roster = load_roster()
        query = getattr(args, "query", "")
        profiles = roster["profiles"]
        if query:
            q = query.lower()
            profiles = [
                p
                for p in profiles
                if q in p["name"].lower() or any(q in s.lower() for s in p.get("skills", []))
            ]
        print(f"Pool roster: {roster['online']}/{roster['total']} online")
        for p in profiles:
            status = "ONLINE" if p["online"] else "OFFLINE"
            skills = ", ".join(p.get("skills", [])[:5])
            line = f"  {p['name']} — skills: {skills} [{status}]"
            if p.get("online") and p.get("peer_id"):
                line += f" peer_id: {p['peer_id']}"
            elif p.get("last_seen"):
                line += f" last_seen: {p['last_seen']}"
            print(line)
    elif verb == "wake":
        from .pool.tools import pool_wake

        print(pool_wake(getattr(args, "agent", "")))
    elif verb == "sleep":
        from .pool.tools import pool_sleep

        print(pool_sleep(getattr(args, "agent", "")))
    elif verb == "dashboard":
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8765)
        no_open = getattr(args, "no_open", False)
        allow_lan = getattr(args, "allow_lan", False)

        # Safety check: refuse 0.0.0.0 without explicit confirmation.
        if host == "0.0.0.0" and not allow_lan:
            raise SystemExit(
                "ERROR: Binding to 0.0.0.0 exposes the dashboard to your entire network. "
                "This is a security risk. Use --host 127.0.0.1 (default) for local-only "
                "access, or pass --allow-lan to confirm you want LAN access."
            )

        try:
            from .dashboard_server import start_server

            start_server(
                host=host,
                port=port,
                open_browser=not no_open,
                allow_lan=allow_lan,
            )
        except FileNotFoundError as exc:
            raise SystemExit(f"ERROR: {exc}") from exc
        except OSError as exc:
            if "address already in use" in str(exc).lower() or exc.errno == 98:
                raise SystemExit(
                    f"ERROR: Port {port} is already in use. "
                    f"Try a different port with --port, or stop the other process."
                ) from exc
            raise
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc
    else:
        raise SystemExit(f"Unknown agency command: {verb}")
