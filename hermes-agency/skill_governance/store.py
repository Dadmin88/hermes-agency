"""SQLite authority ledger with idempotency and a hash-chained audit log."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .authority import AuthenticatedPrincipal, PrincipalAuthenticator
from .models import ProposalState, ReviewRole, RiskClass
from .validation import POLICY_VERSION, SCANNER_VERSION, VALIDATOR_VERSION, canonical_json

_SCHEMA_VERSION = 2


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class GovernanceStore:
    def __init__(self, path: Path, authenticator: PrincipalAuthenticator | None = None):
        self.path = path
        self.authenticator = authenticator
        self.checkpoint_path = path.with_suffix(".audit-checkpoint.json")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS objects(
                    digest TEXT PRIMARY KEY, media_type TEXT NOT NULL, byte_count INTEGER NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposals(
                    proposal_id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 1,
                    source_profile TEXT NOT NULL, native_pending_id TEXT NOT NULL,
                    source_digest TEXT NOT NULL UNIQUE, payload_digest TEXT NOT NULL,
                    semantic_digest TEXT NOT NULL, action TEXT NOT NULL, skill_name TEXT NOT NULL,
                    origin TEXT NOT NULL, state TEXT NOT NULL, state_version INTEGER NOT NULL DEFAULT 1,
                    risk_class TEXT, candidate_digest TEXT, candidate_object_ref TEXT,
                    duplicate_of TEXT REFERENCES proposals(proposal_id),
                    baseline_generation TEXT, baseline_digest TEXT,
                    policy_version TEXT NOT NULL, validator_version TEXT NOT NULL, scanner_version TEXT NOT NULL,
                    validation_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, terminal_at TEXT,
                    UNIQUE(source_profile, native_pending_id)
                );
                CREATE INDEX IF NOT EXISTS proposals_state_idx ON proposals(state, updated_at);
                CREATE INDEX IF NOT EXISTS proposals_semantic_idx ON proposals(semantic_digest);
                CREATE TABLE IF NOT EXISTS source_records(
                    source_profile TEXT NOT NULL, native_pending_id TEXT NOT NULL,
                    source_digest TEXT NOT NULL, original_object_ref TEXT NOT NULL,
                    original_filename TEXT NOT NULL, archive_path TEXT, status TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, last_error TEXT,
                    PRIMARY KEY(source_profile, native_pending_id)
                );
                CREATE TABLE IF NOT EXISTS review_requirements(
                    proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id), role TEXT NOT NULL,
                    ordering INTEGER NOT NULL, reason TEXT NOT NULL, satisfied INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(proposal_id, role)
                );
                CREATE TABLE IF NOT EXISTS reviews(
                    review_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id),
                    candidate_digest TEXT NOT NULL, principal_id TEXT NOT NULL, role TEXT NOT NULL,
                    decision TEXT NOT NULL, reason TEXT NOT NULL, nonce TEXT NOT NULL UNIQUE,
                    authenticated_channel TEXT NOT NULL, created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL, policy_version TEXT NOT NULL,
                    destination TEXT NOT NULL, baseline_generation TEXT NOT NULL,
                    target_generation TEXT NOT NULL,
                    UNIQUE(proposal_id, principal_id, role)
                );
                CREATE TABLE IF NOT EXISTS principal_bindings(
                    principal_id TEXT PRIMARY KEY, profile_name TEXT NOT NULL UNIQUE, role TEXT NOT NULL,
                    peer_id TEXT, enabled INTEGER NOT NULL DEFAULT 1, valid_until TEXT
                );
                CREATE TABLE IF NOT EXISTS promotion_jobs(
                    job_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                    proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id), candidate_digest TEXT NOT NULL,
                    baseline_digest TEXT, target_generation TEXT NOT NULL, state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generations(
                    generation_id TEXT PRIMARY KEY, manifest_digest TEXT NOT NULL UNIQUE,
                    predecessor TEXT, status TEXT NOT NULL, proposal_id TEXT, created_at TEXT NOT NULL,
                    rollback_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS feedback_outbox(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
                    proposal_id TEXT NOT NULL, target_profile TEXT NOT NULL, event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    delivered_at TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                    proposal_id TEXT, actor_principal TEXT NOT NULL, action TEXT NOT NULL,
                    before_state TEXT, after_state TEXT, metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                    BEFORE UPDATE ON audit_events
                    BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                    BEFORE DELETE ON audit_events
                    BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END;
                """
            )
            review_columns = {row[1] for row in db.execute("PRAGMA table_info(reviews)")}
            for name, declaration in {
                "expires_at": "TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00'",
                "policy_version": "TEXT NOT NULL DEFAULT ''",
                "destination": "TEXT NOT NULL DEFAULT ''",
                "baseline_generation": "TEXT NOT NULL DEFAULT '<empty>'",
                "target_generation": "TEXT NOT NULL DEFAULT ''",
            }.items():
                if name not in review_columns:
                    db.execute(f"ALTER TABLE reviews ADD COLUMN {name} {declaration}")
            db.execute(
                "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
                (_SCHEMA_VERSION, utc_now()),
            )
        self.path.chmod(0o600)
        if not self.checkpoint_path.exists():
            self._write_checkpoint()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
                self._write_checkpoint(db)
            except Exception:
                db.rollback()
                raise

    def _write_checkpoint(self, db: sqlite3.Connection | None = None) -> None:
        owned = db is None
        connection = db or self.connect()
        try:
            row = connection.execute(
                "SELECT sequence,event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            payload = {
                "sequence": int(row[0]) if row else 0,
                "event_hash": str(row[1]) if row else "0" * 64,
            }
            temp = self.checkpoint_path.with_name(f".{self.checkpoint_path.name}.tmp")
            temp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            temp.chmod(0o600)
            temp.replace(self.checkpoint_path)
        finally:
            if owned:
                connection.close()

    def _audit(
        self,
        db: sqlite3.Connection,
        *,
        proposal_id: str | None,
        actor: str,
        action: str,
        before: str | None,
        after: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        previous_row = db.execute(
            "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous = str(previous_row[0]) if previous_row else "0" * 64
        event_id = f"sga_{uuid.uuid4().hex}"
        created_at = utc_now()
        safe_metadata = metadata or {}
        material = canonical_json(
            {
                "event_id": event_id,
                "proposal_id": proposal_id,
                "actor": actor,
                "action": action,
                "before": before,
                "after": after,
                "metadata": safe_metadata,
                "created_at": created_at,
                "previous_hash": previous,
            }
        )
        event_hash = hashlib.sha256(material).hexdigest()
        db.execute(
            "INSERT INTO audit_events(event_id, proposal_id, actor_principal, action, before_state, after_state, metadata_json, created_at, previous_hash, event_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                proposal_id,
                actor,
                action,
                before,
                after,
                json.dumps(safe_metadata, sort_keys=True, separators=(",", ":")),
                created_at,
                previous,
                event_hash,
            ),
        )
        return event_hash

    def put_object(self, digest: str, data: bytes, relative_path: str, media_type: str) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO objects VALUES (?,?,?,?,?)",
                (digest, media_type, len(data), relative_path, utc_now()),
            )

    def ingest(
        self,
        *,
        profile: str,
        pending_id: str,
        source_digest: str,
        payload_digest: str,
        semantic_digest: str,
        action: str,
        skill_name: str,
        origin: str,
        object_ref: str,
        original_filename: str,
    ) -> tuple[str, bool]:
        with self.transaction() as db:
            existing = db.execute(
                "SELECT proposal_id, source_digest FROM proposals WHERE source_profile=? AND native_pending_id=?",
                (profile, pending_id),
            ).fetchone()
            if existing:
                if existing["source_digest"] != source_digest:
                    self._audit(
                        db,
                        proposal_id=existing["proposal_id"],
                        actor="ingestor",
                        action="SOURCE_COLLISION",
                        before=None,
                        after=None,
                        metadata={"reason": "native id reused with changed bytes"},
                    )
                    raise ValueError(
                        "source key collision: pending id was reused with changed bytes"
                    )
                db.execute(
                    "UPDATE source_records SET last_seen_at=? WHERE source_profile=? AND native_pending_id=?",
                    (utc_now(), profile, pending_id),
                )
                return str(existing["proposal_id"]), False
            proposal_id = f"sgp_{uuid.uuid4().hex}"
            now = utc_now()
            duplicate = db.execute(
                "SELECT proposal_id FROM proposals WHERE semantic_digest=? ORDER BY created_at LIMIT 1",
                (semantic_digest,),
            ).fetchone()
            initial_state = (
                ProposalState.SUPERSEDED.value if duplicate else ProposalState.INGESTED.value
            )
            db.execute(
                "INSERT INTO proposals(proposal_id, source_profile, native_pending_id, source_digest, payload_digest, semantic_digest, action, skill_name, origin, state, duplicate_of, policy_version, validator_version, scanner_version, created_at, updated_at, terminal_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    proposal_id,
                    profile,
                    pending_id,
                    source_digest,
                    payload_digest,
                    semantic_digest,
                    action,
                    skill_name,
                    origin,
                    initial_state,
                    duplicate["proposal_id"] if duplicate else None,
                    POLICY_VERSION,
                    VALIDATOR_VERSION,
                    SCANNER_VERSION,
                    now,
                    now,
                    now if duplicate else None,
                ),
            )
            db.execute(
                "INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    profile,
                    pending_id,
                    source_digest,
                    object_ref,
                    original_filename,
                    None,
                    "ingested",
                    now,
                    now,
                    None,
                ),
            )
            self._audit(
                db,
                proposal_id=proposal_id,
                actor=profile,
                action="DUPLICATE_SUPERSEDED" if duplicate else "INGESTED",
                before=None,
                after=initial_state,
                metadata={
                    "source_digest": source_digest,
                    "payload_digest": payload_digest,
                    "duplicate_of": duplicate["proposal_id"] if duplicate else None,
                },
            )
            if duplicate:
                self._feedback(
                    db,
                    proposal_id,
                    profile,
                    "superseded_duplicate",
                    {"canonical_proposal_id": duplicate["proposal_id"]},
                )
            return proposal_id, True

    def get(self, proposal_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            return dict(row) if row else None

    def find_source(self, profile: str, pending_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM source_records WHERE source_profile=? AND native_pending_id=?",
                (profile, pending_id),
            ).fetchone()
            return dict(row) if row else None

    def transition(
        self,
        proposal_id: str,
        expected: ProposalState | set[ProposalState],
        target: ProposalState,
        *,
        actor: str,
        metadata: dict[str, Any] | None = None,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allowed = {expected} if isinstance(expected, ProposalState) else expected
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if not row:
                raise KeyError(proposal_id)
            before = ProposalState(row["state"])
            if before not in allowed:
                raise ValueError(f"invalid transition {before.value} -> {target.value}")
            fields: dict[str, Any] = {
                "state": target.value,
                "state_version": int(row["state_version"]) + 1,
                "updated_at": utc_now(),
            }
            if target in {
                ProposalState.VALIDATION_FAILED,
                ProposalState.QUARANTINED,
                ProposalState.REJECTED,
                ProposalState.PROMOTED,
                ProposalState.SUPERSEDED,
            }:
                fields["terminal_at"] = utc_now()
            fields.update(updates or {})
            assignment = ", ".join(f"{key}=?" for key in fields)
            db.execute(
                f"UPDATE proposals SET {assignment} WHERE proposal_id=?",
                (*fields.values(), proposal_id),
            )
            self._audit(
                db,
                proposal_id=proposal_id,
                actor=actor,
                action="STATE_TRANSITION",
                before=before.value,
                after=target.value,
                metadata=metadata,
            )
            result = db.execute(
                "SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            return dict(result)

    def set_requirements(self, proposal_id: str, risk: RiskClass) -> ProposalState:
        if risk is RiskClass.ROUTINE:
            requirements = [(ReviewRole.ORCHESTRATOR, 1, "independent routine approval")]
            state = ProposalState.AWAITING_ROUTINE_APPROVAL
        elif risk is RiskClass.SECURITY:
            requirements = [
                (ReviewRole.SECURITY, 1, "security-sensitive content"),
                (ReviewRole.ORCHESTRATOR, 2, "routine authority after security"),
            ]
            state = ProposalState.AWAITING_SECURITY_APPROVAL
        elif risk is RiskClass.GOVERNANCE:
            requirements = [(ReviewRole.CEO, 1, "governance-sensitive escalation")]
            state = ProposalState.AWAITING_CEO_APPROVAL
        else:
            requirements = [
                (ReviewRole.SECURITY, 1, "security-sensitive content"),
                (ReviewRole.CEO, 2, "governance-sensitive escalation"),
            ]
            state = ProposalState.AWAITING_SECURITY_APPROVAL
        with self.transaction() as db:
            db.execute("DELETE FROM review_requirements WHERE proposal_id=?", (proposal_id,))
            db.executemany(
                "INSERT INTO review_requirements(proposal_id, role, ordering, reason) VALUES (?,?,?,?)",
                [(proposal_id, role.value, order, reason) for role, order, reason in requirements],
            )
        return state

    def bind_principal(self, principal: AuthenticatedPrincipal) -> None:
        if self.authenticator is None or not self.authenticator.verify(principal):
            raise PermissionError("principal capability is not authenticated")
        with self.transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO principal_bindings(principal_id, profile_name, role, peer_id, enabled) VALUES (?,?,?,?,1)",
                (
                    principal.principal_id,
                    principal.profile_name,
                    principal.role.value,
                    principal.peer_id,
                ),
            )
            self._audit(
                db,
                proposal_id=None,
                actor=principal.principal_id,
                action="PRINCIPAL_BOUND",
                before=None,
                after=None,
                metadata={
                    "principal_id": principal.principal_id,
                    "profile_name": principal.profile_name,
                    "role": principal.role.value,
                    "peer_bound": True,
                },
            )

    def record_review(
        self,
        proposal_id: str,
        *,
        principal: AuthenticatedPrincipal,
        decision: str,
        reason: str,
        nonce: str,
        expires_in_seconds: int = 300,
    ) -> dict[str, Any]:
        if self.authenticator is None or not self.authenticator.verify(principal):
            raise PermissionError("review principal capability is not authenticated")
        principal_id = principal.principal_id
        role = principal.role
        authenticated_channel = principal.channel
        if decision not in {"approve", "reject"} or not nonce:
            raise ValueError("review requires approve/reject and nonce")
        with self.transaction() as db:
            proposal = db.execute(
                "SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            binding = db.execute(
                "SELECT * FROM principal_bindings WHERE principal_id=? AND enabled=1",
                (principal_id,),
            ).fetchone()
            requirement = db.execute(
                "SELECT * FROM review_requirements WHERE proposal_id=? AND role=?",
                (proposal_id, role.value),
            ).fetchone()
            if not proposal or not binding or binding["role"] != role.value or not requirement:
                raise PermissionError("authenticated principal is not bound to the required role")
            if (
                binding["profile_name"] != principal.profile_name
                or binding["peer_id"] != principal.peer_id
            ):
                raise PermissionError("stored binding differs from authenticated identity")
            lower = db.execute(
                "SELECT role FROM review_requirements WHERE proposal_id=? AND ordering<? AND satisfied=0",
                (proposal_id, requirement["ordering"]),
            ).fetchone()
            if lower:
                raise PermissionError(f"required {lower['role']} review must be completed first")
            if binding["profile_name"] == proposal["source_profile"]:
                raise PermissionError("proposer cannot approve its own proposal")
            prior = db.execute(
                "SELECT principal_id FROM reviews WHERE proposal_id=? AND decision='approve'",
                (proposal_id,),
            ).fetchall()
            if any(row[0] == principal_id for row in prior):
                raise PermissionError("one principal cannot satisfy multiple roles")
            if not proposal["candidate_digest"]:
                raise ValueError("proposal has no validated candidate digest")
            now = utc_now()
            expires_at = (
                datetime.now(UTC) + timedelta(seconds=max(1, min(expires_in_seconds, 900)))
            ).isoformat()
            destination = f"shared/{proposal['skill_name']}"
            baseline_generation = proposal["baseline_generation"] or "<empty>"
            target_generation = f"next:{baseline_generation}:{proposal['candidate_digest']}"
            db.execute(
                "INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"sgr_{uuid.uuid4().hex}",
                    proposal_id,
                    proposal["candidate_digest"],
                    principal_id,
                    role.value,
                    decision,
                    reason[:1000],
                    nonce,
                    authenticated_channel,
                    now,
                    expires_at,
                    proposal["policy_version"],
                    destination,
                    baseline_generation,
                    target_generation,
                ),
            )
            if decision == "reject":
                target = ProposalState.REJECTED
                db.execute(
                    "UPDATE proposals SET state=?, state_version=state_version+1, terminal_at=?, updated_at=? WHERE proposal_id=?",
                    (target.value, now, now, proposal_id),
                )
                self._feedback(
                    db,
                    proposal_id,
                    proposal["source_profile"],
                    "rejected",
                    {"reason": reason[:500], "role": role.value, "new_revision_required": True},
                )
            else:
                db.execute(
                    "UPDATE review_requirements SET satisfied=1 WHERE proposal_id=? AND role=?",
                    (proposal_id, role.value),
                )
                next_req = db.execute(
                    "SELECT role FROM review_requirements WHERE proposal_id=? AND satisfied=0 ORDER BY ordering LIMIT 1",
                    (proposal_id,),
                ).fetchone()
                target = (
                    ProposalState.AUTHORIZED
                    if not next_req
                    else {
                        ReviewRole.SECURITY.value: ProposalState.AWAITING_SECURITY_APPROVAL,
                        ReviewRole.CEO.value: ProposalState.AWAITING_CEO_APPROVAL,
                        ReviewRole.ORCHESTRATOR.value: ProposalState.AWAITING_ROUTINE_APPROVAL,
                    }[next_req["role"]]
                )
                db.execute(
                    "UPDATE proposals SET state=?, state_version=state_version+1, updated_at=? WHERE proposal_id=?",
                    (target.value, now, proposal_id),
                )
            self._audit(
                db,
                proposal_id=proposal_id,
                actor=principal_id,
                action=f"REVIEW_{decision.upper()}",
                before=proposal["state"],
                after=target.value,
                metadata={
                    "role": role.value,
                    "candidate_digest": proposal["candidate_digest"],
                    "channel": authenticated_channel,
                    "expires_at": expires_at,
                    "destination": destination,
                    "baseline_generation": baseline_generation,
                    "target_generation": target_generation,
                },
            )
            return dict(
                db.execute("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            )

    def authorization_valid(self, proposal_id: str) -> bool:
        """Re-verify digest-bound approvals and live protected role bindings."""
        expected_profiles = {
            ReviewRole.ORCHESTRATOR.value: "agency-orchestrator",
            ReviewRole.SECURITY.value: "agency-security-reviewer",
            ReviewRole.CEO.value: "agency-ceo",
        }
        with self.connect() as db:
            proposal = db.execute(
                "SELECT candidate_digest,state,skill_name,policy_version,baseline_generation FROM proposals WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
            if not proposal or proposal["state"] != ProposalState.AUTHORIZED.value:
                return False
            requirements = db.execute(
                "SELECT role, satisfied FROM review_requirements WHERE proposal_id=?",
                (proposal_id,),
            ).fetchall()
            if not requirements or any(not row["satisfied"] for row in requirements):
                return False
            principals: set[str] = set()
            for requirement in requirements:
                row = db.execute(
                    """SELECT r.principal_id,r.candidate_digest,r.expires_at,r.policy_version,
                              r.destination,r.baseline_generation,r.target_generation,
                              b.profile_name,b.role,b.peer_id
                       FROM reviews r JOIN principal_bindings b ON b.principal_id=r.principal_id
                       WHERE r.proposal_id=? AND r.role=? AND r.decision='approve' AND b.enabled=1""",
                    (proposal_id, requirement["role"]),
                ).fetchone()
                if (
                    not row
                    or row["candidate_digest"] != proposal["candidate_digest"]
                    or row["role"] != requirement["role"]
                    or row["profile_name"] != expected_profiles[requirement["role"]]
                    or row["principal_id"] in principals
                    or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC)
                    or row["policy_version"] != proposal["policy_version"]
                    or row["destination"] != f"shared/{proposal['skill_name']}"
                    or row["baseline_generation"] != (proposal["baseline_generation"] or "<empty>")
                    or row["target_generation"]
                    != f"next:{proposal['baseline_generation'] or '<empty>'}:{proposal['candidate_digest']}"
                    or self.authenticator is None
                    or not self.authenticator.roster_matches(row["profile_name"], row["peer_id"])
                ):
                    return False
                principals.add(row["principal_id"])
            return True

    def _feedback(
        self,
        db: sqlite3.Connection,
        proposal_id: str,
        profile: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        version = db.execute(
            "SELECT state_version FROM proposals WHERE proposal_id=?", (proposal_id,)
        ).fetchone()[0]
        key = f"{proposal_id}:{event_type}:{version}"
        db.execute(
            "INSERT OR IGNORE INTO feedback_outbox(idempotency_key, proposal_id, target_profile, event_type, payload_json, created_at) VALUES (?,?,?,?,?,?)",
            (
                key,
                proposal_id,
                profile,
                event_type,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                utc_now(),
            ),
        )

    def feedback(self, proposal_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self.transaction() as db:
            row = db.execute(
                "SELECT source_profile FROM proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if not row:
                raise KeyError(proposal_id)
            self._feedback(db, proposal_id, row[0], event_type, payload)

    def list(self, *, state: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            if state:
                rows = db.execute(
                    "SELECT * FROM proposals WHERE state=? ORDER BY updated_at DESC LIMIT ?",
                    (state, min(max(limit, 1), 500)),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM proposals ORDER BY updated_at DESC LIMIT ?",
                    (min(max(limit, 1), 500),),
                ).fetchall()
            return [dict(row) for row in rows]

    def status(self) -> dict[str, Any]:
        with self.connect() as db:
            counts = {
                row[0]: row[1]
                for row in db.execute("SELECT state, COUNT(*) FROM proposals GROUP BY state")
            }
            return {
                "schema_version": _SCHEMA_VERSION,
                "proposals": sum(counts.values()),
                "by_state": counts,
                "outbox_pending": db.execute(
                    "SELECT COUNT(*) FROM feedback_outbox WHERE delivered_at IS NULL"
                ).fetchone()[0],
                "audit_events": db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
                "audit_chain_valid": self.verify_audit(db),
            }

    def verify_audit(self, db: sqlite3.Connection | None = None) -> bool:
        owned = db is None
        connection = db or self.connect()
        previous = "0" * 64
        try:
            for row in connection.execute("SELECT * FROM audit_events ORDER BY sequence"):
                material = canonical_json(
                    {
                        "event_id": row["event_id"],
                        "proposal_id": row["proposal_id"],
                        "actor": row["actor_principal"],
                        "action": row["action"],
                        "before": row["before_state"],
                        "after": row["after_state"],
                        "metadata": json.loads(row["metadata_json"]),
                        "created_at": row["created_at"],
                        "previous_hash": previous,
                    }
                )
                if (
                    row["previous_hash"] != previous
                    or hashlib.sha256(material).hexdigest() != row["event_hash"]
                ):
                    return False
                previous = row["event_hash"]
            try:
                checkpoint = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                return False
            last = connection.execute(
                "SELECT sequence,event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            expected = {
                "sequence": int(last[0]) if last else 0,
                "event_hash": str(last[1]) if last else "0" * 64,
            }
            return checkpoint == expected
        finally:
            if owned:
                connection.close()
