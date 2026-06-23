#!/usr/bin/env python3
"""
Hermes Agency Pool Manager
Handles wake/sleep for agency-* profiles only. Direct NodeManager integration.
"""

import os
import json
import time
import threading
import yaml
from pathlib import Path
from datetime import datetime, timedelta

REGISTRY_DEF = Path('/home/dadmin/Hermes_Agency/hermes-agency/pool/registry_definition.json')
AGENCY_CONFIG = Path('/home/dadmin/.hermes/agency/config.yaml')
PROFILES_DIR = Path('/home/dadmin/.hermes/profiles')
PLUGIN_PATH = Path('/home/dadmin/.hermes/plugins/hermes-agency')
DEFAULT_SOUL_SRC = Path('/home/dadmin/Hermes_Agency/hermes-agency/default_staff/profiles')

class PoolManager:
    def __init__(self):
        self.config = self._load_config()
        self.registry = self._load_registry()
        self.active = {}  # name -> {'peer_id': , 'last_active': }
        self.lock = threading.Lock()
        self._start_idle_monitor()

    def _load_config(self):
        if AGENCY_CONFIG.exists():
            with open(AGENCY_CONFIG) as f:
                return yaml.safe_load(f)
        return {'pool': {'max_active_agents': 10, 'idle_timeout_minutes': 5, 'port': 8090}, 'models': {'default': {'model': 'gpt-5.5', 'provider': 'openai'}}}

    def _load_registry(self):
        if REGISTRY_DEF.exists():
            with open(REGISTRY_DEF) as f:
                return json.load(f)
        return {'agents': []}

    def _get_model(self, name):
        models = self.config.get('models', {})
        if name in models.get('overrides', {}):
            return models['overrides'][name]
        for group, m in models.get('groups', {}).items():
            if any(name.endswith(a) for a in [group] + []):  # simplified
                return m
        return models.get('default', {'model': 'gpt-5.5', 'provider': 'openai'})

    def wake(self, name):
        if not name.startswith('agency-'):
            raise ValueError("Only agency-* profiles allowed")
        with self.lock:
            if name in self.active:
                return self.active[name]['peer_id']
            if len(self.active) >= self.config['pool']['max_active_agents']:
                self._swap_oldest()

            profile_dir = PROFILES_DIR / name
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / '.agency').mkdir(exist_ok=True)

            # Copy SOUL.md
            soul_src = DEFAULT_SOUL_SRC / name / 'SOUL.md'
            if soul_src.exists():
                import shutil
                shutil.copy(soul_src, profile_dir / 'SOUL.md')

            # Symlink plugin
            plugin_link = profile_dir / 'plugins' / 'hermes-agency'
            plugin_link.parent.mkdir(exist_ok=True)
            if not plugin_link.exists():
                plugin_link.symlink_to(PLUGIN_PATH)

            model = self._get_model(name)
            # Write minimal config for profile
            cfg = {'model': model['model'], 'provider': model['provider']}
            with open(profile_dir / 'config.yaml', 'w') as f:
                yaml.dump(cfg, f)

            # In real impl: use NodeManager to start node directly
            # For now, simulate and return mock peer_id
            peer_id = f"12D3KooW{hash(name) % 100000000000000000000:020d}"
            self.active[name] = {'peer_id': peer_id, 'last_active': datetime.now()}
            self.registry['agents'] = [a for a in self.registry.get('agents', []) if a['name'] != name]
            # update registry status would go here
            print(f"[PoolManager] Woke {name} with peer_id {peer_id}")
            return peer_id

    def sleep(self, name):
        with self.lock:
            if name in self.active:
                del self.active[name]
                print(f"[PoolManager] Slept {name}")
                return True
            return False

    def _swap_oldest(self):
        if not self.active:
            return
        oldest = min(self.active.items(), key=lambda x: x[1]['last_active'])
        self.sleep(oldest[0])

    def _start_idle_monitor(self):
        def monitor():
            while True:
                time.sleep(60)
                with self.lock:
                    now = datetime.now()
                    timeout = timedelta(minutes=self.config['pool']['idle_timeout_minutes'])
                    to_sleep = [n for n, d in self.active.items() 
                                if now - d['last_active'] > timeout and n != 'agency-orchestrator']
                    for n in to_sleep:
                        self.sleep(n)
        t = threading.Thread(target=monitor, daemon=True)
        t.start()

    def status(self):
        return {
            'active': len(self.active),
            'max': self.config['pool']['max_active_agents'],
            'agents': list(self.active.keys())
        }

if __name__ == '__main__':
    pm = PoolManager()
    print("PoolManager initialized")