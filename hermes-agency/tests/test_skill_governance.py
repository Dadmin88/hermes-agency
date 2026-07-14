from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from hermes_agency.skill_governance import (
    GovernancePaths,
    ProposalState,
    ReviewRole,
    SkillGovernanceControlPlane,
    SkillGovernanceManager,
    apply_migration,
    plan_migration,
    restore_migration,
)
from hermes_agency.skill_governance.authority import PrincipalAuthenticator
from hermes_agency.skill_governance.validation import safe_relative_path


def _plane(tmp_path: Path) -> SkillGovernanceControlPlane:
    identities = {
        "orchestrator": {
            "principal_id": "principal-orchestrator",
            "profile_name": "agency-orchestrator",
            "role": ReviewRole.ORCHESTRATOR,
            "peer_id": "peer-orchestrator",
            "channel": "unix-peer:test",
            "process_uid": os.geteuid(),
        },
        "security": {
            "principal_id": "principal-security",
            "profile_name": "agency-security-reviewer",
            "role": ReviewRole.SECURITY,
            "peer_id": "peer-security",
            "channel": "unix-peer:test",
            "process_uid": os.geteuid(),
        },
        "ceo": {
            "principal_id": "principal-ceo",
            "profile_name": "agency-ceo",
            "role": ReviewRole.CEO,
            "peer_id": "peer-ceo",
            "channel": "unix-peer:test",
            "process_uid": os.geteuid(),
        },
    }
    authenticator = PrincipalAuthenticator(
        {
            "agency-orchestrator": "peer-orchestrator",
            "agency-security-reviewer": "peer-security",
            "agency-ceo": "peer-ceo",
        },
        promoter_uid=os.geteuid(),
        promoter_executable=Path("/proc/self/exe").resolve(),
        credential_verifier=identities.get,
    )
    plane = SkillGovernanceControlPlane(
        GovernancePaths(tmp_path / "state", tmp_path / "profiles", tmp_path / "skills"),
        authenticator=authenticator,
    )
    plane._test_credentials = identities
    return plane


def _principal(plane, role, principal_id):
    credential = {
        ReviewRole.ORCHESTRATOR: "orchestrator",
        ReviewRole.SECURITY: "security",
        ReviewRole.CEO: "ceo",
    }[role]
    assert plane._test_credentials[credential]["principal_id"] == principal_id
    return plane.authenticator.authenticate(credential=credential)


def _promoter(plane):
    return plane.authenticator.authenticate_promoter()


def test_authority_issuance_fails_closed_without_trusted_adapters():
    authenticator = PrincipalAuthenticator(
        {"agency-orchestrator": "peer-orchestrator"},
        promoter_executable=Path("/proc/self/exe").resolve(),
    )
    with pytest.raises(PermissionError, match="identity adapter"):
        authenticator.authenticate(credential={"profile_name": "agency-orchestrator"})
    with pytest.raises(PermissionError, match="promoter process"):
        authenticator.authenticate_promoter()


def _pending(tmp_path: Path, profile: str, pending_id: str, payload: dict) -> Path:
    root = tmp_path / "profiles" / profile / "pending" / "skills"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{pending_id}.json"
    path.write_text(
        json.dumps(
            {
                "id": pending_id,
                "subsystem": "skills",
                "action": payload["action"],
                "origin": "foreground",
                "payload": payload,
            }
        ),
        encoding="utf-8",
    )
    return path


def _skill(name: str, body: str = "Use this procedure safely.") -> str:
    return f"---\nname: {name}\ndescription: A safe test skill\n---\n\n# Test\n\n{body}\n"


def _approve_routine(plane: SkillGovernanceControlPlane, proposal_id: str) -> None:
    principal = _principal(plane, ReviewRole.ORCHESTRATOR, "principal-orchestrator")
    plane.store.bind_principal(principal)
    result = plane.review(
        proposal_id,
        principal=principal,
        decision="approve",
        reason="routine content reviewed",
        nonce=f"nonce-{proposal_id}",
    )
    assert result["state"] == ProposalState.AUTHORIZED.value


