"""Authenticated, non-string authority capabilities for skill governance."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import ReviewRole

_EXPECTED_PROFILES = {
    ReviewRole.ORCHESTRATOR: "agency-orchestrator",
    ReviewRole.SECURITY: "agency-security-reviewer",
    ReviewRole.CEO: "agency-ceo",
}


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    principal_id: str
    profile_name: str
    role: ReviewRole
    peer_id: str
    channel: str
    authenticated_at: str
    valid_until: str
    process_uid: int
    proof: str


@dataclass(frozen=True)
class PromoterAuthority:
    process_uid: int
    executable: str
    authenticated_at: str
    valid_until: str
    proof: str


class PrincipalAuthenticator:
    """Issues short-lived capabilities after managed-roster and process checks.

    The secret is process-local and never accepted from an API caller. Production
    constructs this adapter from the authenticated Keryx roster/socket boundary;
    tests may supply a deterministic roster and UID.
    """

    def __init__(
        self,
        roster: Mapping[str, str],
        *,
        promoter_uid: int | None = None,
        promoter_executable: str | Path | None = None,
        credential_verifier: Callable[[object], Mapping[str, Any] | None] | None = None,
        secret: bytes | None = None,
    ):
        self._roster = dict(roster)
        self.promoter_uid = -1 if promoter_uid is None else int(promoter_uid)
        self.promoter_executable = (
            str(Path(promoter_executable).resolve()) if promoter_executable is not None else ""
        )
        self._credential_verifier = credential_verifier
        self._secret = secret or secrets.token_bytes(32)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def _sign(self, *parts: object) -> str:
        body = "\0".join(str(part) for part in parts).encode()
        return hmac.new(self._secret, body, hashlib.sha256).hexdigest()

    def authenticate(
        self,
        *,
        credential: object,
        ttl_seconds: int = 300,
    ) -> AuthenticatedPrincipal:
        identity = self._credential_verifier(credential) if self._credential_verifier else None
        if not identity:
            raise PermissionError("no authenticated identity adapter accepted the credential")
        try:
            principal_id = str(identity["principal_id"])
            profile_name = str(identity["profile_name"])
            role = ReviewRole(identity["role"])
            peer_id = str(identity["peer_id"])
            channel = str(identity["channel"])
            uid = int(identity["process_uid"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PermissionError("authenticated identity assertion is incomplete") from exc
        expected = _EXPECTED_PROFILES[role]
        if profile_name != expected or self._roster.get(profile_name) != peer_id or not peer_id:
            raise PermissionError("principal does not match the managed Agency roster")
        if not channel.startswith(("unix-peer:", "keryx-auth:")):
            raise PermissionError("review channel is not authenticated")
        now = self._now()
        until = now + timedelta(seconds=max(1, min(ttl_seconds, 900)))
        material = (
            principal_id,
            profile_name,
            role.value,
            peer_id,
            channel,
            now.isoformat(),
            until.isoformat(),
            uid,
        )
        return AuthenticatedPrincipal(
            principal_id=principal_id,
            profile_name=profile_name,
            role=role,
            peer_id=peer_id,
            channel=channel,
            authenticated_at=now.isoformat(),
            valid_until=until.isoformat(),
            process_uid=uid,
            proof=self._sign(*material),
        )

    def verify(self, principal: AuthenticatedPrincipal) -> bool:
        try:
            until = datetime.fromisoformat(principal.valid_until)
        except ValueError:
            return False
        material = (
            principal.principal_id,
            principal.profile_name,
            principal.role.value,
            principal.peer_id,
            principal.channel,
            principal.authenticated_at,
            principal.valid_until,
            principal.process_uid,
        )
        return (
            until > self._now()
            and principal.profile_name == _EXPECTED_PROFILES[principal.role]
            and self._roster.get(principal.profile_name) == principal.peer_id
            and hmac.compare_digest(principal.proof, self._sign(*material))
        )

    def authenticate_promoter(self, *, ttl_seconds: int = 120) -> PromoterAuthority:
        """Mint a capability only from the kernel-observed process identity."""
        uid = os.geteuid()
        executable = str(Path("/proc/self/exe").resolve())
        if uid != self.promoter_uid or executable != self.promoter_executable:
            raise PermissionError("caller is not the configured promoter process")
        now = self._now()
        until = now + timedelta(seconds=max(1, min(ttl_seconds, 300)))
        material = (uid, executable, now.isoformat(), until.isoformat())
        return PromoterAuthority(*material, self._sign(*material))

    def verify_promoter(self, authority: PromoterAuthority) -> bool:
        if not isinstance(authority, PromoterAuthority):
            return False
        try:
            until = datetime.fromisoformat(authority.valid_until)
        except ValueError:
            return False
        material = (
            authority.process_uid,
            authority.executable,
            authority.authenticated_at,
            authority.valid_until,
        )
        return (
            until > self._now()
            and authority.process_uid == self.promoter_uid
            and authority.process_uid == os.geteuid()
            and authority.executable == self.promoter_executable
            and authority.executable == str(Path("/proc/self/exe").resolve())
            and hmac.compare_digest(authority.proof, self._sign(*material))
        )

    def roster_matches(self, profile_name: str, peer_id: str) -> bool:
        return bool(peer_id) and self._roster.get(profile_name) == peer_id
