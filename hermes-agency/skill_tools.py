"""Narrow worker tool surface for profile-local skill acquisition."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .config import get_config
from .skill_governance.hub import HubAcquisitionService
from .skill_governance.profile_scope import resolve_authenticated_profile
from .skill_governance.service import GovernancePaths, SkillGovernanceControlPlane, default_paths

TOOLSET = "agency-skills"
_SERVICES: dict[str, HubAcquisitionService] = {}


class HermesCLIHubSource:
    def search(self, query: str, *, source: str, limit: int) -> list[dict[str, Any]]:
        command = [
            "hermes",
            "skills",
            "search",
            query,
            "--source",
            source,
            "--limit",
            str(limit),
            "--json",
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        payload = json.loads(completed.stdout)
        if not isinstance(payload, list):
            raise ValueError("Hermes skill search returned a non-list payload")
        return [item for item in payload if isinstance(item, dict)][:limit]

    def fetch(self, identifier: str) -> dict[str, Any]:
        """Fetch once into an isolated home; caller freezes these exact bytes."""
        with tempfile.TemporaryDirectory(prefix="agency-skill-inspect-") as raw:
            home = Path(raw)
            env = os.environ.copy()
            env["HERMES_HOME"] = str(home)
            completed = subprocess.run(
                ["hermes", "skills", "install", identifier, "--yes"],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
            if completed.returncode:
                raise RuntimeError(
                    f"Hermes hub install/scanner rejected candidate: {completed.stderr[-500:]}"
                )
            skill_files = [
                path for path in (home / "skills").glob("**/SKILL.md") if ".hub" not in path.parts
            ]
            if len(skill_files) != 1:
                raise RuntimeError("isolated Hermes install did not produce exactly one skill")
            root = skill_files[0].parent
            text = skill_files[0].read_text(encoding="utf-8")
            name = root.name
            if text.startswith("---"):
                import yaml

                loaded = yaml.safe_load(text.split("---", 2)[1]) or {}
                name = str(loaded.get("name") or name)
            files = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in sorted(root.rglob("*"))
                if path.is_file() and not path.is_symlink()
            }
            lock_path = home / "skills" / ".hub" / "lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.is_file() else {}
            return {
                "name": name,
                "source": str(lock.get("source") or "hub"),
                "trust_level": str(lock.get("trust_level") or "untrusted"),
                "revision": lock.get("commit") or lock.get("version") or lock.get("content_hash"),
                "files": files,
            }


def _service(context_profile: str | None = None) -> HubAcquisitionService:
    cfg = get_config().skill_governance
    profile = resolve_authenticated_profile(context_profile=context_profile)
    cached = _SERVICES.get(str(profile.home))
    if cached:
        return cached
    defaults = default_paths()
    paths = GovernancePaths(
        cfg.state_path or defaults.state_root,
        defaults.profiles_root,
        cfg.shared_skills_path.parent if cfg.shared_skills_path else defaults.skills_root,
    )
    service = HubAcquisitionService(
        SkillGovernanceControlPlane(paths, max_pending_bytes=cfg.max_pending_bytes),
        profile,
        HermesCLIHubSource(),
        enabled=cfg.hub_acquisition_enabled,
        max_results=cfg.hub_max_results,
        inspection_ttl_seconds=cfg.hub_inspection_ttl_seconds,
    )
    _SERVICES[str(profile.home)] = service
    return service


def _call(method: str, args: dict[str, Any] | None, kwargs: dict[str, Any]) -> str:
    values = dict(args or {})
    try:
        service = _service(str(kwargs.get("profile") or "") or None)
        if method == "search":
            result = service.search(
                str(values.get("query") or ""),
                source=str(values.get("source") or "all"),
                limit=int(values.get("limit") or 10),
            )
        elif method == "inspect":
            result = service.inspect(
                str(values.get("identifier") or ""),
                task_id=str(values.get("task_id") or kwargs.get("task_id") or ""),
            )
        elif method == "install":
            result = service.install(str(values.get("inspection_token") or ""))
        elif method == "activate":
            result = {"instructions": service.activate(str(values.get("acquisition_id") or ""))}
        elif method == "report":
            result = service.report(
                str(values.get("acquisition_id") or ""),
                outcome=str(values.get("outcome") or ""),
                materiality=list(values.get("materiality") or []),
                summary=str(values.get("summary") or ""),
                validation=list(values.get("validation") or []),
            )
        elif method == "cleanup":
            result = service.cleanup(
                str(values.get("acquisition_id") or ""),
                reason=str(values.get("reason") or "task complete"),
            )
        else:
            result = service.status(str(values.get("acquisition_id") or ""))
        return json.dumps({"ok": True, "result": result}, sort_keys=True, default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True)


def _handler(method):
    return lambda args=None, **kwargs: _call(method, args, kwargs)


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]):
    parameters = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": parameters,
        "function": {"name": name, "description": description, "parameters": parameters},
    }


SKILL_TOOLS = (
    (
        "agency_skill_search",
        _schema(
            "agency_skill_search",
            "Search approved skill registries after checking local/shared capability.",
            {
                "query": {"type": "string"},
                "source": {"type": "string"},
                "limit": {"type": "integer"},
                "task_id": {"type": "string"},
            },
            ["query"],
        ),
        _handler("search"),
        "🔎",
    ),
    (
        "agency_skill_inspect",
        _schema(
            "agency_skill_inspect",
            "Fetch once, scan, and freeze a complete candidate; this does not install it.",
            {"identifier": {"type": "string"}, "task_id": {"type": "string"}},
            ["identifier", "task_id"],
        ),
        _handler("inspect"),
        "🔬",
    ),
    (
        "agency_skill_install",
        _schema(
            "agency_skill_install",
            "Install exact inspected bytes only into the authenticated active worker profile; no force/path/profile controls.",
            {"inspection_token": {"type": "string"}},
            ["inspection_token"],
        ),
        _handler("install"),
        "📥",
    ),
    (
        "agency_skill_activate",
        _schema(
            "agency_skill_activate",
            "Rehash and load exact acquired instructions for the current task.",
            {"acquisition_id": {"type": "string"}},
            ["acquisition_id"],
        ),
        _handler("activate"),
        "▶️",
    ),
    (
        "agency_skill_report",
        _schema(
            "agency_skill_report",
            "Record outcome; only materially helpful use with concrete validation recommends shared promotion.",
            {
                "acquisition_id": {"type": "string"},
                "outcome": {"type": "string"},
                "materiality": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
                "validation": {"type": "array", "items": {"type": "object"}},
            },
            ["acquisition_id", "outcome", "materiality", "summary", "validation"],
        ),
        _handler("report"),
        "📝",
    ),
    (
        "agency_skill_cleanup",
        _schema(
            "agency_skill_cleanup",
            "Remove only receipt-owned unchanged local bytes.",
            {"acquisition_id": {"type": "string"}, "reason": {"type": "string"}},
            ["acquisition_id", "reason"],
        ),
        _handler("cleanup"),
        "🧹",
    ),
    (
        "agency_skill_status",
        _schema(
            "agency_skill_status",
            "Read acquisition receipt/evidence state without raw candidate content.",
            {"acquisition_id": {"type": "string"}},
            ["acquisition_id"],
        ),
        _handler("status"),
        "ℹ️",
    ),
)
