#!/usr/bin/env python3
"""Apply the P0 Keryx-first runtime alignment to the current branch.

This migration is intentionally idempotent and assertion-heavy. It exists only to
apply focused edits through GitHub Actions when a direct checkout is unavailable.
Remove it before the P0 pull request is marked ready.
"""

from __future__ import annotations

import re
from pathlib import Path


def replace_regex(path: str, pattern: str, replacement: str, *, marker: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if marker in text:
        return
    updated, count = re.subn(pattern, replacement.rstrip(), text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match for {pattern!r}, found {count}")
    file.write_text(updated, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if new in text and old not in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}: {old!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def align_config() -> None:
    replace_once(
        "hermes-agency/config.py",
        '    transport_backend: str = "agentanycast"',
        '    transport_backend: str = "keryx"',
    )
    replace_regex(
        "hermes-agency/config.py",
        r"def _transport_backend_config\(.*?(?=\n\ndef _clean_optional_str\()",
        '''def _transport_backend_config(config: dict[str, Any]) -> str:
    """Return the configured Agency transport backend with Keryx-first defaults."""

    raw_backend = (
        str(_cfg_get(config, "agency", "transport_backend", default="keryx") or "keryx")
        .strip()
        .lower()
    )
    aliases = {
        "agent-anycast": "agentanycast",
        "agent_anycast": "agentanycast",
        "anycast": "agentanycast",
    }
    backend = aliases.get(raw_backend, raw_backend)
    if backend not in {"agentanycast", "keryx"}:
        logger.warning(
            "Unsupported agency.transport_backend=%r; falling back to keryx", raw_backend
        )
        return "keryx"
    return backend
''',
        marker="Keryx-first defaults",
    )


def align_tools() -> None:
    replace_regex(
        "hermes-agency/tools.py",
        r"def get_transport_backend\(.*?(?=\n\ndef _configure_keryx_environment\()",
        '''def get_transport_backend() -> str:
    """Return configured Agency transport backend, defaulting to Keryx."""

    try:
        from .config import get_config

        backend = getattr(get_config(), "transport_backend", "keryx")
    except Exception:
        logger.debug("Failed to load Agency transport backend from config", exc_info=True)
        backend = "keryx"
    normalized = str(backend or "keryx").strip().lower()
    aliases = {
        "agent-anycast": "agentanycast",
        "agent_anycast": "agentanycast",
        "anycast": "agentanycast",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"agentanycast", "keryx"}:
        logger.warning(
            "Unsupported agency.transport_backend=%r; falling back to keryx", backend
        )
        return "keryx"
    return normalized
''',
        marker="defaulting to Keryx",
    )
    replace_regex(
        "hermes-agency/tools.py",
        r"def get_effective_transport_backend\(.*?(?=\n\ndef _compact_node\()",
        '''def get_effective_transport_backend() -> str:
    """Return the configured backend without silently changing transports."""

    backend = get_transport_backend()
    if backend == "keryx" and check_keryx_available():
        _configure_keryx_environment()
    elif backend == "keryx":
        logger.warning("Keryx transport requested but SDK unavailable")
    return backend


def check_agency_available() -> bool:
    """Return True when the explicitly selected Agency transport SDK is importable."""

    effective_backend = get_effective_transport_backend()
    if effective_backend == "keryx":
        return check_keryx_available()
    return importlib.util.find_spec("agentanycast") is not None
''',
        marker="without silently changing transports",
    )


def align_node_manager() -> None:
    replace_regex(
        "hermes-agency/node_manager.py",
        r"def _normalize_transport_backend\(.*?(?=\n\ndef _configure_keryx_environment\()",
        '''def _normalize_transport_backend(value: Any) -> str:
    """Normalize configured transport backend with a Keryx-first fallback."""

    backend = str(value or "keryx").strip().lower()
    backend = _TRANSPORT_BACKEND_ALIASES.get(backend, backend)
    if backend not in {"agentanycast", "keryx"}:
        logger.warning(
            "Unsupported agency.transport_backend=%r; falling back to keryx", value
        )
        return "keryx"
    return backend


def _transport_backend_for_config(cfg: AgencyConfig | None = None) -> str:
    """Return the configured transport backend for ``cfg`` or current config."""

    try:
        active_cfg = cfg or get_config()
        return _normalize_transport_backend(getattr(active_cfg, "transport_backend", "keryx"))
    except Exception:
        logger.debug("Failed to load Agency transport backend from config", exc_info=True)
        return "keryx"
''',
        marker="Keryx-first fallback",
    )
    replace_regex(
        "hermes-agency/node_manager.py",
        r"def _resolve_transport_node_class\(.*?(?=\n\ndef _resolve_daemon_bin\()",
        '''def _resolve_transport_node_class(cfg: AgencyConfig) -> tuple[type[Any], str]:
    """Return the node class for the explicitly selected transport backend."""

    backend = _transport_backend_for_config(cfg)
    if backend == "keryx":
        _configure_keryx_environment(cfg)
        try:
            from keryx.node import KeryxNode
        except Exception as exc:
            raise RuntimeError("Keryx transport requested but SDK unavailable") from exc
        return KeryxNode, "keryx"

    try:
        from agentanycast import Node
    except Exception as exc:
        raise RuntimeError("AgentAnycast transport requested but SDK unavailable") from exc
    return Node, "agentanycast"
''',
        marker="explicitly selected transport backend",
    )
    replace_regex(
        "hermes-agency/node_manager.py",
        r"def _resolve_daemon_bin\(.*?(?=\n\n@dataclass)",
        '''def _resolve_daemon_bin() -> Any | None:
    """Return an explicit legacy AgentAnycast daemon override when configured."""

    cfg = get_config()
    if cfg.daemon_bin and cfg.daemon_bin.exists():
        return cfg.daemon_bin
    return None
''',
        marker="explicit legacy AgentAnycast daemon override",
    )


def align_pool() -> None:
    replace_regex(
        "hermes-agency/pool/roster.py",
        r"def _transport_backend\(.*?(?=\n\ndef _keryx_config_kwargs\()",
        '''def _transport_backend() -> str:
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
''',
        marker="pool transport backend, defaulting to Keryx",
    )
    replace_regex(
        "hermes-agency/pool/manager.py",
        r"def _transport_backend\(.*?(?=\n\ndef send_task_via_transport\()",
        '''def _transport_backend() -> str:
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
''',
        marker="pool transport backend, defaulting to Keryx",
    )
    manager = Path("hermes-agency/pool/manager.py")
    text = manager.read_text(encoding="utf-8")
    text = text.replace(
        "AgentAnycast remains the default/fallback.  When ``transport_backend=keryx``\n"
        "    is configured, install Keryx's compatibility transport before touching the\n"
        "    singleton NodeManager so ``send_task_sync`` delivers via Keryx's daemon/relay\n"
        "    path instead of the legacy AgentAnycast daemon.",
        "Keryx is the default. AgentAnycast is used only when legacy mode is selected.\n"
        "    The singleton NodeManager owns the selected transport implementation.",
    )
    text = text.replace(
        "Older pool configs used provider names such as ``openai``/``xai`` that\n"
        "        are no longer valid on this VPS Hermes install. Kanban workers exit rc=0\n"
        "        before loading tools when the provider is invalid, which the dispatcher\n"
        "        records as a protocol violation. Keep the pool safe by defaulting every\n"
        "        agency worker to the known-good OpenAI Codex OAuth provider.",
        "Older pool configs may use deprecated provider aliases. Normalize them so\n"
        "        workers reach Hermes with a supported provider name instead of failing\n"
        "        before tool loading.",
    )
    manager.write_text(text, encoding="utf-8")


def add_regression_tests() -> None:
    test_file = Path("hermes-agency/tests/test_keryx_transport.py")
    text = test_file.read_text(encoding="utf-8")
    marker = "def test_transport_defaults_to_keryx_when_setting_is_absent"
    if marker in text:
        return
    addition = r'''

def test_transport_defaults_to_keryx_when_setting_is_absent(plugin_tools):
    plugin_tools["config"].load_config = lambda: {}

    assert plugin_tools["config"].get_config().transport_backend == "keryx"
    assert plugin_tools["tools"].get_transport_backend() == "keryx"


def test_invalid_transport_name_falls_back_to_keryx(plugin_tools):
    plugin_tools["config"].load_config = lambda: {
        "agency": {"transport_backend": "not-a-transport"}
    }

    assert plugin_tools["config"].get_config().transport_backend == "keryx"
    assert plugin_tools["tools"].get_transport_backend() == "keryx"


def test_keryx_unavailable_is_reported_without_transport_switch(plugin_tools, monkeypatch):
    monkeypatch.setattr(plugin_tools["tools"], "check_keryx_available", lambda: False)

    assert plugin_tools["tools"].get_effective_transport_backend() == "keryx"
    assert plugin_tools["tools"].check_agency_available() is False


def test_explicit_agentanycast_selects_legacy_node_class(node_manager_module, monkeypatch):
    class LegacyNode:
        pass

    legacy_module = types.ModuleType("agentanycast")
    legacy_module.__spec__ = importlib.machinery.ModuleSpec("agentanycast", loader=None)
    legacy_module.Node = LegacyNode
    monkeypatch.setitem(sys.modules, "agentanycast", legacy_module)

    node_cls, backend = node_manager_module._resolve_transport_node_class(
        types.SimpleNamespace(transport_backend="agentanycast")
    )

    assert node_cls is LegacyNode
    assert backend == "agentanycast"
'''
    test_file.write_text(text.rstrip() + "\n" + addition, encoding="utf-8")


def update_audit() -> None:
    path = Path("docs/audits/2026-07-10-p0-product-truth-keryx-alignment.md")
    text = path.read_text(encoding="utf-8")
    for item in (
        "Change the config default to `keryx`",
        "Change tools, node manager, pool, and roster fallbacks to `keryx`",
        "Restore a genuine explicit AgentAnycast node-class path or remove the runtime fallback claim",
        "Ensure configured and effective backend reporting is truthful",
        "Add transport-default and resolver regression tests",
    ):
        text = text.replace(f"- [ ] {item}", f"- [x] {item}")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    align_config()
    align_tools()
    align_node_manager()
    align_pool()
    add_regression_tests()
    update_audit()


if __name__ == "__main__":
    main()
