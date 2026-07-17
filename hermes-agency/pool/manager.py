#!/usr/bin/env python3
"""
Hermes Agency Pool Manager
Handles wake/sleep for agency-* profiles only. Direct NodeManager integration.
"""

import ctypes
import gc
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

try:
    from .memory_tracker import MemoryTracker
except ImportError:
    _mt_path = Path(__file__).with_name("memory_tracker.py")
    _mt_spec = importlib.util.spec_from_file_location("memory_tracker", _mt_path)
    if _mt_spec and _mt_spec.loader:
        _mt_mod = importlib.util.module_from_spec(_mt_spec)
        _mt_spec.loader.exec_module(_mt_mod)
        MemoryTracker = _mt_mod.MemoryTracker
    else:
        MemoryTracker = None  # type: ignore[assignment,misc]

REGISTRY_DEF = Path(__file__).with_name("registry_definition.json")
HOME = Path.home()
HERMES_HOME = Path(os.environ.get("HERMES_HOME", HOME / ".hermes")).expanduser()
REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = Path(__file__).resolve().parents[1]

AGENCY_CONFIG = Path(
    os.environ.get("HERMES_AGENCY_CONFIG", HERMES_HOME / "agency" / "config.yaml")
).expanduser()
PROFILES_DIR = Path(os.environ.get("HERMES_PROFILES_DIR", HERMES_HOME / "profiles")).expanduser()
PLUGIN_PATH = Path(
    os.environ.get("HERMES_AGENCY_PLUGIN_PATH", HERMES_HOME / "plugins" / "hermes-agency")
).expanduser()
DEFAULT_SOUL_SRC = Path(
    os.environ.get("HERMES_AGENCY_DEFAULT_STAFF_DIR", PLUGIN_ROOT / "default_staff" / "profiles")
).expanduser()
KANBAN_WORKER_SKILL_SRC = Path(
    os.environ.get(
        "HERMES_AGENCY_KANBAN_WORKER_SKILL", HERMES_HOME / "skills" / "devops" / "kanban-worker"
    )
).expanduser()
HERMES_BIN = os.environ.get("HERMES_BIN", str(HOME / ".local" / "bin" / "hermes"))
HERMES_PYTHON = os.environ.get(
    "HERMES_PYTHON", str(HERMES_HOME / "hermes-agent" / "venv" / "bin" / "python")
)
NODE_RUNNER = Path(
    os.environ.get("HERMES_AGENCY_NODE_RUNNER", PLUGIN_ROOT / "pool" / "agency_node_runner.py")
).expanduser()
PEER_ID_RE = re.compile(r"(12D3KooW[0-9A-Za-z]+)")
OWN_PEER_ID_LINE_RE = re.compile(r"^PEER_ID=(12D3KooW[0-9A-Za-z]+)$")
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
ED25519_PUBLIC_KEY_PREFIX = bytes([0x08, 0x01, 0x12, 0x20])
IDENTITY_MULTIHASH_CODE = 0x00
DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_PROVIDER = "openai-codex"
KANBAN_SOUL_MARKER = "<!-- hermes-agency-kanban-worker -->"


def _transport_backend() -> str:
    """Return the configured pool transport backend, defaulting to Keryx."""

    try:
        from ..config import get_config

        backend = str(getattr(get_config(), "transport_backend", "keryx") or "keryx")
    except Exception:
        backend = str(
            os.environ.get("HERMES_AGENCY_TRANSPORT_BACKEND")
            or os.environ.get("AGENCY_TRANSPORT_BACKEND")
            or "keryx"
        )
    backend = backend.strip().lower().replace("_", "-")
    if backend in {"agentanycast", "agent-anycast", "anycast"}:
        return "agentanycast"
    return "keryx"


def send_task_via_transport(
    *,
    message: str,
    peer_id: str,
    wait_seconds: float = 0,
    metadata: dict[str, str] | None = None,
) -> dict[str, object]:
    """Route an outbound pool task through the configured transport.

    Keryx is the default. AgentAnycast is used only when legacy mode is selected.
    The singleton NodeManager owns the selected transport implementation.
    """

    from ..node_manager import manager

    return manager.send_task_sync(
        message=message,
        peer_id=peer_id,
        wait_seconds=wait_seconds,
        metadata=metadata,
    )


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


