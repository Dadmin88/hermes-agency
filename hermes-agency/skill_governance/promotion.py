"""Whole-generation atomic shared-skill publication and verified rollback."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .authority import PrincipalAuthenticator, PromoterAuthority
from .models import ProposalState
from .store import GovernanceStore, utc_now
from .validation import _copy_regular_tree, canonical_json, fsync_tree, tree_manifest


class GenerationPromoter:
    """Publish immutable generations; production must run this under a dedicated UID."""

    def __init__(
        self, store: GovernanceStore, skills_root: Path, authenticator: PrincipalAuthenticator
    ):
        self.store = store
        self.authenticator = authenticator
        self.skills_root = skills_root
        self.release_root = skills_root / ".agency-shared" / "releases"
        self.manifest_root = skills_root / ".agency-shared" / "manifests"
        self.shared_link = skills_root / "shared"
        self.lock_path = skills_root / ".agency-shared" / "promotion.lock"

    def _authority(self, authority: PromoterAuthority) -> str:
        if not self.authenticator.verify_promoter(authority):
            raise PermissionError("invalid or expired promoter capability")
        return f"promoter-uid:{authority.process_uid}"

    def _locked(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = self.lock_path.open("a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def _active_generation(self) -> tuple[str | None, Path | None]:
        if not self.shared_link.is_symlink():
            if self.shared_link.exists():
                raise RuntimeError("shared path exists but is not the managed generation symlink")
            return None, None
        target = os.readlink(self.shared_link)
        resolved = (self.shared_link.parent / target).resolve()
        release_root = self.release_root.resolve()
        if resolved.parent != release_root:
            raise RuntimeError("shared symlink escapes managed release root")
        return resolved.name, resolved

    def _verify_generation(self, generation: Path) -> tuple[list[dict[str, Any]], str]:
        manifest_path = generation / "MANIFEST.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise RuntimeError("generation manifest is missing")
        envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = envelope.get("files")
        if not isinstance(files, list):
            raise RuntimeError("generation manifest is invalid")
        actual: list[dict[str, Any]] = []
        for path in sorted(generation.rglob("*")):
            if path == manifest_path or path.is_dir():
                continue
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("generation contains unsupported entry")
            data = path.read_bytes()
            actual.append(
                {
                    "path": path.relative_to(generation).as_posix(),
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        digest = hashlib.sha256(canonical_json(actual)).hexdigest()
        if files != actual or envelope.get("tree_digest") != digest:
            raise RuntimeError("generation manifest does not match immutable files")
        return actual, digest

    def promote(
        self, proposal_id: str, candidate_dir: Path, *, authority: PromoterAuthority
    ) -> dict[str, Any]:
        actor = self._authority(authority)
        handle = self._locked()
        try:
            return self._promote_locked(proposal_id, candidate_dir, actor=actor)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _promote_locked(
        self, proposal_id: str, candidate_dir: Path, *, actor: str
    ) -> dict[str, Any]:
        if not self.store.verify_audit():
            raise RuntimeError("audit chain/checkpoint verification failed")
        proposal = self.store.get(proposal_id)
        if not proposal or proposal["state"] != ProposalState.AUTHORIZED.value:
            raise ValueError("proposal is not authorized")
        if not self.store.authorization_valid(proposal_id):
            raise PermissionError("live authority bindings or digest-bound approvals are invalid")
        if proposal["action"] == "delete":
            candidate_digest = hashlib.sha256(b"deleted").hexdigest()
        else:
            _manifest, candidate_digest = tree_manifest(candidate_dir)
        if candidate_digest != proposal["candidate_digest"]:
            raise ValueError("candidate digest changed after approval")
        self.skills_root.mkdir(parents=True, exist_ok=True, mode=0o755)
        self.release_root.mkdir(parents=True, exist_ok=True, mode=0o755)
        self.manifest_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        active_id, active = self._active_generation()
        baseline_digest = None
        if active is not None:
            self._verify_generation(active)
            active_skill = active / proposal["skill_name"]
            if active_skill.is_dir() and not active_skill.is_symlink():
                _, baseline_digest = tree_manifest(active_skill)
        if proposal["baseline_digest"] != baseline_digest:
            raise ValueError("published baseline changed after validation")
        if proposal["baseline_generation"] != active_id:
            raise ValueError("published generation changed after validation")
        key = hashlib.sha256(
            canonical_json(
                {
                    "proposal_id": proposal_id,
                    "action": proposal["action"],
                    "skill_name": proposal["skill_name"],
                    "candidate_digest": candidate_digest,
                    "baseline_digest": baseline_digest,
                    "baseline_generation": active_id,
                }
            )
        ).hexdigest()
        with self.store.transaction() as db:
            existing = db.execute(
                "SELECT * FROM promotion_jobs WHERE idempotency_key=?", (key,)
            ).fetchone()
            if existing and existing["state"] == "promoted":
                return dict(existing)
            generation_id = f"g-{uuid.uuid4().hex[:16]}"
            job_id = f"sgj_{uuid.uuid4().hex}"
            now = utc_now()
            db.execute(
                "INSERT OR IGNORE INTO promotion_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    key,
                    proposal_id,
                    candidate_digest,
                    baseline_digest,
                    generation_id,
                    "building",
                    1,
                    None,
                    now,
                    now,
                ),
            )
        self.store.transition(
            proposal_id,
            ProposalState.AUTHORIZED,
            ProposalState.PROMOTING,
            actor=actor,
            metadata={"idempotency_key": key},
        )
        temp_path = Path(tempfile.mkdtemp(prefix=".tmp-", dir=self.release_root))
        try:
            if active is not None:
                for child in active.iterdir():
                    if child.name == "MANIFEST.json":
                        continue
                    target = temp_path / child.name
                    if child.is_dir():
                        _copy_regular_tree(child, target)
                    else:
                        raise RuntimeError("managed generation contains an unexpected root file")
            skill_target = temp_path / proposal["skill_name"]
            if proposal["action"] == "delete":
                if skill_target.exists():
                    shutil.rmtree(skill_target)
            else:
                if skill_target.exists():
                    shutil.rmtree(skill_target)
                _copy_regular_tree(candidate_dir, skill_target)
                _, copied_digest = tree_manifest(skill_target)
                if copied_digest != candidate_digest:
                    raise RuntimeError("candidate changed while creating the immutable generation")
            files, generation_digest = tree_manifest(temp_path, generation=True)
            envelope = {
                "schema_version": 1,
                "generation": generation_id,
                "predecessor": active_id,
                "proposal_id": proposal_id,
                "candidate_digest": candidate_digest,
                "tree_digest": generation_digest,
                "files": files,
                "created_at": utc_now(),
            }
            (temp_path / "MANIFEST.json").write_text(
                json.dumps(envelope, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            fsync_tree(temp_path)
            final_path = self.release_root / generation_id
            os.replace(temp_path, final_path)
            for path in sorted(final_path.rglob("*"), reverse=True):
                os.chmod(path, 0o555 if path.is_dir() else 0o444, follow_symlinks=False)
            os.chmod(final_path, 0o555)
            pointer = self.skills_root / f".shared-{uuid.uuid4().hex}.tmp"
            pointer.symlink_to(final_path.relative_to(self.skills_root))
            os.replace(pointer, self.shared_link)
            parent_fd = os.open(self.skills_root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            manifest_bytes = (final_path / "MANIFEST.json").read_bytes()
            manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
            with self.store.transaction() as db:
                now = utc_now()
                if active_id:
                    db.execute(
                        "UPDATE generations SET status='retired' WHERE generation_id=?",
                        (active_id,),
                    )
                db.execute(
                    "INSERT INTO generations VALUES (?,?,?,?,?,?,?)",
                    (
                        generation_id,
                        manifest_digest,
                        active_id,
                        "published",
                        proposal_id,
                        now,
                        None,
                    ),
                )
                db.execute(
                    "UPDATE promotion_jobs SET state='promoted', updated_at=? WHERE idempotency_key=?",
                    (now, key),
                )
            self.store.transition(
                proposal_id,
                ProposalState.PROMOTING,
                ProposalState.PROMOTED,
                actor=actor,
                metadata={"generation": generation_id, "manifest_digest": manifest_digest},
            )
            self.store.feedback(
                proposal_id,
                "promoted",
                {"generation": generation_id, "candidate_digest": candidate_digest},
            )
            return {
                "job_id": job_id,
                "proposal_id": proposal_id,
                "generation": generation_id,
                "manifest_digest": manifest_digest,
                "state": "promoted",
            }
        except Exception as exc:
            shutil.rmtree(temp_path, ignore_errors=True)
            current_id, _current = self._active_generation()
            if current_id == generation_id:
                return self._finalize_published_job(
                    proposal_id, key, generation_id, active_id, actor=actor
                )
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE promotion_jobs SET state='failed', last_error=?, updated_at=? WHERE idempotency_key=?",
                    (f"{type(exc).__name__}: {exc}"[:1000], utc_now(), key),
                )
            self.store.transition(
                proposal_id,
                ProposalState.PROMOTING,
                ProposalState.PROMOTION_FAILED,
                actor=actor,
                metadata={"error_type": type(exc).__name__},
            )
            self.store.feedback(
                proposal_id,
                "promotion_failed",
                {
                    "reason": "atomic publication failed; shared pointer was not intentionally changed"
                },
            )
            raise

    def _finalize_published_job(
        self,
        proposal_id: str,
        key: str,
        generation_id: str,
        predecessor: str | None,
        *,
        actor: str,
    ) -> dict[str, Any]:
        final_path = self.release_root / generation_id
        self._verify_generation(final_path)
        envelope = json.loads((final_path / "MANIFEST.json").read_text(encoding="utf-8"))
        recorded_predecessor = envelope.get("predecessor")
        if predecessor is not None and recorded_predecessor != predecessor:
            raise RuntimeError("published generation predecessor does not match promotion intent")
        predecessor = recorded_predecessor
        manifest_digest = hashlib.sha256((final_path / "MANIFEST.json").read_bytes()).hexdigest()
        now = utc_now()
        with self.store.transaction() as db:
            if predecessor:
                db.execute(
                    "UPDATE generations SET status='retired' WHERE generation_id=?", (predecessor,)
                )
            db.execute(
                "INSERT OR REPLACE INTO generations VALUES (?,?,?,?,?,?,?)",
                (generation_id, manifest_digest, predecessor, "published", proposal_id, now, None),
            )
            db.execute(
                "UPDATE promotion_jobs SET state='promoted',updated_at=?,last_error=NULL WHERE idempotency_key=?",
                (now, key),
            )
            state = db.execute(
                "SELECT state FROM proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()[0]
            if state != ProposalState.PROMOTED.value:
                db.execute(
                    "UPDATE proposals SET state=?,state_version=state_version+1,updated_at=?,terminal_at=? WHERE proposal_id=?",
                    (ProposalState.PROMOTED.value, now, now, proposal_id),
                )
                self.store._audit(
                    db,
                    proposal_id=proposal_id,
                    actor=actor,
                    action="PROMOTION_RECONCILED",
                    before=state,
                    after=ProposalState.PROMOTED.value,
                    metadata={"generation": generation_id},
                )
        return {
            "proposal_id": proposal_id,
            "generation": generation_id,
            "manifest_digest": manifest_digest,
            "state": "promoted",
        }

    def reconcile(self, *, authority: PromoterAuthority) -> list[str]:
        actor = self._authority(authority)
        handle = self._locked()
        try:
            active_id, _active = self._active_generation()
            if not active_id:
                return []
            with self.store.connect() as db:
                rows = db.execute(
                    "SELECT * FROM promotion_jobs WHERE target_generation=? AND state!='promoted'",
                    (active_id,),
                ).fetchall()
            repaired = []
            for row in rows:
                self._finalize_published_job(
                    row["proposal_id"], row["idempotency_key"], active_id, None, actor=actor
                )
                repaired.append(row["job_id"])
            return repaired
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def rollback(
        self,
        generation_id: str,
        *,
        authority: PromoterAuthority,
        reason: str,
        expected_active: str,
    ) -> dict[str, Any]:
        actor = self._authority(authority)
        if not self.store.verify_audit():
            raise RuntimeError("audit chain/checkpoint verification failed")
        handle = self._locked()
        try:
            return self._rollback_locked(generation_id, actor, reason, expected_active)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _rollback_locked(
        self, generation_id: str, actor: str, reason: str, expected_active: str
    ) -> dict[str, Any]:
        active_id, active = self._active_generation()
        if active_id != expected_active:
            raise ValueError("active generation changed before rollback")
        if active is None or active_id == generation_id:
            raise ValueError("rollback target must differ from active generation")
        target = self.release_root / generation_id
        _files, tree_digest = self._verify_generation(target)
        pointer = self.skills_root / f".shared-{uuid.uuid4().hex}.tmp"
        pointer.symlink_to(target.relative_to(self.skills_root))
        os.replace(pointer, self.shared_link)
        with self.store.transaction() as db:
            db.execute(
                "UPDATE generations SET status='retired' WHERE generation_id=?", (active_id,)
            )
            db.execute(
                "UPDATE generations SET status='published', rollback_reason=? WHERE generation_id=?",
                (reason[:1000], generation_id),
            )
            self.store._audit(
                db,
                proposal_id=None,
                actor=actor,
                action="ROLLBACK",
                before=active_id,
                after=generation_id,
                metadata={"reason": reason[:500], "tree_digest": tree_digest},
            )
        return {
            "rolled_back_from": active_id,
            "generation": generation_id,
            "tree_digest": tree_digest,
        }
