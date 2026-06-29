"""Static file serving for the Hermes Agency Vite React dashboard.

Serves the built frontend from hermes-agency/dashboard/dist/.
Injects the session token into index.html so the SPA can authenticate.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .dashboard_security import _get_expected_token

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def resolve_dashboard_dist() -> Path:
    """Return the absolute path to the Vite build output directory.

    Looks for ``hermes-agency/dashboard/dist/`` relative to the plugin root.
    """
    plugin_root = Path(__file__).resolve().parent
    return plugin_root / "dashboard" / "dist"


def _index_html_path() -> Path:
    return resolve_dashboard_dist() / "index.html"


def _assets_dir() -> Path:
    return resolve_dashboard_dist() / "assets"


# ---------------------------------------------------------------------------
# Token injection
# ---------------------------------------------------------------------------


def _inject_token(html: str, token: str) -> str:
    """Inject the session token into the HTML so the SPA can read it.

    We insert a ``<meta>`` tag right after ``<head>`` so the React app can
    read ``document.querySelector('meta[name="hermes-dashboard-token"]')?.content``.
    """
    meta_tag = f'<meta name="hermes-dashboard-token" content="{token}">'
    # Insert after the first <head> tag (case-insensitive).
    lower = html.lower()
    head_idx = lower.find("<head")
    if head_idx == -1:
        # No <head> found; prepend.
        return meta_tag + html
    # Find the end of the opening <head> or <head ...> tag.
    close_idx = html.find(">", head_idx)
    if close_idx == -1:
        return meta_tag + html
    insert_pos = close_idx + 1
    return html[:insert_pos] + "\n    " + meta_tag + html[insert_pos:]


# ---------------------------------------------------------------------------
# Route handlers (mounted as a non-API router)
# ---------------------------------------------------------------------------


static_router = APIRouter()


@static_router.get("/", response_class=HTMLResponse)
async def serve_index() -> Response:
    """Serve index.html with the session token injected."""
    index_path = _index_html_path()
    if not index_path.exists():
        return _missing_build_response()
    html = index_path.read_text(encoding="utf-8")
    token = _get_expected_token()
    if token:
        html = _inject_token(html, token)
    return HTMLResponse(content=html)


@static_router.get("/assets/{file_path:path}")
async def serve_assets(file_path: str) -> Response:
    """Serve Vite-hashed assets from dist/assets/."""
    assets_dir = _assets_dir().resolve()
    asset = (assets_dir / file_path).resolve()
    try:
        asset.relative_to(assets_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Asset not found: {file_path}") from None
    if not asset.exists() or not asset.is_file():
        raise HTTPException(status_code=404, detail=f"Asset not found: {file_path}")
    # Determine content type from suffix.
    suffix = asset.suffix.lower()
    content_types = {
        ".js": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".map": "application/json",
    }
    media_type = content_types.get(suffix, "application/octet-stream")
    return Response(content=asset.read_bytes(), media_type=media_type)


@static_router.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_fallback(full_path: str) -> Response:
    """SPA fallback: serve index.html for any unmatched client-side route.

    API routes (``/api/...``) are registered on a separate router with higher
    priority, so they never reach this handler.
    """
    index_path = _index_html_path()
    if not index_path.exists():
        return _missing_build_response()
    html = index_path.read_text(encoding="utf-8")
    token = _get_expected_token()
    if token:
        html = _inject_token(html, token)
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _missing_build_response() -> Response:
    """Return a helpful error when the Vite build output is missing."""
    dist = resolve_dashboard_dist()
    message = (
        f"Dashboard frontend build not found at {dist}.\n\n"
        "To build the frontend:\n"
        "  cd hermes-agency/dashboard\n"
        "  npm install\n"
        "  npm run build\n\n"
        "This produces the dist/ directory that the dashboard server serves."
    )
    logger.warning("Dashboard build missing: %s", dist)
    return JSONResponse(
        status_code=503,
        content={
            "error": "dashboard_build_missing",
            "message": message,
            "dist_path": str(dist),
        },
    )