def _running_inside_gateway() -> bool:
    """Return true when the pool manager is loaded inside `hermes gateway run`.

    The gateway process already owns the active profile's in-process NodeManager.
    Starting a second long-lived runner for the orchestrator from inside that same
    gateway contends for the same AgentAnycast BoltDB store and causes repeated
    `open bolt db: timeout` failures.
    """

    return os.environ.get("_HERMES_GATEWAY") == "1"


class PoolManager:
    def __init__(self):
        self.config = self._load_config()
        self.registry = self._load_registry()
        self.active = {}  # name -> {'peer_id': str, 'last_active': datetime, 'proc': Popen|None, 'persistent': bool}
        self.persistent_agents = {"agency-orchestrator"}
        self.lock = threading.RLock()
        self._pending_restarts: list[str] = []
        self.memory_tracker = MemoryTracker() if MemoryTracker is not None else None
        self._last_memory_log = 0.0
        # Spin up agency-orchestrator as persistent A2A node only for standalone
        # pool-manager use. Inside `hermes gateway run`, the plugin's in-process
        # NodeManager already starts the orchestrator node; a child runner would
        # duplicate the same profile home and lock the same BoltDB store.
        if _running_inside_gateway():
            print("[PoolManager] gateway mode detected; using in-process orchestrator node")
            self._start_idle_monitor()
            return
        try:
            self._start_idle_monitor()
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

    def _is_agent_disabled(self, name: str) -> bool:
        """Return whether the roster marks an agent as disabled."""

        try:
            return bool(self._roster_module().is_agent_disabled(name))
        except Exception as exc:
            print(f"[PoolManager] roster disabled check warning for {name}: {exc}")
            return False

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

        Older pool configs may use deprecated provider aliases. Normalize them so
        workers reach Hermes with a supported provider name instead of failing
        before tool loading.
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

    def _registered_agent_names(self):
        """Return the set of known agent names from the registry."""
        return {a.get("name") for a in self.registry.get("agents", [])}

    def _validate_agent_name(self, name: str) -> None:
        """Validate that *name* matches the ``agency-*`` pattern and exists in the
        registry.  Raises :class:`ValueError` on invalid input and
        :class:`KeyError` when the name is not in the registry."""
        if not isinstance(name, str) or not name.startswith("agency-"):
            raise ValueError("Only agency-* profiles allowed")
        if name not in self._registered_agent_names():
            raise KeyError(f"Agent {name!r} not found in registry")

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
                    matches = []
                    for line in data.splitlines():
                        plain_match = OWN_PEER_ID_LINE_RE.fullmatch(line)
                        if plain_match:
                            matches.append(plain_match.group(1))
                            continue
                        try:
                            entry = json.loads(line)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if (
                            not isinstance(entry, dict)
                            or entry.get("event") != "agentanycastd started"
                        ):
                            continue
                        peer_id = entry.get("peer_id")
                        if isinstance(peer_id, str) and PEER_ID_RE.fullmatch(peer_id):
                            matches.append(peer_id)
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
        # If the runner is still alive but did not emit HERMES_AGENCY_NODE_STATE
        # on the captured pipe, keep it running so wake() can resolve the peer ID
        # from the daemon log/key. Some Hermes runtimes redirect later runner
        # output to the per-profile runner log, while the child daemon is already
        # healthy and registered.
        return peer_id, proc, "\n".join(output_lines)

    def _terminate_runner_proc(self, proc):
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)

    def wake(self, name, persistent=False):
        if self._is_agent_disabled(name):
            raise ValueError(
                f"Agent {name} is disabled. Use pool_enable_agent to re-enable it first."
            )
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
            effective_max = self._effective_max_agents()
            if not persistent and active_pool_count >= effective_max:
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
                sock = PROFILES_DIR / name / ".agency" / "daemon.sock"
                if not sock.exists():
                    print(
                        f"[PoolManager] agency start for {name} exited without a live daemon socket; falling back to runner"
                    )
                    cli_started = False
                else:
                    peer_id, peer_source = self._resolve_started_peer_id(
                        name, initial_output=cli_output if cli_peer else "", timeout=5
                    )
                    if peer_id:
                        print(
                            f"[PoolManager] resolved {name} peer_id from {peer_source}: {peer_id}"
                        )
            if not cli_started:
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
                        self._terminate_runner_proc(proc)
                        raise RuntimeError(error)

            self.active[name] = {
                "peer_id": peer_id,
                "last_active": datetime.now(),
                "woke_at": datetime.now(),
                "proc": proc,
                "persistent": persistent,
                "rss_at_wake_mb": None,
            }
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
                self._terminate_runner_proc(proc)
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
            self._release_memory()
            print(f"[PoolManager] Slept {name}")
            return True

    def _swap_oldest(self):
        pool_agents = {n: d for n, d in self.active.items() if not d.get("persistent")}
        if not pool_agents:
            return
        oldest = min(pool_agents.items(), key=lambda x: x[1]["last_active"])
        self.sleep(oldest[0])

    def _release_memory(self):
        """Force Python to return freed memory to the OS."""
        gc.collect()
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError, ValueError):
            pass  # Non-glibc or musl — best effort

    def _effective_max_agents(self) -> int:
        """Compute max agents based on memory budget and current usage."""
        configured_max = self.config["pool"]["max_active_agents"]
        budget_mb = self.config["pool"].get("memory_budget_mb", 1500)
        current_rss_mb = self.memory_tracker.get_process_rss_mb()
        available_mb = self.memory_tracker.get_system_available_mb()

        # If over 80% of budget or system memory critically low, force reduction
        if current_rss_mb > budget_mb * 0.8:
            return max(1, len([a for a in self.active.values() if not a.get("persistent")]) - 1)
        if available_mb < 500:
            return max(1, len([a for a in self.active.values() if not a.get("persistent")]) - 1)
        return configured_max

    def _enforce_memory_budget(self, current_rss_mb: float, budget_mb: float):
        """Swap out idle agents until we're under the memory budget."""
        critical_mb = self.config["pool"].get("memory_critical_threshold_mb", 2000)
        available_mb = self.memory_tracker.get_system_available_mb()

        if current_rss_mb > critical_mb or available_mb < 300:
            # Critical: sleep ALL non-persistent agents
            to_sleep = [n for n, d in self.active.items() if not d.get("persistent")]
            for name in to_sleep:
                self.sleep(name)
            print(
                f"[PoolManager] CRITICAL memory: {current_rss_mb:.0f} MB RSS, {available_mb:.0f} MB avail — slept ALL non-persistent agents"
            )
            return

        # Over budget: sleep oldest idle agents one at a time
        pool_agents = {n: d for n, d in self.active.items() if not d.get("persistent")}
        while pool_agents and current_rss_mb > budget_mb:
            oldest = min(pool_agents.items(), key=lambda x: x[1]["last_active"])
            self.sleep(oldest[0])
            del pool_agents[oldest[0]]
            self._release_memory()
            current_rss_mb = self.memory_tracker.get_process_rss_mb()
            print(
                f"[PoolManager] Memory budget: slept {oldest[0]}, RSS now {current_rss_mb:.0f} MB"
            )

    def _log_memory_stats(self):
        """Log memory stats every 5 minutes."""
        now = time.time()
        if now - self._last_memory_log < 300:
            return
        self._last_memory_log = now
        report = self.memory_tracker.get_pool_memory_report(self.active)
        budget_mb = self.config["pool"].get("memory_budget_mb", 1500)
        print(
            f"[PoolManager] Memory: RSS={report['process_rss_mb']:.0f}MB "
            f"budget={budget_mb}MB "
            f"system_avail={report['system_available_mb']:.0f}MB "
            f"agents={report['agent_count']} "
            f"per_agent={report['per_agent_mb']}"
        )

    def _start_idle_monitor(self):
        def monitor():
            while True:
                check_interval = self.config["pool"].get("memory_check_interval_seconds", 30)
                time.sleep(check_interval)
                try:
                    with self.lock:
                        now = datetime.now()
                        timeout = timedelta(minutes=self.config["pool"]["idle_timeout_minutes"])

                        # Update per-agent RSS for agents with proc handles
                        for name, data in self.active.items():
                            proc = data.get("proc")
                            if proc is not None and hasattr(proc, "pid") and proc.poll() is None:
                                try:
                                    data["rss_at_wake_mb"] = round(
                                        self.memory_tracker.get_child_rss_mb(proc.pid), 1
                                    )
                                except (ProcessLookupError, OSError):
                                    pass

                        # Sleep idle agents
                        to_sleep = [
                            n
                            for n, d in self.active.items()
                            if now - d["last_active"] > timeout and n != "agency-orchestrator"
                        ]
                        for n in to_sleep:
                            self.sleep(n)

                        # Health watchdog: detect crashed agents
                        crashed = []
                        for n, d in list(self.active.items()):
                            proc = d.get("proc")
                            if proc is not None and hasattr(proc, "pid"):
                                if proc.poll() is not None:
                                    crashed.append((n, d))
                        for n, d in crashed:
                            exit_code = d.get("proc").returncode if d.get("proc") else "?"
                            print(
                                f"[PoolManager] Health watchdog: {n} crashed "
                                f"(exit={exit_code}), removing from active pool"
                            )
                            self.active.pop(n, None)
                            # Mark for auto-restart (handled outside lock)
                            woke_at = d.get("woke_at")
                            if (
                                woke_at is not None
                                and not d.get("persistent")
                                and (now - woke_at).total_seconds() < 600
                            ):
                                self._pending_restarts.append(n)

                        # Memory budget enforcement
                        rss_mb = self.memory_tracker.get_process_rss_mb()
                        budget_mb = self.config["pool"].get("memory_budget_mb", 1500)
                        if rss_mb > budget_mb:
                            self._enforce_memory_budget(rss_mb, budget_mb)

                        # Always release memory every cycle — Python's pymalloc
                        # holds freed pages; malloc_trim returns them to the OS.
                        self._release_memory()

                        # Periodic memory stats logging
                        self._log_memory_stats()
                except Exception as exc:
                    print(f"[PoolManager] idle monitor error: {exc}")

                # Auto-restart crashed agents (outside lock to avoid deadlock)
                pending = list(self._pending_restarts)
                self._pending_restarts.clear()
                for agent_name in pending:
                    try:
                        print(f"[PoolManager] Health watchdog: auto-restarting {agent_name}")
                        self.wake(agent_name)
                    except Exception as restart_exc:
                        print(
                            f"[PoolManager] Health watchdog: restart of {agent_name} "
                            f"failed: {restart_exc}"
                        )

        t = threading.Thread(target=monitor, daemon=True)
        t.start()

    def status(self):
        active_pool = [n for n, d in self.active.items() if not d.get("persistent")]
        persistent = [n for n, d in self.active.items() if d.get("persistent")]
        memory_report = self.memory_tracker.get_pool_memory_report(self.active)
        budget_mb = self.config["pool"].get("memory_budget_mb", 1500)
        return {
            "active": len(active_pool),
            "max": self.config["pool"]["max_active_agents"],
            "effective_max": self._effective_max_agents(),
            "agents": active_pool,
            "persistent": persistent,
            "peer_ids": {n: d["peer_id"] for n, d in self.active.items()},
            "memory": {
                "process_rss_mb": memory_report["process_rss_mb"],
                "budget_mb": budget_mb,
                "system_available_mb": memory_report["system_available_mb"],
                "system_used_pct": memory_report["system_used_pct"],
                "per_agent_mb": memory_report["per_agent_mb"],
            },
        }


if __name__ == "__main__":
    pm = PoolManager()
    print("PoolManager initialized")