def test_ingest_is_idempotent_and_audit_chain_verifies(tmp_path):
    plane = _plane(tmp_path)
    source = _pending(
        tmp_path,
        "agency-writer",
        "abcd1234",
        {"action": "create", "name": "safe-skill", "content": _skill("safe-skill")},
    )

    first = plane.ingest_file("agency-writer", source)
    second = plane.ingest_file("agency-writer", source)

    assert first["created"] is True
    assert second == {**first, "created": False}
    assert first["state"] == ProposalState.AWAITING_ROUTINE_APPROVAL.value
    assert plane.store.status()["proposals"] == 1
    assert plane.store.verify_audit()
    assert source.exists(), "ingestion must never replay or silently remove native intent"
    with plane.store.connect() as db, pytest.raises(Exception, match="audit events are immutable"):
        db.execute("DELETE FROM audit_events")


def test_same_source_id_with_changed_bytes_fails_closed(tmp_path):
    plane = _plane(tmp_path)
    source = _pending(
        tmp_path,
        "agency-writer",
        "abcd1234",
        {"action": "create", "name": "safe-skill", "content": _skill("safe-skill")},
    )
    plane.ingest_file("agency-writer", source)
    source.write_text(source.read_text().replace("safely", "differently"), encoding="utf-8")

    with pytest.raises(ValueError, match="source key collision"):
        plane.ingest_file("agency-writer", source)
    assert plane.store.status()["proposals"] == 1


def test_semantic_duplicate_preserves_provenance_and_is_superseded(tmp_path):
    plane = _plane(tmp_path)
    payload = {"action": "create", "name": "safe-skill", "content": _skill("safe-skill")}
    first = plane.ingest_file(
        "agency-writer", _pending(tmp_path, "agency-writer", "aaaa1111", payload)
    )
    duplicate = plane.ingest_file(
        "agency-writer", _pending(tmp_path, "agency-writer", "bbbb2222", payload)
    )

    record = plane.store.get(duplicate["proposal_id"])
    assert record["state"] == ProposalState.SUPERSEDED.value
    assert record["duplicate_of"] == first["proposal_id"]
    assert plane.store.status()["proposals"] == 2


def test_secret_is_quarantined_and_feedback_is_redacted(tmp_path):
    plane = _plane(tmp_path)
    source = _pending(
        tmp_path,
        "agency-writer",
        "abcd1234",
        {
            "action": "create",
            "name": "unsafe-skill",
            "content": _skill("unsafe-skill", "api_key = 'ABCDEFGHIJKLMNOPQRSTUV'"),
        },
    )

    result = plane.ingest_file("agency-writer", source)

    assert result["state"] == ProposalState.QUARANTINED.value
    with plane.store.connect() as db:
        payload = db.execute("SELECT payload_json FROM feedback_outbox").fetchone()[0]
    assert "ABCDEFGHIJKLMNOPQRSTUV" not in payload
    assert "SECRET_DETECTED" in payload


@pytest.mark.parametrize(
    "path",
    ["../escape", "/absolute", "scripts\\evil.py", "scripts/%2e%2e/evil.py", "scripts/a. /x"],
)
def test_support_paths_reject_ambiguous_or_escaping_values(path):
    with pytest.raises(ValueError):
        safe_relative_path(path)


