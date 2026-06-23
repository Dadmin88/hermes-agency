#!/usr/bin/env python3
"""
Hermes Agency Pool Manager
Handles wake/sleep for agency-* profiles only. Direct NodeManager integration.
"""

import importlib.util
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

REGISTRY_DEF = Path(__file__).with_name("registry_definition.json")
AGENCY_CONFIG = Path("/home/dadmin/.hermes/agency/config.yaml")
PROFILES_DIR = Path("/home/dadmin/.hermes/profiles")
PLUGIN_PATH = Path("/home/dadmin/.hermes/plugins/hermes-agency")
DEFAULT_SOUL_SRC = Path("/home/dadmin/Hermes_Agency/hermes-agency/default_staff/profiles")
KANBAN_WORKER_SKILL_SRC = Path("/home/dadmin/.hermes/skills/devops/kanban-worker")
HERMES_BIN = "/home/dadmin/.local/bin/hermes"
HERMES_PYTHON = "/home/dadmin/.hermes/hermes-agent/venv/bin/python"
NODE_RUNNER = Path("/home/dadmin/Hermes_Agency/hermes-agency/pool/agency_node_runner.py")
PEER_ID_RE = re.compile(r"(12D3KooW[0-9A-Za-z]+)")
OWN_PEER_ID_RE = re.compile(r'(?:"peer_id"\s*:\s*"|^PEER_ID=)(12D3KooW[0-9A-Za-z]+)', re.MULTILINE)
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
ED25519_PUBLIC_KEY_PREFIX = bytes([0x08, 0x01, 0x12, 0x20])
IDENTITY_MULTIHASH_CODE = 0x00
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_PROVIDER = "openai-codex"
KANBAN_SOUL_MARKER = "<!-- hermes-agency-kanban-worker -->"


