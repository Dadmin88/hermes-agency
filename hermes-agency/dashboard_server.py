"""Hermes Agency Dashboard — FastAPI server entry-point.

Creates the ASGI app, registers API and static routers, and starts uvicorn.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import webbrowser
from typing import Any

import uvicorn

from .dashboard_api import create_api_router
from .dashboard_models import DashboardSettings
from .dashboard_security import _set_expected_token, generate_session_token
from .dashboard_static import static_router

logger = logging.getLogger(__name__)

DASHBOARD_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    local_only: bool = True,
    session_token: str | None = None,
) -> tuple[Any, str]:
    """Create and return ``(FastAPI, session_token)``.

    The session token is generated if not supplied.  It is stored in the
    security module so that ``require_token`` dependencies work, and it is
    injected into index.html by the static router.
    """
    from fastapi import FastAPI

    token = session_token or generate_session_token()
    _set_expected_token(token)

    settings = DashboardSettings(
        host=host,
        port=port,
        local_only=local_only,
        server_start_time=time.time(),
        version=DASHBOARD_VERSION,
    )

    app = FastAPI(
        title="Hermes Agency Dashboard",
        version=DASHBOARD_VERSION,
        docs_url=None,  # Disable Swagger UI in production.
        redoc_url=None,
    )

    # Mount API router first (higher priority than SPA fallback).
    api_router = create_api_router(settings)
    app.include_router(api_router)

    # Mount static/SPA router last (catch-all for client-side routes).
    app.include_router(static_router)

    # Store token on app state for programmatic access.
    app.state.dashboard_token = token
    app.state.dashboard_settings = settings

    return app, token


# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------


def start_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    dev: bool = False,
    allow_lan: bool = False,
    session_token: str | None = None,
) -> None:
    """Start the dashboard server (blocking).

    Parameters
    ----------
    host:
        Bind address.  ``0.0.0.0`` is refused unless *allow_lan* is True.
    port:
        Bind port.
    open_browser:
        Open the default browser after the server starts.
    dev:
        Enable auto-reload (development mode).
    allow_lan:
        Explicit opt-in to LAN exposure.  Required when *host* is not
        a loopback address.
    session_token:
        Override the auto-generated session token (useful for testing).
    """
    # Refuse non-localhost without explicit opt-in.
    if host not in ("127.0.0.1", "localhost", "::1") and not allow_lan:
        print(
            f"ERROR: --host {host} exposes the dashboard to the network.\n"
            "       Use --allow-lan to confirm you want LAN access.\n"
            "       Defaulting to 127.0.0.1.",
            file=sys.stderr,
        )
        host = "127.0.0.1"

    local_only = host in ("127.0.0.1", "localhost", "::1")
    app, token = create_app(
        host=host,
        port=port,
        local_only=local_only,
        session_token=session_token,
    )

    url = f"http://{host}:{port}"
    # If binding to 0.0.0.0, show a more useful localhost URL for the user.
    display_url = f"http://127.0.0.1:{port}" if host == "0.0.0.0" else url

    print()
    print("  ┌─────────────────────────────────────────────┐")
    print("  │        Hermes Agency Dashboard               │")
    print("  ├─────────────────────────────────────────────┤")
    print(f"  │  URL:   {display_url:<37s} │")
    print(f"  │  Token: {token[:20]}...{' ' * 14}│")
    if not local_only:
        print(f"  │  LAN:   {host}:{port:<27s} │")
    print("  └─────────────────────────────────────────────┘")
    print()

    if open_browser:

        def _open() -> None:
            # Give uvicorn a moment to bind.
            import time as _t

            _t.sleep(1.5)
            try:
                webbrowser.open(display_url)
            except Exception:
                pass

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info" if not dev else "debug",
        reload=dev,
    )
