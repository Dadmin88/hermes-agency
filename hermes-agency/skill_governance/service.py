"""Agency skill-governance control plane orchestration."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .authority import AuthenticatedPrincipal, PrincipalAuthenticator, PromoterAuthority
from .models import ProposalState
from .promotion import GenerationPromoter
from .store import GovernanceStore
from .validation import (
    canonical_json,
    materialize,
    sha256_bytes,
    validate_candidate,
    validate_skill_name,
)

_ALLOWED_ACTIONS = {"create", "edit", "patch", "delete", "write_file", "remove_file"}
_ALLOWED_PAYLOAD_KEYS = {
    "action",
    "name",
    "category",
    "content",
    "old_string",
    "new_string",
    "replace_all",
    "file_path",
    "file_content",
    "absorbed_into",
}


@dataclass(frozen=True)
class GovernancePaths:
    state_root: Path
    profiles_root: Path
    skills_root: Path

    @property
    def objects(self) -> Path:
        return self.state_root / "objects" / "sha256"

    @property
    def candidates(self) -> Path:
        return self.state_root / "candidates"

    @property
    def archives(self) -> Path:
        return self.state_root / "native-archive"


class SkillGovernanceControlPlane:
    def __init__(
        self,
        paths: GovernancePaths,
        *,
        max_pending_bytes: int = 1572864,
        authenticator: PrincipalAuthenticator | None = None,
    ):
        self.paths = paths
        self.max_pending_bytes = max_pending_bytes
        self.paths.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.paths.state_root.chmod(0o700)
        self.authenticator = authenticator or PrincipalAuthenticator({})
        self.store = GovernanceStore(paths.state_root / "governance.sqlite3", self.authenticator)
        self.promoter = GenerationPromoter(self.store, paths.skills_root, self.authenticator)

    def _store_object(self, data: bytes, media_type: str) -> tuple[str, Path]:
        digest = sha256_bytes(data)
        path = self.paths.objects / digest[:2] / digest
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.exists():
            if path.read_bytes() != data:
                raise RuntimeError("content-addressed object collision")
        else:
            temp = path.with_name(f".{digest}.tmp")
            descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                os.write(descriptor, data)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temp, path)
        relative = path.relative_to(self.paths.state_root).as_posix()
        self.store.put_object(digest, data, relative, media_type)
        return digest, path

    def _parse_record(
        self, profile: str, path: Path, data: bytes
    ) -> tuple[str, dict[str, Any], str, str]:
        if len(data) > self.max_pending_bytes:
            raise ValueError("pending record exceeds configured byte limit")
        try:
            record = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"pending record is not valid UTF-8 JSON: {exc}") from exc
        if not isinstance(record, dict) or record.get("subsystem") != "skills":
            raise ValueError("pending record must be a skills object")
        pending_id = str(record.get("id") or "")
        if pending_id != path.stem or not pending_id or len(pending_id) > 128:
            raise ValueError("pending id must match filename")
        action = str(record.get("action") or "")
        payload = record.get("payload")
        if action not in _ALLOWED_ACTIONS or not isinstance(payload, dict):
            raise ValueError("pending action or payload is invalid")
        unknown = set(payload) - _ALLOWED_PAYLOAD_KEYS
        if unknown or payload.get("action") != action:
            raise ValueError("payload has unknown keys or mismatched action")
        skill_name = validate_skill_name(payload.get("name"))
        semantic = sha256_bytes(canonical_json({"profile": profile, "payload": payload}))
        return pending_id, payload, skill_name, semantic

    def ingest_file(self, profile: str, path: Path) -> dict[str, Any]:
        if (
            not re.fullmatch(r"agency-[a-z0-9][a-z0-9-]{0,62}", profile)
            or profile == "agency-orchestrator"
        ):
            raise PermissionError("only non-orchestrator agency profiles may propose")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("pending source must be one regular, non-linked file")
            data = os.read(descriptor, self.max_pending_bytes + 1)
            if os.fstat(descriptor) != info:
                raise RuntimeError("pending source changed while reading")
        finally:
            os.close(descriptor)
        pending_id, payload, skill_name, semantic_digest = self._parse_record(profile, path, data)
        source_digest, source_object = self._store_object(
            data, "application/vnd.hermes.pending+json"
        )
        payload_digest = sha256_bytes(canonical_json(payload))
        proposal_id, created = self.store.ingest(
            profile=profile,
            pending_id=pending_id,
            source_digest=source_digest,
            payload_digest=payload_digest,
            semantic_digest=semantic_digest,
            action=payload["action"],
            skill_name=skill_name,
            origin=str(json.loads(data).get("origin") or "unknown")[:64],
            object_ref=source_object.relative_to(self.paths.state_root).as_posix(),
            original_filename=path.name,
        )
        if created and self.store.get(proposal_id)["state"] == ProposalState.INGESTED.value:
            self.validate(proposal_id, payload)
        return {
            "proposal_id": proposal_id,
            "created": created,
            "state": self.store.get(proposal_id)["state"],
        }

    def validate(self, proposal_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        proposal = self.store.get(proposal_id)
        if not proposal:
            raise KeyError(proposal_id)
        if payload is None:
            source_record = self.store.find_source(
                proposal["source_profile"], proposal["native_pending_id"]
            )
            if source_record is None:
                raise RuntimeError("durable source record is missing")
            source = self.paths.state_root / source_record["original_object_ref"]
            payload = json.loads(source.read_bytes())["payload"]
        self.store.transition(
            proposal_id, ProposalState.INGESTED, ProposalState.VALIDATING, actor="validator"
        )
        shared = self.paths.skills_root / "shared"
        baseline = shared / proposal["skill_name"] if shared.exists() else None
        baseline_digest = None
        baseline_generation = None
        if shared.is_symlink():
            baseline_generation = (shared.parent / os.readlink(shared)).resolve().name
        if baseline is not None and baseline.exists():
            from .validation import tree_manifest

            _, baseline_digest = tree_manifest(baseline)
        candidate = self.paths.candidates / proposal_id
        shutil.rmtree(candidate, ignore_errors=True)
        try:
            action, name = materialize(payload, baseline, candidate)
            result = validate_candidate(candidate, name, action)
        except Exception as exc:
            from .models import RiskClass, ValidationFinding, ValidationResult

            result = ValidationResult(
                False,
                False,
                RiskClass.SECURITY,
                None,
                None,
                (ValidationFinding("MATERIALIZATION_FAILED", "error", "", str(exc)),),
            )
        if not result.valid:
            target = (
                ProposalState.QUARANTINED if result.quarantined else ProposalState.VALIDATION_FAILED
            )
            self.store.transition(
                proposal_id,
                ProposalState.VALIDATING,
                target,
                actor="validator",
                metadata={"finding_codes": [item.code for item in result.findings]},
                updates={
                    "risk_class": result.risk.value,
                    "validation_json": json.dumps(result.as_dict(), sort_keys=True),
                },
            )
            self.store.feedback(
                proposal_id,
                target.value.lower(),
                {
                    "findings": [item.as_dict() for item in result.findings],
                    "new_revision_required": True,
                },
            )
            return self.store.get(proposal_id)
        next_state = self.store.set_requirements(proposal_id, result.risk)
        return self.store.transition(
            proposal_id,
            ProposalState.VALIDATING,
            next_state,
            actor="validator",
            metadata={"risk": result.risk.value, "candidate_digest": result.candidate_digest},
            updates={
                "risk_class": result.risk.value,
                "candidate_digest": result.candidate_digest,
                "candidate_object_ref": str(candidate),
                "baseline_digest": baseline_digest,
                "baseline_generation": baseline_generation,
                "validation_json": json.dumps(result.as_dict(), sort_keys=True),
            },
        )

    def scan(self) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        if not self.paths.profiles_root.is_dir():
            return {"scanned": 0, "results": [], "errors": []}
        for profile_dir in sorted(self.paths.profiles_root.glob("agency-*")):
            if (
                profile_dir.is_symlink()
                or not profile_dir.is_dir()
                or profile_dir.name == "agency-orchestrator"
            ):
                continue
            pending = profile_dir / "pending" / "skills"
            if pending.is_symlink() or not pending.is_dir():
                continue
            for path in sorted(pending.glob("*.json")):
                try:
                    results.append(self.ingest_file(profile_dir.name, path))
                except Exception as exc:
                    errors.append(
                        {
                            "profile": profile_dir.name,
                            "file": path.name,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
        return {"scanned": len(results) + len(errors), "results": results, "errors": errors}

    def ingest_hub_recommendation(
        self,
        *,
        profile: str,
        acquisition_id: str,
        skill_name: str,
        bundle_dir: Path,
        bundle_digest: str,
        evidence_digest: str,
    ) -> str:
        """Attach immutable, materially-helpful hub bytes to normal governance."""
        validate_skill_name(skill_name)
        manifest, actual_digest = __import__(
            f"{__package__}.validation", fromlist=["tree_manifest"]
        ).tree_manifest(bundle_dir)
        if actual_digest != bundle_digest:
            raise ValueError("hub bundle digest changed before recommendation")
        source = canonical_json(
            {
                "origin": "hub_evidence",
                "profile": profile,
                "acquisition_id": acquisition_id,
                "bundle_digest": bundle_digest,
                "evidence_digest": evidence_digest,
                "manifest": manifest,
            }
        )
        source_digest, source_path = self._store_object(
            source, "application/vnd.hermes.agency.hub-evidence+json"
        )
        proposal_id, created = self.store.ingest(
            profile=profile,
            pending_id=f"hub-{acquisition_id}",
            source_digest=source_digest,
            payload_digest=bundle_digest,
            semantic_digest=sha256_bytes(
                canonical_json({"name": skill_name, "digest": bundle_digest})
            ),
            action="create",
            skill_name=skill_name,
            origin="hub_evidence",
            object_ref=source_path.relative_to(self.paths.state_root).as_posix(),
            original_filename=f"hub-{acquisition_id}.json",
        )
        if not created:
            return proposal_id
        candidate = self.paths.candidates / proposal_id
        shutil.rmtree(candidate, ignore_errors=True)
        from .validation import _copy_regular_tree, validate_candidate

        _copy_regular_tree(bundle_dir, candidate)
        result = validate_candidate(candidate, skill_name, "create")
        if not result.valid or result.candidate_digest != bundle_digest:
            self.store.transition(
                proposal_id,
                ProposalState.INGESTED,
                ProposalState.QUARANTINED,
                actor="hub-validator",
                updates={"validation_json": json.dumps(result.as_dict(), sort_keys=True)},
            )
            raise ValueError("hub recommendation failed governance validation")
        shared = self.paths.skills_root / "shared"
        active_generation = (
            (shared.parent / os.readlink(shared)).resolve().name if shared.is_symlink() else None
        )
        baseline = shared / skill_name
        baseline_digest = None
        if baseline.is_dir() and not baseline.is_symlink():
            from .validation import tree_manifest

            _, baseline_digest = tree_manifest(baseline)
        next_state = self.store.set_requirements(proposal_id, result.risk)
        self.store.transition(
            proposal_id,
            ProposalState.INGESTED,
            next_state,
            actor="hub-validator",
            metadata={"evidence_digest": evidence_digest},
            updates={
                "risk_class": result.risk.value,
                "candidate_digest": bundle_digest,
                "candidate_object_ref": str(candidate),
                "baseline_digest": baseline_digest,
                "baseline_generation": active_generation,
                "validation_json": json.dumps(result.as_dict(), sort_keys=True),
            },
        )
        return proposal_id

    def review(
        self,
        proposal_id: str,
        *,
        principal: AuthenticatedPrincipal,
        decision: str,
        reason: str,
        nonce: str,
        expires_in_seconds: int = 300,
    ) -> dict[str, Any]:
        return self.store.record_review(
            proposal_id,
            principal=principal,
            decision=decision,
            reason=reason,
            nonce=nonce,
            expires_in_seconds=expires_in_seconds,
        )

    def promote(self, proposal_id: str, *, authority: PromoterAuthority) -> dict[str, Any]:
        if not self.authenticator.verify_promoter(authority):
            raise PermissionError("only the authenticated dedicated promoter may publish")
        proposal = self.store.get(proposal_id)
        if not proposal or not proposal.get("candidate_object_ref"):
            raise ValueError("proposal candidate is unavailable")
        return self.promoter.promote(
            proposal_id, Path(proposal["candidate_object_ref"]), authority=authority
        )

    def status(self) -> dict[str, Any]:
        return {
            "enabled": False,
            "deployment_state": "implementation-only",
            "state_root": str(self.paths.state_root),
            "shared_path": str(self.paths.skills_root / "shared"),
            **self.store.status(),
        }


def default_paths() -> GovernancePaths:
    home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
    root = home.parent.parent if home.parent.name == "profiles" else home
    return GovernancePaths(
        root / ".agency" / "skill-governance", root / "profiles", root / "skills"
    )
