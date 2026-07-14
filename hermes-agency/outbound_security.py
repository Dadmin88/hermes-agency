"""Sanitize remote-visible Hermes Agency outputs before persistence or transport.

Pattern matching cannot detect every secret. This boundary reduces accidental
credential leakage in progress updates, final artifacts, and remote error text.
Detailed raw diagnostics should stay local only.
"""

from __future__ import annotations

import re
from typing import Literal

RemoteKind = Literal["progress", "artifact", "error", "rejection", "generic"]

DEFAULT_MAX_CHARS = {
    "progress": 2_000,
    "artifact": 32_000,
    "error": 512,
    "rejection": 256,
    "generic": 8_000,
}

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([a-z0-9_.-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|authorization|"
    r"bearer[_-]?token|token|password|secret|credential|private[_-]?key))\b\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_TOKEN_RE = re.compile(r"\b(?:sk|pk|rk|key)-[A-Za-z0-9_-]{8,}\b")
_PEM_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_URL_CREDS_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@")
_HOME_PATH_RE = re.compile(r"(?i)(?:/home|/Users)/[^\s'\"`]+")
_FILE_URL_RE = re.compile(r"(?i)\bfile://[^\s'\"`]+")

_STABLE_REMOTE_ERRORS = {
    "missing_peer_id": "authorization_rejected",
    "not_in_allowlist": "authorization_rejected",
    "blocked": "authorization_rejected",
    "insufficient_trust": "authorization_rejected",
    "tampered_metadata": "authorization_rejected",
    "authorization_revoked": "authorization_rejected",
}


def sanitize_remote_text(
    text: str | None,
    *,
    kind: RemoteKind = "generic",
    max_chars: int | None = None,
) -> str:
    """Redact sensitive patterns and bound size for remote-visible text."""

    value = str(text or "")
    if not value:
        return ""

    sanitized = _PEM_RE.sub("-----BEGIN PRIVATE KEY-----<redacted>-----END PRIVATE KEY-----", value)
    sanitized = _URL_CREDS_RE.sub(r"\1<redacted>:<redacted>@", sanitized)
    sanitized = _BEARER_RE.sub("Bearer <redacted>", sanitized)
    sanitized = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", sanitized)
    sanitized = _TOKEN_RE.sub("<redacted>", sanitized)
    sanitized = _HOME_PATH_RE.sub("<redacted-path>", sanitized)
    sanitized = _FILE_URL_RE.sub("file://<redacted-path>", sanitized)

    limit = (
        max_chars
        if max_chars is not None
        else DEFAULT_MAX_CHARS.get(kind, DEFAULT_MAX_CHARS["generic"])
    )
    limit = max(32, int(limit))
    if len(sanitized) <= limit:
        return sanitized
    return sanitized[: max(0, limit - 16)] + "…[truncated]"


def stable_remote_error(action_or_reason: str | None, *, fallback: str = "task_failed") -> str:
    """Map internal rejection actions to stable remote-safe error codes."""

    key = str(action_or_reason or "").strip().lower()
    if key in _STABLE_REMOTE_ERRORS:
        return _STABLE_REMOTE_ERRORS[key]
    if key in {"authorization_rejected", "task_failed", "handler_timeout"}:
        return key
    # Never echo raw exception content as the remote code.
    if "timeout" in key:
        return "handler_timeout"
    if "authoriz" in key or "allowlist" in key or "trust" in key or "blocked" in key:
        return "authorization_rejected"
    return fallback