def test_combined_security_governance_requires_security_then_ceo(tmp_path):
    plane = _plane(tmp_path)
    source = _pending(
        tmp_path,
        "agency-writer",
        "abcd1234",
        {
            "action": "create",
            "name": "governance-skill",
            "content": _skill("governance-skill", "Review skill governance before running shell."),
        },
    )
    proposal_id = plane.ingest_file("agency-writer", source)["proposal_id"]
    security = _principal(plane, ReviewRole.SECURITY, "principal-security")
    ceo = _principal(plane, ReviewRole.CEO, "principal-ceo")
    plane.store.bind_principal(security)
    plane.store.bind_principal(ceo)

    with pytest.raises(PermissionError):
        plane.review(
            proposal_id,
            principal=ceo,
            decision="approve",
            reason="CEO cannot skip security",
            nonce="spoof-nonce",
        )
    after_security = plane.review(
        proposal_id,
        principal=security,
        decision="approve",
        reason="static findings reviewed",
        nonce="security-nonce",
    )
    assert after_security["state"] == ProposalState.AWAITING_CEO_APPROVAL.value
    after_ceo = plane.review(
        proposal_id,
        principal=ceo,
        decision="approve",
        reason="governance escalation approved",
        nonce="ceo-nonce",
    )
    assert after_ceo["state"] == ProposalState.AUTHORIZED.value
    assert plane.store.authorization_valid(proposal_id) is True
    with plane.store.transaction() as db:
        db.execute("UPDATE principal_bindings SET enabled=0 WHERE principal_id='principal-ceo'")
    assert plane.store.authorization_valid(proposal_id) is False


def test_authority_cannot_be_minted_from_caller_strings(tmp_path):
    authenticator = PrincipalAuthenticator(
        {"agency-orchestrator": "peer-orchestrator"},
        promoter_uid=os.geteuid(),
        promoter_executable=Path("/proc/self/exe").resolve(),
    )
    with pytest.raises(PermissionError, match="identity adapter"):
        authenticator.authenticate(credential="caller-asserted-orchestrator")


def test_authorization_rejects_target_generation_tampering(tmp_path):
    plane = _plane(tmp_path)
    proposal_id = plane.ingest_file(
        "agency-writer",
        _pending(
            tmp_path,
            "agency-writer",
            "target-binding",
            {"action": "create", "name": "safe-skill", "content": _skill("safe-skill")},
        ),
    )["proposal_id"]
    _approve_routine(plane, proposal_id)
    with plane.store.transaction() as db:
        db.execute(
            "UPDATE reviews SET target_generation='next:forged:generation' WHERE proposal_id=?",
            (proposal_id,),
        )
    assert plane.store.authorization_valid(proposal_id) is False


def test_rejection_is_terminal_and_creates_feedback(tmp_path):
    plane = _plane(tmp_path)
    proposal_id = plane.ingest_file(
        "agency-writer",
        _pending(
            tmp_path,
            "agency-writer",
            "abcd1234",
            {"action": "create", "name": "safe-skill", "content": _skill("safe-skill")},
        ),
    )["proposal_id"]
    principal = _principal(plane, ReviewRole.ORCHESTRATOR, "principal-orchestrator")
    plane.store.bind_principal(principal)

    result = plane.review(
        proposal_id,
        principal=principal,
        decision="reject",
        reason="needs a narrower procedure",
        nonce="reject-nonce",
    )

    assert result["state"] == ProposalState.REJECTED.value
    assert plane.store.status()["outbox_pending"] >= 1


def test_atomic_promotion_is_idempotent_and_manifest_verified(tmp_path):
    plane = _plane(tmp_path)
    proposal_id = plane.ingest_file(
        "agency-writer",
        _pending(
            tmp_path,
            "agency-writer",
            "abcd1234",
            {"action": "create", "name": "safe-skill", "content": _skill("safe-skill")},
        ),
    )["proposal_id"]
    _approve_routine(plane, proposal_id)

    promoted = plane.promote(proposal_id, authority=_promoter(plane))

    shared = tmp_path / "skills" / "shared"
    assert shared.is_symlink()
    assert (shared / "safe-skill" / "SKILL.md").is_file()
    assert (shared / "MANIFEST.json").is_file()
    assert promoted["state"] == "promoted"
    assert plane.store.get(proposal_id)["state"] == ProposalState.PROMOTED.value
    with pytest.raises(PermissionError):
        plane.promote(proposal_id, authority=object())


