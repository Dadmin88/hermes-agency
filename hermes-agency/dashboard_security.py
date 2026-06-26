"""Security helpers for the Hermes Agency dashboard.

Default posture: localhost-only, token-gated, no CORS, no LAN exposure.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence

from fastapi import Header, HTTPException, status


def generate_session_token() -> str:
    """Generate a cryptographically random session token."""
    return secrets.token_urlsafe(32)


def validate_token(token: str | None, expected: str) -> bool:
    """Constant-time comparison of the supplied token against the expected value."""
    if not token or not expected:
        return False
    # secrets.compare_digest avoids timing side-channels
    return secrets.compare_digest(token, expected)


def validate_origin(origin: str | None, allowed_hosts: Sequence[str]) -> bool:
    """Return True when *origin* matches one of *allowed_hosts*.

    ``allowed_hosts`` entries may be plain hostnames or ``scheme://host`` URIs.
    An empty *allowed_hosts* list means "reject everything except same-origin".
    """
    if not origin:
        # Same-origin requests omit Origin; allow them through.
        return True
    if not allowed_hosts:
        return False
    origin_lower = origin.strip().lower().rstrip("/")
    for host in allowed_hosts:
        host_lower = host.strip().lower().rstrip("/")
        if origin_lower == host_lower:
            return True
        # Also accept bare hostname matching against the origin's host part.
        if "://" in origin_lower:
            origin_host = origin_lower.split("://", 1)[1]
            if origin_host == host_lower or origin_host.split(":")[0] == host_lower:
                return True
    return False


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

_DASHBOARD_TOKEN_HEADER = "x-hermes-dashboard-token"


async def _require_token_dependency(
    x_hermes_dashboard_token: str | None = Header(default=None),
) -> str:
    """FastAPI dependency that enforces the dashboard session token.

    Callers must set ``X-Hermes-Dashboard-Token: <token>`` on every mutating
    request.  The expected token is injected at startup via
    ``_set_expected_token()``.
    """
    expected = _get_expected_token()
    if not expected:
        # If no token was configured (shouldn't happen in production), deny.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dashboard security token is not configured on the server.",
        )
    if not validate_token(x_hermes_dashboard_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Hermes-Dashboard-Token header.",
        )
    assert x_hermes_dashboard_token is not None  # validated above
    return x_hermes_dashboard_token


# Module-level expected token store (set once at startup).
_expected_token: str = ""


def _set_expected_token(token: str) -> None:
    global _expected_token  # noqa: PLW0603
    _expected_token = token


def _get_expected_token() -> str:
    return _expected_token


# Re-export the dependency under a public name for use in routers.
require_token = _require_token_dependency
