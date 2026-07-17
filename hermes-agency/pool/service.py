#!/usr/bin/env python3
"""
Hermes Agency Pool Manager Service
FastAPI/Flask HTTP server on configured port.

Security notes:
- Binds to 127.0.0.1 by default (loopback only).  Set HERMES_POOL_BIND=0.0.0.0
  to expose on all interfaces; this also requires a valid bearer token.
- Bearer token auth is enforced on every mutating endpoint. When
  HERMES_POOL_TOKEN is unset, mutations fail closed with HTTP 503.
"""

import hmac
import os
from pathlib import Path

from flask import Flask, jsonify, request
from manager import PoolManager

try:
    from skills import effective_agent_skills, list_shared_skills, set_shared_pool_enabled
except ImportError:  # package-relative fallback
    from .skills import effective_agent_skills, list_shared_skills, set_shared_pool_enabled

POOL_TOKEN = os.environ.get("HERMES_POOL_TOKEN", "")
BIND_HOST = os.environ.get("HERMES_POOL_BIND", "127.0.0.1")

app = Flask(__name__)
pm = PoolManager()


def _hermes_home():
    return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()


def _profiles_dir():
    return Path(os.environ.get("HERMES_PROFILES_DIR", _hermes_home() / "profiles")).expanduser()


def _shared_skills_path():
    """Resolve the configured pool without exposing its host path in responses."""
    configured = os.environ.get("HERMES_SHARED_SKILLS_PATH", "").strip()
    if configured:
        return os.path.expanduser(configured)
    return str(_hermes_home() / "skills" / "shared")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _check_token() -> bool:
    """Return True only when mutation authentication is configured and valid."""
    if not POOL_TOKEN:
        return False
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    presented = auth[len("Bearer ") :]
    return hmac.compare_digest(presented, POOL_TOKEN)


def _require_token():
    """Return a Flask error response unless mutation authentication is ready and valid."""
    if not POOL_TOKEN:
        return jsonify({"error": "mutation authentication is not configured"}), 503
    if not _check_token():
        return jsonify({"error": "unauthorized"}), 401
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/pool/agents", methods=["GET"])
def list_agents():
    return jsonify({"agents": pm.registry.get("agents", []), "active": pm.status()})


@app.route("/pool/agents/<name>", methods=["GET"])
def get_agent(name):
    for a in pm.registry.get("agents", []):
        if a["name"] == name:
            return jsonify(a)
    return jsonify({"error": "not found"}), 404


@app.route("/pool/agents/<name>/wake", methods=["POST"])
def wake_agent(name):
    deny = _require_token()
    if deny is not None:
        return deny
    try:
        pm._validate_agent_name(name)
        peer_id = pm.wake(name)
        return jsonify({"status": "waking", "peer_id": peer_id})
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/pool/agents/<name>/sleep", methods=["POST"])
def sleep_agent(name):
    deny = _require_token()
    if deny is not None:
        return deny
    try:
        pm._validate_agent_name(name)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    success = pm.sleep(name)
    return jsonify({"status": "sleeping" if success else "noop"})


@app.route("/pool/agents/<name>/task", methods=["POST"])
def delegate_task(name):
    deny = _require_token()
    if deny is not None:
        return deny
    try:
        pm._validate_agent_name(name)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    data = request.json or {}
    peer_id = pm.wake(name)
    return jsonify({"status": "delegated", "peer_id": peer_id, "task": data.get("message")})


@app.route("/pool/status", methods=["GET"])
def pool_status():
    return jsonify(pm.status())


@app.route("/pool/skills", methods=["GET"])
def list_shared_skill_pool():
    """Authenticated, metadata-only inventory of the shared skill pool."""
    deny = _require_token()
    if deny is not None:
        return deny
    return jsonify({"skills": list_shared_skills(Path(_shared_skills_path()))})


@app.route("/pool/agents/<name>/skills", methods=["GET"])
def get_effective_agent_skills(name):
    """Show the actual resolver precedence for one profile, not fleet-wide availability."""
    deny = _require_token()
    if deny is not None:
        return deny
    try:
        pm._validate_agent_name(name)
        return jsonify(
            effective_agent_skills(
                profiles_root=_profiles_dir(),
                shared_skills_path=Path(_shared_skills_path()),
                profile_name=name,
            )
        )
    except KeyError:
        return jsonify({"error": "not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/pool/agents/<name>/skills/shared-pool", methods=["PUT"])
def configure_effective_agent_skills(name):
    """Enable or remove the shared pool from one profile's effective skill set."""
    deny = _require_token()
    if deny is not None:
        return deny
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get("enabled"), bool):
        return jsonify({"error": "enabled must be a boolean"}), 400
    try:
        pm._validate_agent_name(name)
        return jsonify(
            set_shared_pool_enabled(
                profiles_root=_profiles_dir(),
                shared_skills_path=Path(_shared_skills_path()),
                profile_name=name,
                enabled=data["enabled"],
            )
        )
    except KeyError:
        return jsonify({"error": "not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


def run():
    port = pm.config["pool"]["port"]
    if BIND_HOST not in ("127.0.0.1", "localhost", "::1") and not POOL_TOKEN:
        raise SystemExit(
            "FATAL: HERMES_POOL_BIND is set to a non-loopback address but "
            "HERMES_POOL_TOKEN is empty. Refusing to start without authentication. "
            "Set HERMES_POOL_TOKEN or bind to 127.0.0.1."
        )
    print(f"Starting Pool Manager Service on {BIND_HOST}:{port}")
    app.run(host=BIND_HOST, port=port, threaded=True)


if __name__ == "__main__":
    run()
