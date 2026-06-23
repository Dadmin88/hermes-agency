#!/usr/bin/env python3
"""
Hermes Agency Pool Manager HTTP Service
FastAPI/Flask-style lightweight server on configured port.
"""
from flask import Flask, jsonify, request
from manager import PoolManager
import threading

app = Flask(__name__)
pm = PoolManager()

@app.route("/pool/agents", methods=["GET"])
def list_agents():
    return jsonify({"agents": list(pm.registry["agents"].keys()), "active": pm.get_status()})

@app.route("/pool/agents/<name>", methods=["GET"])
def agent_details(name):
    if name not in pm.registry["agents"]:
        return jsonify({"error": "not found"}), 404
    return jsonify(pm.registry["agents"][name] | {"status": pm.active_agents.get(name, {"status": "sleeping"})})

@app.route("/pool/agents/<name>/wake", methods=["POST"])
def wake(name):
    try:
        peer_id = pm.wake_agent(name)
        return jsonify({"status": "woken", "peer_id": peer_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/pool/agents/<name>/sleep", methods=["POST"])
def sleep(name):
    pm.sleep_agent(name)
    return jsonify({"status": "sleeping"})

@app.route("/pool/agents/<name>/task", methods=["POST"])
def delegate_task(name):
    data = request.json or {}
    peer_id = pm.wake_agent(name)
    # In real: a2a_send via SDK
    return jsonify({"status": "delegated", "peer_id": peer_id, "task": data.get("message")})

@app.route("/pool/status", methods=["GET"])
def status():
    return jsonify(pm.get_status())

if __name__ == "__main__":
    port = pm.config["pool"]["port"]
    print(f"Starting pool service on port {port}")
    app.run(host="0.0.0.0", port=port)