def test_second_generation_can_roll_back_to_verified_predecessor(tmp_path):
    plane = _plane(tmp_path)
    first_id = plane.ingest_file(
        "agency-writer",
        _pending(
            tmp_path,
            "agency-writer",
            "aaaa1111",
            {"action": "create", "name": "safe-skill", "content": _skill("safe-skill")},
        ),
    )["proposal_id"]
    _approve_routine(plane, first_id)
    authority = _promoter(plane)
    first = plane.promote(first_id, authority=authority)

    second_id = plane.ingest_file(
        "agency-writer",
        _pending(
            tmp_path,
            "agency-writer",
            "bbbb2222",
            {
                "action": "edit",
                "name": "safe-skill",
                "content": _skill("safe-skill", "A reviewed second version."),
            },
        ),
    )["proposal_id"]
    _approve_routine(plane, second_id)
    second = plane.promote(second_id, authority=authority)
    assert second["generation"] != first["generation"]

    rolled_back = plane.promoter.rollback(
        first["generation"],
        authority=authority,
        reason="failed smoke test",
        expected_active=second["generation"],
    )
    assert rolled_back["rolled_back_from"] == second["generation"]
    assert (
        "A reviewed second version."
        not in (tmp_path / "skills" / "shared" / "safe-skill" / "SKILL.md").read_text()
    )


def _profile(root: Path, name: str, text: str) -> Path:
    path = root / name / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o640)
    return path


def test_migration_dry_run_apply_and_restore(tmp_path):
    profiles = tmp_path / "profiles"
    specialist = _profile(profiles, "agency-writer", "model:\n  default: test\n")
    orchestrator = _profile(profiles, "agency-orchestrator", "skills:\n  write_approval: true\n")
    shared = tmp_path / "skills" / "shared"
    backups = tmp_path / "backups"
    original = {path: path.read_bytes() for path in (specialist, orchestrator)}

    plans = plan_migration(profiles, shared)
    assert {plan.profile for plan in plans} == {"agency-writer", "agency-orchestrator"}
    dry_run = apply_migration(profiles, shared, backups, dry_run=True)
    assert dry_run["bytes_unchanged"] is True
    assert all(path.read_bytes() == content for path, content in original.items())

    authenticator = PrincipalAuthenticator(
        {}, promoter_uid=os.geteuid(), promoter_executable=Path("/proc/self/exe").resolve()
    )
    authority = authenticator.authenticate_promoter()
    applied = apply_migration(
        profiles,
        shared,
        backups,
        dry_run=False,
        yes=True,
        authority=authority,
        authenticator=authenticator,
    )
    assert applied["ok"] is True
    specialist_data = yaml.safe_load(specialist.read_text())
    orchestrator_data = yaml.safe_load(orchestrator.read_text())
    assert specialist_data["skills"]["write_approval"] is True
    assert orchestrator_data["skills"]["write_approval"] is False
    assert specialist_data["model"] == {"default": "test"}
    assert specialist_data["skills"]["external_dirs"] == [str(shared.absolute())]
    assert (specialist.stat().st_mode & 0o777) == 0o640

    restored = restore_migration(
        profiles,
        backups,
        applied["migration_id"],
        yes=True,
        authority=authority,
        authenticator=authenticator,
    )
    assert restored["ok"] is True
    assert all(path.read_bytes() == content for path, content in original.items())


def test_reconciler_is_disabled_by_default_and_single_writer(tmp_path):
    plane = _plane(tmp_path)
    disabled = SkillGovernanceManager(plane, enabled=False, is_orchestrator=True)
    assert disabled.start_sync() is False

    owner = SkillGovernanceManager(plane, enabled=True, is_orchestrator=True)
    standby = SkillGovernanceManager(plane, enabled=True, is_orchestrator=True)
    assert owner.start_sync() is True
    try:
        assert standby.start_sync() is False
        assert owner.status()["running"] is True
    finally:
        owner.stop_sync()
    assert standby.start_sync() is True
    standby.stop_sync()
