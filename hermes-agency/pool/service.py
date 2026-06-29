#!/usr/bin/env python3
"""
Hermes Agency Pool Manager Service
FastAPI/Flask HTTP server on configured port.

Security notes:
- Binds to 127.0.0.1 by default (loopback only).  Set HERMES_POOL_BIND=0.0.0.0
  to expose on all interfaces; this also requires a valid bearer token.
- Bearer token auth is enforced on all mutating endpoints when
  HERMES_POOL_TOKEN is set.
"""

import hmac
import os

from flask import Flask, jsonify, request
from manager import PoolManager

POOL_TOKEN = os.environ.get("HERMES_POOL_TOKEN", "")
BIND_HOST = os.environ.get("HERMES_POOL_BIND", "127.0.0.1")

app = Flask(__name__)
pm = PoolManager()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _check_token() -> bool:
    """Return True when the request carries a valid bearer token, or when no
    token is configured (local-only / development mode)."""
    if not POOL_TOKEN:
        return True
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    presented = auth[len("Bearer ") :]
    return hmac.compare_digest(presented, POOL_TOKEN)


def _require_token():
    """Abort with 401 if the bearer token is missing or wrong."""
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


def run():
    port = pm.config["pool"]["port"]
    print(f"Starting Pool Manager Service on {BIND_HOST}:{port}")
    app.run(host=BIND_HOST, port=port, threaded=True)


if __name__ == "__main__":
    run()
