#!/usr/bin/env python3
"""
Hermes Agency Pool Manager Service
FastAPI/Flask HTTP server on configured port.
"""

import os

from flask import Flask, jsonify, request
from manager import PoolManager

app = Flask(__name__)
pm = PoolManager()


def _auth_token():
    return os.environ.get("HERMES_POOL_TOKEN") or pm.config.get("pool", {}).get("auth_token")


def _authorized():
    token = _auth_token()
    if not token:
        return False
    return request.headers.get("Authorization") == f"Bearer {token}"


@app.before_request
def require_auth_for_state_changes():
    if request.method == "POST" and not _authorized():
        return jsonify({"error": "unauthorized"}), 401
    return None


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
    try:
        peer_id = pm.wake(name)
        return jsonify({"status": "waking", "peer_id": peer_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/pool/agents/<name>/sleep", methods=["POST"])
def sleep_agent(name):
    success = pm.sleep(name)
    return jsonify({"status": "sleeping" if success else "noop"})


@app.route("/pool/agents/<name>/task", methods=["POST"])
def delegate_task(name):
    data = request.json or {}
    peer_id = pm.wake(name)
    # In real: a2a_send via plugin
    return jsonify({"status": "delegated", "peer_id": peer_id, "task": data.get("message")})


@app.route("/pool/status", methods=["GET"])
def pool_status():
    return jsonify(pm.status())


def run():
    port = pm.config["pool"]["port"]
    print(f"Starting Pool Manager Service on port {port}")
    host = pm.config.get("pool", {}).get("host", "127.0.0.1")
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    run()
