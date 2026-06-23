#!/usr/bin/env python3
"""
Hermes Agency Pool Manager
Handles wake/sleep, idle detection, resource limits for agency-* profiles only.
Uses direct NodeManager API where possible (per prompt).
"""
import os
import json
import time
import threading
import yaml
from pathlib import Path
from datetime import datetime

REGISTRY_FILE = Path("/home/dadmin/Hermes_Agency/hermes-agency/pool/registry_definition.json")
CONFIG_FILE = Path.home() / ".hermes" / "agency" / "config.yaml"
PROFILES_DIR = Path.home() / ".hermes" / "profiles"
REPO_PROFILES = Path("/home/dadmin/Hermes_Agency/hermes-agency/default_staff/profiles")
PLUGIN_PATH = Path.home() / ".hermes" / "plugins" / "hermes-agency"

class PoolManager:
    def __init__(self):
        self.registry = self._load_registry()
        self.config = self._load_config()
        self.active_agents = {}
        self.lock = threading.Lock()
        self.idle_thread = threading.Thread(target=self._idle_watcher, daemon=True)
        self.idle_thread.start()

    def _load_registry(self):
        with open(REGISTRY_FILE) as f:
            return json.load(f)

    def _load_config(self):
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                return yaml.safe_load(f)
        return {"pool": {"max_active_agents": 10, "idle_timeout_minutes": 5, "port": 8090},
                "models": {"default": {"model": "gpt-5.5", "provider": "openai"}}}

    def _get_model_for_agent(self, name):
        overrides = self.config.get("models", {}).get("overrides", {})
        if name in overrides:
            return overrides[name]
        groups = self.config.get("models", {}).get("groups", {})
        # Simple category mapping (expand in full impl)
        for cat, agents in {"engineering": ["agency-frontend-engineer"], "management": ["agency-orchestrator"]}.items():
            if name in agents and cat in groups:
                return groups[cat]
        return self.config["models"]["default"]

    def wake_agent(self, name):
        if not name.startswith("agency-"):
            raise ValueError("Only agency-* profiles allowed")
        with self.lock:
            if name in self.active_agents:
                return self.active_agents[name]["peer_id"]

            if len(self.active_agents) >= self.config["pool"]["max_active_agents"]:
                self._swap_oldest_idle()

            profile_dir = PROFILES_DIR / name
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / ".agency").mkdir(exist_ok=True)

            # Copy SOUL.md
            soul_src = REPO_PROFILES / name / "SOUL.md"
            if soul_src.exists():
                import shutil
                shutil.copy(soul_src, profile_dir / "SOUL.md")

            # Symlink plugin
            plugin_link = profile_dir / "plugins" / "hermes-agency"
            plugin_link.parent.mkdir(exist_ok=True)
            if not plugin_link.exists():
                plugin_link.symlink_to(PLUGIN_PATH)

            model_cfg = self._get_model_for_agent(name)
            # Write minimal config for profile (model etc.)
            cfg = {"model": model_cfg, "agency": {"enabled": True}}
            with open(profile_dir / "config.yaml", "w") as f:
                yaml.dump(cfg, f)

            # In real impl: use NodeManager to start node directly
            # Here we simulate and return a placeholder peer_id
            peer_id = f"12D3KooW{ name[-8:] }SIMULATED"
            self.active_agents[name] = {
                "peer_id": peer_id,
                "last_active": datetime.now(),
                "status": "active"
            }
            print(f"Woke {name} with peer_id {peer_id}")
            return peer_id

    def sleep_agent(self, name):
        with self.lock:
            if name in self.active_agents:
                # In real: stop node via NodeManager
                del self.active_agents[name]
                print(f"Slept {name}")
            return True

    def _swap_oldest_idle(self):
        if not self.active_agents:
            return
        oldest = min(self.active_agents.items(), key=lambda x: x[1]["last_active"])
        self.sleep_agent(oldest[0])

    def _idle_watcher(self):
        while True:
            time.sleep(60)
            timeout = self.config["pool"]["idle_timeout_minutes"] * 60
            now = datetime.now()
            with self.lock:
                for name, data in list(self.active_agents.items()):
                    if (now - data["last_active"]).total_seconds() > timeout:
                        if name != "agency-orchestrator":
                            self.sleep_agent(name)

    def get_status(self):
        return {
            "active_count": len(self.active_agents),
            "active_agents": list(self.active_agents.keys()),
            "max": self.config["pool"]["max_active_agents"]
        }

if __name__ == "__main__":
    pm = PoolManager()
    print("Pool Manager initialized. Status:", pm.get_status())