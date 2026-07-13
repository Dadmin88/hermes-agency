"""Recovered/queued tasks must re-authorize against current policy before execution."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    full = f"hermes_plugin_test.{name}"
    spec = importlib.util.spec_from_file_location(full, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    # Ensure relative imports inside the package resolve.
    if "hermes_plugin_test" not in sys.modules:
        pkg = types.ModuleType("hermes_plugin_test")
        pkg.__path__ = [str(PLUGIN_DIR)]
        sys.modules["hermes_plugin_test"] = pkg
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def security_modules(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()
    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: hermes_home
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    # Minimal hermes_cli.cfg_get used by config.
    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli_config = types.ModuleType("hermes_cli.config")

    def cfg_get(config, *path, default=None):
        value = config
        for key in path:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return value

    hermes_cli_config.cfg_get = cfg_get
    hermes_cli_config.load_config = lambda: {}
    hermes_cli.config = hermes_cli_config
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_cli_config)

    # Load as package members so relative imports work.
    pkg = types.ModuleType("hermes_plugin")
    pkg.__path__ = [str(PLUGIN_DIR)]
    monkeypatch.setitem(sys.modules, "hermes_plugin", pkg)

    loaded = {}
    for module_name in ("config", "trust", "incoming_security"):
        full_name = f"hermes_plugin.{module_name}"
        spec = importlib.util.spec_from_file_location(full_name, PLUGIN_DIR / f"{module_name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full_name, module)
        spec.loader.exec_module(module)
        loaded[module_name] = module
    return loaded, hermes_home


def _cfg(security_modules, *, allowlist: list[str], peers: dict | None = None):
    mods, hermes_home = security_modules
    config_mod, trust_mod = mods["config"], mods["trust"]
    relay = config_mod.RelaySecurityConfig(allowlist=tuple(allowlist), allow_all=False)
    trust_path = hermes_home / "agency" / "trust.json"
    trust_path.parent.mkdir(parents=True, exist_ok=True)
    trust_cfg = config_mod.TrustConfig(store_path=str(trust_path), tofu=True)
    cfg = config_mod.AgencyConfig(
        enabled=True,
        allow_remote_tasks=True,
        trusted_peers=list(allowlist),
        relay_security=relay,
        trust=trust_cfg,
    )
    # Seed trust store through public API when possible.
    store = trust_mod.store_for_config(cfg)
    for peer_id, level in (peers or {}).items():
        store.verify_peer(peer_id, name=peer_id, trust_level="full", source="test")
        if level != "full":
            store.set_trust(peer_id, trust_level=level)
    return cfg


def test_authorize_recovered_requires_sender(security_modules):
    mods, _ = security_modules
    sec = mods["incoming_security"]
    cfg = _cfg(security_modules, allowlist=["peer-a"], peers={"peer-a": "full"})
    decision = sec.authorize_recovered_record(cfg, sender_peer_id="")
    assert decision.allowed is False
    assert decision.action == "missing_peer_id"


def test_authorize_recovered_rejects_allowlist_removal(security_modules):
    mods, _ = security_modules
    sec = mods["incoming_security"]
    cfg = _cfg(security_modules, allowlist=["peer-a"], peers={"peer-a": "full"})
    ok = sec.authorize_recovered_record(cfg, sender_peer_id="peer-a")
    assert ok.allowed is True

    cfg2 = _cfg(security_modules, allowlist=["other"], peers={"peer-a": "full"})
    denied = sec.authorize_recovered_record(cfg2, sender_peer_id="peer-a")
    assert denied.allowed is False
    assert denied.action in {"not_in_allowlist", "blocked", "insufficient_trust"}


def test_authorize_recovered_rejects_tampered_metadata(security_modules):
    mods, _ = security_modules
    sec = mods["incoming_security"]
    cfg = _cfg(security_modules, allowlist=["peer-a"], peers={"peer-a": "full"})
    decision = sec.authorize_recovered_record(
        cfg,
        sender_peer_id="peer-a",
        metadata={"sender_peer_id": "peer-b"},
    )
    assert decision.allowed is False
    assert decision.action == "tampered_metadata"


def test_authorize_recovered_rejects_blocked_peer(security_modules):
    mods, _ = security_modules
    sec = mods["incoming_security"]
    cfg = _cfg(security_modules, allowlist=["peer-a"], peers={"peer-a": "blocked"})
    decision = sec.authorize_recovered_record(cfg, sender_peer_id="peer-a")
    assert decision.allowed is False


@pytest.mark.asyncio
async def test_worker_blocks_recovered_without_remote_content_leak(security_modules, monkeypatch):
    """Drive IncomingQueueMixin._authorize_record_for_execution fail-closed path."""

    mods, hermes_home = security_modules
    # Load outbound + queue modules into the hermes_plugin package used by security fixture.
    for module_name in ("outbound_security", "control_messages", "incoming_queue"):
        full_name = f"hermes_plugin.{module_name}"
        if full_name in sys.modules and module_name != "incoming_queue":
            continue
        path = PLUGIN_DIR / f"{module_name}.py"
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location(full_name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full_name, module)
        try:
            spec.loader.exec_module(module)
        except Exception:
            if module_name == "incoming_queue":
                raise
            continue

    queue_mod = sys.modules["hermes_plugin.incoming_queue"]
    out_mod = sys.modules["hermes_plugin.outbound_security"]

    cfg = _cfg(security_modules, allowlist=[], peers={})
    record = queue_mod.IncomingTaskRecord(
        task_id="task-recovered-1",
        sender_peer_id="revoked-peer",
        sender_card={"name": "revoked-agent"},
        target_skill_id="",
        message_text="do not leak SECRET_TOKEN=sk-supersecret123456 to remote",
        metadata={"recovered": True, "sender_peer_id": "revoked-peer"},
    )

    class _NM:
        def get_config(self):
            return cfg

        def kanban_update_task(self, *args, **kwargs):
            return {}

    class _Host(queue_mod.IncomingQueueMixin):
        def __init__(self):
            self._incoming_records = {record.task_id: record}
            self._incoming_order = [record.task_id]
            self.state = types.SimpleNamespace()

        def _nm(self):
            return _NM()

        def _call_on_agency_board(self, *args, **kwargs):
            return None

        def _persist_incoming_records(self):
            return None

    fails: list[str] = []

    class Task:
        async def fail(self, error):
            fails.append(str(error))

        async def update_status(self, status):
            raise AssertionError("should not progress unauthorized recovered task")

        async def complete(self, artifacts=None):
            raise AssertionError("should not complete unauthorized recovered task")

    host = _Host()
    allowed = await host._authorize_record_for_execution(Task(), record, cfg)
    assert allowed is False
    assert record.status == "failed"
    assert record.metadata.get("authorization_rejected") is True
    assert fails, "task.fail must be called"
    assert (
        fails[0] == out_mod.stable_remote_error("not_in_allowlist")
        or fails[0] == "authorization_rejected"
    )
    assert "sk-supersecret123456" not in fails[0]
    assert "SECRET_TOKEN" not in fails[0]
    assert "do not leak" not in fails[0]
    # Local audit may retain reason; remote payload must stay stable.
    assert (
        "authorization" in (record.error or "").lower()
        or "allowlist" in (record.error or "").lower()
    )
