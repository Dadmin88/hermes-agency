"""Disabled-by-default profile-local hub acquisition lifecycle."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import stat
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .profile_scope import ProfileScope
from .service import SkillGovernanceControlPlane
from .validation import (
    _copy_regular_tree,
    canonical_json,
    tree_manifest,
    validate_candidate,
    validate_skill_name,
)


class HubSource(Protocol):
    def search(self, query: str, *, source: str, limit: int) -> list[dict[str, Any]]: ...
    def fetch(self, identifier: str) -> dict[str, Any]: ...


class HubAcquisitionService:
    def __init__(
        self,
        control_plane: SkillGovernanceControlPlane,
        profile: ProfileScope,
        source: HubSource,
        *,
        enabled: bool = False,
        max_results: int = 25,
        inspection_ttl_seconds: int = 600,
    ):
        self.control_plane = control_plane
        self.profile = profile
        self.source = source
        self.enabled = enabled
        self.max_results = max(1, min(max_results, 25))
        self.inspection_ttl_seconds = max(60, min(inspection_ttl_seconds, 3600))
        self.root = profile.home / ".agency" / "skill-acquisition"
        self.db_path = control_plane.paths.state_root / "governance.sqlite3"
        self._secret = secrets.token_bytes(32)
        if enabled:
            agency_root = self._local_directory(".agency", create=True)
            self.root = agency_root / "skill-acquisition"
            self.root.mkdir(exist_ok=True, mode=0o700)
            if self.root.is_symlink() or self.root.resolve(strict=True).parent != agency_root:
                raise PermissionError("skill acquisition root escapes the active profile")
            self._initialize()

    def _gate(self) -> None:
        if not self.enabled:
            raise PermissionError("hub acquisition is disabled")
        info = self.profile.home.stat()
        if (info.st_dev, info.st_ino, info.st_uid) != (
            self.profile.device,
            self.profile.inode,
            self.profile.uid,
        ):
            raise PermissionError("authenticated profile root changed")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def _local_directory(self, relative: str, *, create: bool = False) -> Path:
        path = self.profile.home / relative
        if create:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise PermissionError(f"profile-local {relative} root must be a non-symlink directory")
        if path.resolve(strict=True).parent != self.profile.home.resolve(strict=True):
            raise PermissionError(f"profile-local {relative} root escapes the active profile")
        return path

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS hub_acquisitions(
                  acquisition_id TEXT PRIMARY KEY,source_profile TEXT NOT NULL,task_id TEXT NOT NULL,
                  identifier TEXT NOT NULL,source TEXT NOT NULL,trust_level TEXT,upstream_revision TEXT,
                  bundle_digest TEXT NOT NULL,name TEXT NOT NULL,bundle_path TEXT NOT NULL,
                  installed_relpath TEXT,installed_digest TEXT,state TEXT NOT NULL,token_hash TEXT NOT NULL,
                  token_expires REAL NOT NULL,created_at REAL NOT NULL,activated_at REAL,terminal_at REAL,
                  UNIQUE(source_profile,task_id,identifier,bundle_digest));
                CREATE TABLE IF NOT EXISTS hub_evidence(
                  evidence_id TEXT PRIMARY KEY,acquisition_id TEXT NOT NULL,task_id TEXT NOT NULL,
                  outcome TEXT NOT NULL,materiality_json TEXT NOT NULL,summary TEXT NOT NULL,
                  validation_json TEXT NOT NULL,evidence_digest TEXT NOT NULL UNIQUE,proposal_id TEXT,
                  created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS hub_feedback(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,acquisition_id TEXT NOT NULL,code TEXT NOT NULL,
                  message TEXT NOT NULL,created_at REAL NOT NULL,acknowledged_at REAL);
                """
            )

    def search(self, query: str, *, source: str = "all", limit: int = 10) -> list[dict[str, Any]]:
        self._gate()
        query = query.strip()
        if (
            not query
            or len(query) > 200
            or source not in {"all", "skills-sh", "github", "official"}
        ):
            raise ValueError("invalid hub search")
        return self.source.search(query, source=source, limit=max(1, min(limit, self.max_results)))

    def inspect(self, identifier: str, *, task_id: str) -> dict[str, Any]:
        self._gate()
        if not task_id or not identifier or "://" in identifier:
            raise ValueError("task_id and non-URL identifier are required")
        bundle = self.source.fetch(identifier)
        files = bundle.get("files")
        if not isinstance(files, dict) or "SKILL.md" not in files:
            raise ValueError("hub source did not return a complete skill bundle")
        acquisition_id = f"hsa_{uuid.uuid4().hex}"
        agency_root = self._local_directory(".agency", create=True)
        acquisition_root = agency_root / "skill-acquisition"
        acquisition_root.mkdir(exist_ok=True, mode=0o700)
        quarantine = acquisition_root / "quarantine"
        quarantine.mkdir(exist_ok=True, mode=0o700)
        if quarantine.is_symlink() or quarantine.resolve(strict=True).parent != acquisition_root:
            raise PermissionError("quarantine root escapes the active profile")
        bundle_dir = quarantine / acquisition_id
        bundle_dir.mkdir(parents=True, mode=0o700)
        try:
            for raw_path, raw_data in files.items():
                path = PurePosixPath(str(raw_path))
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or any(part in {"", "."} for part in path.parts)
                ):
                    raise ValueError("hub bundle contains an unsafe path")
                data = raw_data if isinstance(raw_data, bytes) else str(raw_data).encode()
                target = bundle_dir.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(
                    target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                )
                try:
                    os.write(descriptor, data)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        except Exception:
            shutil.rmtree(bundle_dir, ignore_errors=True)
            raise
        name = validate_skill_name(bundle.get("name"))
        result = validate_candidate(bundle_dir, name, "create")
        if not result.valid or not result.candidate_digest:
            shutil.rmtree(bundle_dir, ignore_errors=True)
            raise PermissionError(f"hub bundle failed scanner: {[f.code for f in result.findings]}")
        token_nonce = secrets.token_urlsafe(24)
        expires = time.time() + self.inspection_ttl_seconds
        material = f"{self.profile.name}\0{task_id}\0{identifier}\0{result.candidate_digest}\0{expires}\0{token_nonce}"
        proof = hmac.new(self._secret, material.encode(), hashlib.sha256).hexdigest()
        token = f"{acquisition_id}.{expires:.6f}.{token_nonce}.{proof}"
        with self._connect() as db:
            db.execute(
                "INSERT INTO hub_acquisitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    acquisition_id,
                    self.profile.name,
                    task_id,
                    identifier,
                    str(bundle.get("source") or "unknown"),
                    str(bundle.get("trust_level") or "untrusted"),
                    str(bundle.get("revision") or f"sha256:{result.candidate_digest}"),
                    result.candidate_digest,
                    name,
                    str(bundle_dir),
                    None,
                    None,
                    "INSPECTED",
                    hashlib.sha256(token.encode()).hexdigest(),
                    expires,
                    time.time(),
                    None,
                    None,
                ),
            )
        return {
            "acquisition_id": acquisition_id,
            "name": name,
            "candidate_digest": result.candidate_digest,
            "upstream_revision": str(bundle.get("revision") or f"sha256:{result.candidate_digest}"),
            "inspection_token": token,
            "manifest": tree_manifest(bundle_dir)[0],
        }

    def _row_for_token(self, token: str) -> sqlite3.Row:
        acquisition_id = token.split(".", 1)[0]
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM hub_acquisitions WHERE acquisition_id=?", (acquisition_id,)
            ).fetchone()
        if (
            not row
            or row["token_hash"] != hashlib.sha256(token.encode()).hexdigest()
            or row["token_expires"] <= time.time()
        ):
            raise PermissionError("inspection token is invalid or expired")
        if row["source_profile"] != self.profile.name:
            raise PermissionError("acquisition belongs to another profile")
        return row

    def install(self, inspection_token: str) -> dict[str, Any]:
        self._gate()
        row = self._row_for_token(inspection_token)
        source = Path(row["bundle_path"])
        _, digest = tree_manifest(source)
        if digest != row["bundle_digest"]:
            raise ValueError("inspected bundle changed")
        destination = self._local_directory("skills", create=True) / row["name"]
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("local skill name already exists")
        shared = self.control_plane.paths.skills_root / "shared" / row["name"]
        if shared.exists():
            raise FileExistsError("shared skill name already exists")
        temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        _copy_regular_tree(source, temp)
        os.replace(temp, destination)
        _, installed_digest = tree_manifest(destination)
        with self._connect() as db:
            db.execute(
                "UPDATE hub_acquisitions SET state='ACQUIRED',installed_relpath=?,installed_digest=? WHERE acquisition_id=?",
                (
                    destination.relative_to(self.profile.home).as_posix(),
                    installed_digest,
                    row["acquisition_id"],
                ),
            )
        return {
            "acquisition_id": row["acquisition_id"],
            "state": "ACQUIRED",
            "installed_digest": installed_digest,
        }

    def activate(self, acquisition_id: str) -> str:
        self._gate()
        row = self.status(acquisition_id)
        if row["source_profile"] != self.profile.name or row["state"] not in {
            "ACQUIRED",
            "ACTIVATED",
        }:
            raise PermissionError("acquisition is not activatable by this profile")
        path = self.profile.home / row["installed_relpath"]
        _, digest = tree_manifest(path)
        if digest != row["installed_digest"]:
            raise ValueError("installed skill drifted")
        with self._connect() as db:
            db.execute(
                "UPDATE hub_acquisitions SET state='ACTIVATED',activated_at=? WHERE acquisition_id=?",
                (time.time(), acquisition_id),
            )
        return (path / "SKILL.md").read_text(encoding="utf-8")

    def report(
        self,
        acquisition_id: str,
        *,
        outcome: str,
        materiality: list[str],
        summary: str,
        validation: list[dict[str, str]],
    ) -> dict[str, Any]:
        self._gate()
        if outcome not in {"helped", "partial", "no_help", "harmful"}:
            raise ValueError("invalid outcome")
        row = self.status(acquisition_id)
        if row["source_profile"] != self.profile.name or row["state"] != "ACTIVATED":
            raise PermissionError("only the activating profile may report")
        allowed_materiality = {"blocker_resolved", "quality_gain", "time_saved", "error_prevented"}
        material = sorted(set(materiality) & allowed_materiality)
        concrete = [
            item
            for item in validation
            if item.get("kind") in {"test", "command", "artifact", "review"}
            and item.get("result") in {"pass", "fail", "mixed"}
            and item.get("ref")
        ]
        recommend = (
            outcome == "helped" and bool(material) and bool(concrete) and bool(summary.strip())
        )
        evidence = {
            "acquisition_id": acquisition_id,
            "task_id": row["task_id"],
            "outcome": outcome,
            "materiality": material,
            "summary": summary.strip()[:1000],
            "validation": concrete,
        }
        evidence_digest = hashlib.sha256(canonical_json(evidence)).hexdigest()
        proposal_id = None
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO hub_evidence VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    f"hse_{uuid.uuid4().hex}",
                    acquisition_id,
                    row["task_id"],
                    outcome,
                    json.dumps(material),
                    summary.strip()[:1000],
                    json.dumps(concrete, sort_keys=True),
                    evidence_digest,
                    None,
                    time.time(),
                ),
            )
        if recommend:
            proposal_id = self.control_plane.ingest_hub_recommendation(
                profile=self.profile.name,
                acquisition_id=acquisition_id,
                skill_name=row["name"],
                bundle_dir=Path(row["bundle_path"]),
                bundle_digest=row["bundle_digest"],
                evidence_digest=evidence_digest,
            )
        with self._connect() as db:
            db.execute(
                "UPDATE hub_evidence SET proposal_id=? WHERE evidence_digest=?",
                (proposal_id, evidence_digest),
            )
            db.execute(
                "UPDATE hub_acquisitions SET state=?,terminal_at=? WHERE acquisition_id=?",
                ("RECOMMENDED" if proposal_id else "EVIDENCE_ONLY", time.time(), acquisition_id),
            )
        return {
            "acquisition_id": acquisition_id,
            "evidence_digest": evidence_digest,
            "proposal_id": proposal_id,
            "state": "RECOMMENDED" if proposal_id else "EVIDENCE_ONLY",
        }

    def cleanup(self, acquisition_id: str, *, reason: str) -> dict[str, Any]:
        self._gate()
        row = self.status(acquisition_id)
        if row["source_profile"] != self.profile.name:
            raise PermissionError("acquisition belongs to another profile")
        rel = PurePosixPath(str(row.get("installed_relpath") or ""))
        if not rel.parts or rel.parts[0] != "skills" or len(rel.parts) != 2:
            return {"acquisition_id": acquisition_id, "state": "CLEANED", "removed": False}
        path = self.profile.home.joinpath(*rel.parts)
        if path.exists():
            _, digest = tree_manifest(path)
            if digest != row["installed_digest"]:
                raise ValueError("local skill changed; cleanup requires operator review")
            shutil.rmtree(path)
        with self._connect() as db:
            db.execute(
                "UPDATE hub_acquisitions SET state='CLEANED',terminal_at=? WHERE acquisition_id=?",
                (time.time(), acquisition_id),
            )
            db.execute(
                "INSERT INTO hub_feedback(acquisition_id,code,message,created_at) VALUES (?,?,?,?)",
                (acquisition_id, "cleaned", reason[:500], time.time()),
            )
        return {"acquisition_id": acquisition_id, "state": "CLEANED", "removed": True}

    def status(self, acquisition_id: str) -> dict[str, Any]:
        self._gate()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM hub_acquisitions WHERE acquisition_id=?", (acquisition_id,)
            ).fetchone()
        if not row:
            raise KeyError(acquisition_id)
        return dict(row)
