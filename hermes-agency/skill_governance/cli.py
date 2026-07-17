"""Conservative operator command surface for skill governance."""

from __future__ import annotations

import json
from argparse import ArgumentParser, Namespace
from typing import Any

from ..config import get_config
from .migration import apply_migration, plan_migration
from .service import GovernancePaths, SkillGovernanceControlPlane, default_paths


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _control_plane() -> SkillGovernanceControlPlane:
    config = get_config().skill_governance
    paths = default_paths()
    state_root = config.state_path or paths.state_root
    shared_path = config.shared_skills_path or paths.shared_skills_path
    paths = GovernancePaths(state_root, paths.profiles_root, shared_path)
    return SkillGovernanceControlPlane(paths, max_pending_bytes=config.max_pending_bytes)


def setup_parser(parent: ArgumentParser) -> None:
    sub = parent.add_subparsers(dest="skill_governance_command")
    status = sub.add_parser("status", help="Show durable governance status")
    status.add_argument("--json", action="store_true")
    scan = sub.add_parser("scan", help="Run one reconciliation scan when governance is enabled")
    scan.add_argument("--json", action="store_true")
    proposals = sub.add_parser("proposals", help="List bounded proposal metadata")
    proposals.add_argument("--state", default="")
    proposals.add_argument("--limit", type=int, default=100)
    proposals.add_argument("--json", action="store_true")
    show = sub.add_parser("show", help="Show one proposal without raw content")
    show.add_argument("proposal_id")
    show.add_argument("--json", action="store_true")
    migrate = sub.add_parser("migrate", help="Plan/apply/restore profile gate wiring")
    migrate_sub = migrate.add_subparsers(dest="migration_command")
    plan = migrate_sub.add_parser("plan", help="Dry-run profile migration")
    plan.add_argument("--profiles", default="")
    plan.add_argument("--json", action="store_true")
    apply = migrate_sub.add_parser("apply", help="Apply migration with backups")
    apply.add_argument("--profiles", default="")
    apply.add_argument("--yes", action="store_true")
    apply.add_argument("--json", action="store_true")
    restore = migrate_sub.add_parser("restore", help="Restore a migration backup")
    restore.add_argument("migration_id")
    restore.add_argument("--yes", action="store_true")
    restore.add_argument("--json", action="store_true")


def _profiles(args: Namespace) -> list[str] | None:
    return [
        item.strip() for item in str(getattr(args, "profiles", "")).split(",") if item.strip()
    ] or None


def dispatch(args: Namespace) -> str:
    command = getattr(args, "skill_governance_command", None) or "status"
    if command == "status":
        plane = _control_plane()
        payload = plane.status()
    elif command == "scan":
        if not get_config().skill_governance.enabled:
            payload = {
                "ok": False,
                "error": "agency.skill_governance.enabled is false; no scan performed",
            }
        else:
            plane = _control_plane()
            payload = {"ok": True, **plane.scan()}
    elif command == "proposals":
        plane = _control_plane()
        payload = plane.store.list(
            state=getattr(args, "state", "") or None, limit=getattr(args, "limit", 100)
        )
    elif command == "show":
        plane = _control_plane()
        payload = plane.store.get(getattr(args, "proposal_id", "")) or {
            "error": "proposal not found"
        }
    elif command == "migrate":
        plane = _control_plane()
        paths = plane.paths
        shared = paths.shared_skills_path
        backups = paths.state_root / "config-backups"
        migration_command = getattr(args, "migration_command", None) or "plan"
        if migration_command == "plan":
            plans = plan_migration(paths.profiles_root, shared, _profiles(args))
            payload = {
                "ok": not any(plan.status == "error" for plan in plans),
                "dry_run": True,
                "results": [plan.as_dict() for plan in plans],
            }
        elif migration_command == "apply":
            if args.yes:
                payload = {
                    "ok": False,
                    "error": "apply requires the authenticated promoter service",
                }
            else:
                payload = apply_migration(
                    paths.profiles_root, shared, backups, profiles=_profiles(args), dry_run=True
                )
        elif migration_command == "restore":
            payload = {"ok": False, "error": "restore requires the authenticated promoter service"}
        else:
            raise ValueError(f"unknown migration command: {migration_command}")
    else:
        raise ValueError(f"unknown skill governance command: {command}")
    if getattr(args, "json", False):
        return _json(payload)
    if isinstance(payload, list):
        return (
            "\n".join(
                f"{item['proposal_id']} {item['state']} {item['skill_name']}" for item in payload
            )
            or "No proposals."
        )
    return _json(payload)