def _base58_encode(data: bytes) -> str:
    """Encode bytes as base58btc without adding the multibase prefix."""

    number = int.from_bytes(data, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = BASE58_ALPHABET[remainder] + encoded
    leading_zeroes = len(data) - len(data.lstrip(b"\0"))
    return (BASE58_ALPHABET[0] * leading_zeroes) + (encoded or BASE58_ALPHABET[0])


def _libp2p_peer_id_from_public_key(public_key: bytes) -> str:
    """Derive an Ed25519 libp2p PeerID from a raw 32-byte public key."""

    if len(public_key) != 32:
        raise ValueError(f"expected 32-byte Ed25519 public key, got {len(public_key)} bytes")
    public_key_proto = ED25519_PUBLIC_KEY_PREFIX + public_key
    identity_multihash = bytes([IDENTITY_MULTIHASH_CODE, len(public_key_proto)]) + public_key_proto
    return _base58_encode(identity_multihash)


class PoolManager:
    def __init__(self):
        self.config = self._load_config()
        self.registry = self._load_registry()
        self.active = {}  # name -> {'peer_id': str, 'last_active': datetime, 'proc': Popen|None, 'persistent': bool}
        self.persistent_agents = {"agency-orchestrator"}
        self.lock = threading.RLock()
        self._start_idle_monitor()
        # Spin up agency-orchestrator as persistent A2A node (always on)
        try:
            self.wake("agency-orchestrator", persistent=True)
            print("[PoolManager] agency-orchestrator started persistently")
        except Exception as e:
            print(f"[PoolManager] orchestrator start warning: {e}")

    def _load_config(self):
        if AGENCY_CONFIG.exists():
            with open(AGENCY_CONFIG) as f:
                return yaml.safe_load(f)
        return {
            "pool": {"max_active_agents": 10, "idle_timeout_minutes": 5, "port": 8090},
            "models": {"default": {"model": DEFAULT_MODEL, "provider": DEFAULT_PROVIDER}},
        }

    def _load_registry(self):
        if REGISTRY_DEF.exists():
            with open(REGISTRY_DEF) as f:
                return json.load(f)
        return {"agents": []}

    def _roster_module(self):
        """Load pool.roster in package and direct-script execution modes."""

        try:
            from . import roster

            return roster
        except ImportError:
            module_path = Path(__file__).with_name("roster.py")
            spec = importlib.util.spec_from_file_location("hermes_agency_pool_roster", module_path)
            if spec is None or spec.loader is None:
                raise
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

    def _record_roster_wake(
        self,
        name: str,
        *,
        success: bool,
        peer_id: str | None = None,
        error: str | None = None,
    ) -> None:
        try:
            self._roster_module().record_wake_attempt(
                name, success=success, peer_id=peer_id, error=error
            )
        except Exception as exc:
            print(f"[PoolManager] roster wake update warning for {name}: {exc}")

    def _record_roster_status(
        self,
        name: str,
        *,
        online: bool,
        peer_id: str | None = None,
        error: str | None = None,
    ) -> None:
        try:
            self._roster_module().update_agent_status(
                name, online=online, peer_id=peer_id, error=error
            )
        except Exception as exc:
            print(f"[PoolManager] roster status update warning for {name}: {exc}")

    def _get_model(self, name):
        models = self.config.get("models", {})
        if name in models.get("overrides", {}):
            return self._normalise_model_config(models["overrides"][name])
        for group, m in models.get("groups", {}).items():
            if any(name.endswith(a) for a in [group] + []):  # simplified
                return self._normalise_model_config(m)
        model = models.get("default", {"model": DEFAULT_MODEL, "provider": DEFAULT_PROVIDER})
        return self._normalise_model_config(model)

    def _normalise_model_config(self, model):
        """Return a Hermes-current provider/model pair for worker profiles.

        Older pool configs used provider names such as ``openai``/``xai`` that
        are no longer valid on this VPS Hermes install. Kanban workers exit rc=0
        before loading tools when the provider is invalid, which the dispatcher
        records as a protocol violation. Keep the pool safe by defaulting every
        agency worker to the known-good OpenAI Codex OAuth provider.
        """
        configured = dict(model or {})
        provider = (configured.get("provider") or DEFAULT_PROVIDER).strip()
        provider_aliases = {
            "openai": "openai-codex",
            "xai": "xai-oauth",
        }
        configured["provider"] = provider_aliases.get(provider, provider)
        if configured["provider"] == "openai-codex":
            configured["model"] = configured.get("model") or DEFAULT_MODEL
        else:
            configured["model"] = configured.get("model") or DEFAULT_MODEL
        return configured

    def _registry_agent(self, name):
        for agent in self.registry.get("agents", []):
            if agent.get("name") == name:
                return agent
        return {"name": name, "description": f"{name} agent", "skills": [], "category": "agency"}

    def _role_title(self, name):
        return name.removeprefix("agency-").replace("-", " ").title()

    def _kanban_worker_soul_section(self, agent):
        skills = agent.get("skills") or []
        skill_lines = "\n".join(f"- {skill}" for skill in skills) or "- general task execution"
        return (
            f"\n\n{KANBAN_SOUL_MARKER}\n"
            "## Kanban Worker Protocol\n\n"
            "When the Hermes Kanban dispatcher starts this profile, you are a headless "
            "worker for exactly one assigned card. Treat the injected Kanban guidance "
            "and the `kanban-worker` skill as authoritative.\n\n"
            "1. Call `kanban_show()` first to read the assigned task, comments, prior "
            "runs, dependencies, and workspace.\n"
            "2. Work only inside `$HERMES_KANBAN_WORKSPACE` unless the task explicitly "
            "authorizes another path.\n"
            "3. Use `kanban_heartbeat(note=...)` during long-running operations.\n"
            "4. If blocked by missing information, credentials, access, or a human "
            "decision, add useful context with `kanban_comment(...)` and then call "
            "`kanban_block(reason=...)`. Do not call `clarify` in worker mode.\n"
            "5. Before exiting, you MUST call either `kanban_complete(summary=..., "
            "metadata=...)` for genuinely finished work or `kanban_block(reason=...)` "
            "for incomplete work. A plain text answer is not a valid worker result.\n"
            "6. Create follow-up cards with `kanban_create(...)` only when the next work "
            "belongs to another specialist; do not silently scope-creep.\n\n"
            "### Registry Skills\n\n"
            f"{skill_lines}\n"
        )

    def _generated_soul(self, name):
        agent = self._registry_agent(name)
        role = self._role_title(name)
        skills = agent.get("skills") or []
        skill_lines = "\n".join(f"- {skill}" for skill in skills) or "- general task execution"
        return (
            f"# SOUL.md — {role}\n\n"
            "## Identity\n\n"
            f"You are `{name}`, the Hermes Agency {role}.\n\n"
            "## Role Description\n\n"
            f"{agent.get('description') or role + ' agent'}\n\n"
            "## Skills\n\n"
            f"{skill_lines}\n\n"
            "## Operating Principles\n\n"
            "- Stay inside your specialty unless the task explicitly asks otherwise.\n"
            "- Prefer concrete artifacts, verified results, and concise handoffs.\n"
            "- Escalate to the right specialist by creating Kanban follow-up cards when needed.\n"
            "- Do not deploy, publish, delete, or mutate production resources without explicit approval."
            f"{self._kanban_worker_soul_section(agent)}"
        )

    def _ensure_soul(self, name, profile_dir):
        soul_path = profile_dir / "SOUL.md"
        agent = self._registry_agent(name)
        if soul_path.exists():
            content = soul_path.read_text(encoding="utf-8", errors="ignore")
            if KANBAN_SOUL_MARKER not in content:
                soul_path.write_text(
                    content.rstrip() + self._kanban_worker_soul_section(agent) + "\n",
                    encoding="utf-8",
                )
            return

        soul_src = DEFAULT_SOUL_SRC / name / "SOUL.md"
        if soul_src.exists():
            content = soul_src.read_text(encoding="utf-8", errors="ignore")
            if KANBAN_SOUL_MARKER not in content:
                content = content.rstrip() + self._kanban_worker_soul_section(agent) + "\n"
            soul_path.write_text(content, encoding="utf-8")
            return

        soul_path.write_text(self._generated_soul(name) + "\n", encoding="utf-8")

    def _ensure_kanban_worker_skill(self, profile_dir):
        if not KANBAN_WORKER_SKILL_SRC.exists():
            print(f"[PoolManager] kanban-worker skill source missing: {KANBAN_WORKER_SKILL_SRC}")
            return
        link = profile_dir / "skills" / "devops" / "kanban-worker"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            if link.is_symlink():
                if link.resolve(strict=False) != KANBAN_WORKER_SKILL_SRC.resolve(strict=True):
                    link.unlink()
                    link.symlink_to(KANBAN_WORKER_SKILL_SRC, target_is_directory=True)
                return
            if link.exists():
                return
            link.symlink_to(KANBAN_WORKER_SKILL_SRC, target_is_directory=True)
        except OSError as exc:
            print(
                f"[PoolManager] kanban-worker skill install warning for {profile_dir.name}: {exc}"
            )

    def _ensure_profile_config(self, profile_dir, model):
        config_path = profile_dir / "config.yaml"
        try:
            config = (
                yaml.safe_load(config_path.read_text(encoding="utf-8"))
                if config_path.exists()
                else {}
            )
        except Exception:
            config = {}
        if not isinstance(config, dict):
            config = {}

        model = self._normalise_model_config(model)
        config.setdefault("model", {})
        config["model"]["default"] = model.get("model", DEFAULT_MODEL)
        config["model"]["provider"] = model.get("provider", DEFAULT_PROVIDER)
        config.setdefault("kanban", {})
        config["kanban"]["dispatch_in_gateway"] = True
        config.setdefault("plugins", {})
        enabled = config["plugins"].get("enabled") or []
        if isinstance(enabled, str):
            enabled = [enabled]
        if "hermes-agency" not in enabled:
            enabled.append("hermes-agency")
        config["plugins"]["enabled"] = enabled
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    def _extract_peer_id(self, text):
        if not text:
            return None
        match = PEER_ID_RE.search(text)
        return match.group(1) if match else None

    def _profile_env(self, name):
        env = os.environ.copy()
        profile_dir = PROFILES_DIR / name
        env.update(
            {
                "HERMES_PROFILE": name,
                "HERMES_HOME": str(profile_dir),
                "HERMES_AGENCY_PLUGIN_PATH": str(PLUGIN_PATH),
                "PYTHONUNBUFFERED": "1",
            }
        )
        return env

    def _ensure_profile(self, name):
        profile_dir = PROFILES_DIR / name
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / ".agency").mkdir(exist_ok=True)

        self._ensure_soul(name, profile_dir)
        self._ensure_kanban_worker_skill(profile_dir)

        plugin_link = profile_dir / "plugins" / "hermes-agency"
        plugin_link.parent.mkdir(exist_ok=True)
        if not plugin_link.exists():
            plugin_link.symlink_to(PLUGIN_PATH)

        model = self._get_model(name)
        self._ensure_profile_config(profile_dir, model)
        return profile_dir

    def _status_peer_id_from_cli(self, name):
        try:
            result = subprocess.run(
                [HERMES_BIN, "-p", name, "agency", "status"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            return self._extract_peer_id(output), output
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def _peer_id_from_log(self, name):
        """Read this daemon's own PeerID from AgentAnycast/Hermes Agency logs.

        Daemon logs contain many remote peer IDs in task/discovery entries. Only
        accept explicit own-node markers: JSON `peer_id` on the `agentanycastd
        started` line or the plain `PEER_ID=...` line emitted at startup.
        """
        candidates = [
            PROFILES_DIR / name / ".agentanycast" / "logs" / "daemon.log",
            PROFILES_DIR / name / ".agency" / "logs" / "daemon.log",
        ]
        for path in candidates:
            try:
                if path.exists():
                    data = path.read_text(errors="ignore")[-50000:]
                    matches = OWN_PEER_ID_RE.findall(data)
                    if matches:
                        return matches[-1], str(path)
            except Exception as exc:
                print(f"[PoolManager] log peer_id read warning for {path}: {exc}")
        return None, None

    def _peer_id_from_key(self, name):
        """Derive this daemon's PeerID from its Ed25519 private key file.

        AgentAnycast stores Ed25519 private keys as 64 bytes where the final 32
        bytes are the public key. libp2p PeerID for Ed25519 is an identity
        multihash over the protobuf-encoded public key.
        """
        candidates = [
            PROFILES_DIR / name / ".agentanycast" / "key",
            PROFILES_DIR / name / ".agency" / "key",
        ]
        found = {}
        for path in candidates:
            try:
                if not path.exists():
                    continue
                found["key"] = str(path)
                data = path.read_bytes()
                if len(data) >= 64:
                    return _libp2p_peer_id_from_public_key(data[-32:]), found
                if len(data) == 32:
                    return _libp2p_peer_id_from_public_key(data), found
            except Exception as exc:
                print(f"[PoolManager] key peer_id read warning for {path}: {exc}")
        return None, found

    def _check_agency_files(self, name):
        """Best-effort diagnostics for known AgentAnycast/Hermes Agency files."""
        found = {}
        for base in (PROFILES_DIR / name / ".agentanycast", PROFILES_DIR / name / ".agency"):
            for child in ("daemon.sock", "key"):
                path = base / child
                if path.exists():
                    found[str(path.relative_to(PROFILES_DIR / name))] = str(path)
        return found

    def _resolve_started_peer_id(self, name, initial_output="", timeout=10):
        """Resolve a real PeerID after daemon startup through status/log/key."""
        peer_id = self._extract_peer_id(initial_output)
        if peer_id:
            return peer_id, "start output"

        deadline = time.time() + timeout
        last_status_output = ""
        while time.time() <= deadline:
            status_peer, status_output = self._status_peer_id_from_cli(name)
            last_status_output = status_output
            if status_peer:
                return status_peer, "agency status"

            log_peer, log_path = self._peer_id_from_log(name)
            if log_peer:
                return log_peer, f"log:{log_path}"

            key_peer, key_files = self._peer_id_from_key(name)
            if key_peer:
                return key_peer, f"key:{key_files.get('key')}"

            time.sleep(1)

        print(
            f"[PoolManager] final agency status output for {name}: {last_status_output.strip()[:1000]}"
        )
        return None, "unresolved"

    def _start_cli_node(self, name):
        """Try the documented Hermes plugin CLI start path.

        Some installed Hermes builds do not expose plugin CLI commands; the caller
        treats failures here as non-fatal and falls back to the long-lived runner.
        The boolean return value means the CLI accepted the start command; only in
        that case is it safe to resolve peer IDs from existing log/key files.
        """
        try:
            result = subprocess.run(
                [HERMES_BIN, "-p", name, "agency", "start"],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            peer_id = self._extract_peer_id(output)
            return peer_id, output, result.returncode == 0
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}", False

    def _stop_cli_node(self, name):
        try:
            result = subprocess.run(
                [HERMES_BIN, "-p", name, "agency", "stop"],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return result.returncode == 0, (result.stdout or "") + "\n" + (result.stderr or "")
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def _start_runner_node(self, name):
        profile_dir = PROFILES_DIR / name
        proc = subprocess.Popen(
            [HERMES_PYTHON, str(NODE_RUNNER)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=self._profile_env(name),
            cwd=str(profile_dir),
        )
        deadline = time.time() + 150
        output_lines = []
        peer_id = None
        while time.time() < deadline:
            if proc.stdout is None:
                break
            line = proc.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                print(f"[PoolManager:{name}] {line.rstrip()}")
                peer_id = self._extract_peer_id(line)
                if line.startswith("HERMES_AGENCY_NODE_STATE") and peer_id:
                    # Give the daemon a few seconds to publish/register before returning.
                    time.sleep(5)
                    return peer_id, proc, "\n".join(output_lines)
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.2)
        if proc.poll() is None and not peer_id:
            proc.terminate()
        return peer_id, proc, "\n".join(output_lines)

    def wake(self, name, persistent=False):
        if not name.startswith("agency-"):
            raise ValueError("Only agency-* profiles allowed")
        persistent = persistent or name in self.persistent_agents
        with self.lock:
            existing = self.active.get(name)
            if existing:
                proc = existing.get("proc")
                if proc is None or proc.poll() is None:
                    existing["last_active"] = datetime.now()
                    self._record_roster_status(name, online=True, peer_id=existing.get("peer_id"))
                    return existing["peer_id"]
                print(f"[PoolManager] Removing stale process for {name}")
                del self.active[name]

            active_pool_count = sum(1 for d in self.active.values() if not d.get("persistent"))
            if not persistent and active_pool_count >= self.config["pool"]["max_active_agents"]:
                self._swap_oldest()

            self._ensure_profile(name)

            # First try the documented CLI flow: start, wait 5s for the
            # daemon, then resolve a real peer_id from status/log/key.
            cli_peer, cli_output, cli_started = self._start_cli_node(name)
            if cli_output:
                print(f"[PoolManager] agency start output for {name}: {cli_output.strip()[:1000]}")
            peer_id = None
            if cli_started:
                time.sleep(5)
                peer_id, peer_source = self._resolve_started_peer_id(
                    name, initial_output=cli_output if cli_peer else "", timeout=5
                )
                if peer_id:
                    print(f"[PoolManager] resolved {name} peer_id from {peer_source}: {peer_id}")
            else:
                print(
                    f"[PoolManager] agency start CLI unavailable/failed for {name}; falling back to runner"
                )
            proc = None

            # Current VPS Hermes build does not expose `hermes agency`; keep the
            # node alive in this pool-manager process via a long-lived child.
            if not peer_id:
                peer_id, proc, runner_output = self._start_runner_node(name)
                if not peer_id:
                    log_peer = log_path = key_peer = None
                    key_files = {}
                    # Only use file-derived peer IDs if the runner is still
                    # alive; otherwise old key/log files can produce stale IDs.
                    if proc is not None and proc.poll() is None:
                        log_peer, log_path = self._peer_id_from_log(name)
                        key_peer, key_files = self._peer_id_from_key(name)
                        peer_id = log_peer or key_peer
                    if not peer_id:
                        agency_files = self._check_agency_files(name)
                        details = runner_output or cli_output or "no output"
                        error = (
                            f"Unable to determine real peer_id for {name}. "
                            f"agency_files={agency_files}; key_files={key_files}; "
                            f"log_path={log_path}; output={details[:1000]}"
                        )
                        self._record_roster_wake(name, success=False, error=error)
                        raise RuntimeError(error)

            self.active[name] = {
                "peer_id": peer_id,
                "last_active": datetime.now(),
                "proc": proc,
                "persistent": persistent,
            }
            self.registry["agents"] = [
                a for a in self.registry.get("agents", []) if a["name"] != name
            ]
            print(f"[PoolManager] Woke {name} with peer_id {peer_id} (persistent={persistent})")
            self._record_roster_wake(name, success=True, peer_id=peer_id)
            return peer_id

    def sleep(self, name):
        with self.lock:
            data = self.active.get(name)
            if not data:
                return False
            if data.get("persistent"):
                print(f"[PoolManager] Refusing to sleep persistent agent {name}")
                return False
            proc = data.get("proc")
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
            else:
                stopped, stop_output = self._stop_cli_node(name)
                if stop_output:
                    print(
                        f"[PoolManager] agency stop output for {name}: {stop_output.strip()[:1000]}"
                    )
                if not stopped:
                    print(
                        f"[PoolManager] CLI stop unavailable/failed for {name}; removing from active registry only"
                    )
            del self.active[name]
            self._record_roster_status(name, online=False)
            print(f"[PoolManager] Slept {name}")
            return True

    def _swap_oldest(self):
        pool_agents = {n: d for n, d in self.active.items() if not d.get("persistent")}
        if not pool_agents:
            return
        oldest = min(pool_agents.items(), key=lambda x: x[1]["last_active"])
        self.sleep(oldest[0])

    def _start_idle_monitor(self):
        def monitor():
            while True:
                time.sleep(60)
                with self.lock:
                    now = datetime.now()
                    timeout = timedelta(minutes=self.config["pool"]["idle_timeout_minutes"])
                    to_sleep = [
                        n
                        for n, d in self.active.items()
                        if now - d["last_active"] > timeout and n != "agency-orchestrator"
                    ]
                    for n in to_sleep:
                        self.sleep(n)

        t = threading.Thread(target=monitor, daemon=True)
        t.start()

    def status(self):
        active_pool = [n for n, d in self.active.items() if not d.get("persistent")]
        persistent = [n for n, d in self.active.items() if d.get("persistent")]
        return {
            "active": len(active_pool),
            "max": self.config["pool"]["max_active_agents"],
            "agents": active_pool,
            "persistent": persistent,
            "peer_ids": {n: d["peer_id"] for n, d in self.active.items()},
        }


if __name__ == "__main__":
    pm = PoolManager()
    print("PoolManager initialized")
