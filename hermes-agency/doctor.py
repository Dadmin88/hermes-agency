"""Self-diagnostic checks for the Hermes Agency plugin."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import yaml
except Exception:  # pragma: no cover - Hermes normally depends on PyYAML
    yaml = None  # type: ignore[assignment]

from hermes_constants import get_hermes_home

from .card_builder import build_card, card_to_dict
from .config import AgencyConfig, get_config
from .node_manager import _registry_addresses, manager
from .tools import check_agency_available
from .trust import relay_control_url, store_for_config

PASS = "pass"
WARN = "warn"
FAIL = "fail"
NA = "na"


@dataclass(frozen=True)
class DoctorCheck:
    """One Hermes Agency diagnostic result."""

    id: str
    label: str
    status: str
    message: str
    remediation: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "message": self.message,
        }
        if self.remediation:
            payload["remediation"] = self.remediation
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass(frozen=True)
class DoctorReport:
    """Complete Hermes Agency doctor report."""

    checks: list[DoctorCheck]

    @property
    def exit_code(self) -> int:
        if any(check.status == FAIL for check in self.checks):
            return 2
        if any(check.status == WARN for check in self.checks):
            return 1
        return 0

    @property
    def summary(self) -> dict[str, int]:
        return {
            status: sum(1 for check in self.checks if check.status == status)
            for status in (PASS, WARN, FAIL, NA)
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.exit_code == 0,
            "exit_code": self.exit_code,
            "summary": self.summary,
            "checks": [check.as_dict() for check in self.checks],
        }


def _check(
    check_id: str,
    label: str,
    status: str,
    message: str,
    remediation: str | None = None,
    **details: Any,
) -> DoctorCheck:
    return DoctorCheck(
        id=check_id,
        label=label,
        status=status,
        message=message,
        remediation=remediation,
        details={key: value for key, value in details.items() if value is not None},
    )


def _config_file_state() -> tuple[str, str, str | None]:
    try:
        from hermes_cli.config import get_config_path
    except Exception as exc:
        return WARN, f"Could not resolve Hermes config path: {type(exc).__name__}: {exc}", None

    path = Path(get_config_path()).expanduser()
    if not path.exists():
        return WARN, f"Hermes config file does not exist at {path}", str(path)
    if yaml is None:
        return WARN, "PyYAML is unavailable; config syntax could not be checked", str(path)
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return FAIL, f"Hermes config file is not valid YAML: {type(exc).__name__}: {exc}", str(path)
    if not isinstance(loaded, dict):
        return FAIL, "Hermes config file must contain a YAML mapping", str(path)
    if "agency" not in loaded:
        return (
            WARN,
            "Hermes config is valid but has no agency section; defaults are in use",
            str(path),
        )
    return PASS, "Hermes config exists and agency config is valid YAML", str(path)


def _is_local_or_https(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme in {"https", "unix"}:
        return True
    host = (parsed.hostname or "").strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    return parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}


def _daemon_candidates(cfg: AgencyConfig) -> list[Path]:
    candidates: list[Path] = []
    if cfg.daemon_bin:
        candidates.append(Path(cfg.daemon_bin).expanduser())
    found = shutil.which("agentanycastd")
    if found:
        candidates.append(Path(found))
    if cfg.home:
        candidates.append(Path(cfg.home).expanduser() / "bin" / "agentanycastd")
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _daemon_binary_check(cfg: AgencyConfig) -> DoctorCheck:
    candidates = _daemon_candidates(cfg)
    for candidate in candidates:
        if candidate.exists():
            if os.access(candidate, os.X_OK):
                return _check(
                    "daemon_binary",
                    "Daemon binary",
                    PASS,
                    f"agentanycastd is present and executable at {candidate}",
                    path=str(candidate),
                )
            return _check(
                "daemon_binary",
                "Daemon binary",
                FAIL,
                f"agentanycastd exists but is not executable at {candidate}",
                "Set agency.daemon_bin or install the daemon",
                path=str(candidate),
            )
    return _check(
        "daemon_binary",
        "Daemon binary",
        FAIL,
        "agentanycastd binary was not found in agency.daemon_bin, PATH, or agency home",
        "Set agency.daemon_bin or install the daemon",
        candidates=[str(item) for item in candidates],
    )


def _daemon_provenance_check(cfg: AgencyConfig) -> DoctorCheck:
    if cfg.daemon_bin:
        if Path(cfg.daemon_bin).expanduser().exists():
            return _check(
                "daemon_provenance",
                "Daemon checksum/provenance",
                PASS,
                "Explicit daemon binary is configured; provenance is operator-managed",
                path=str(cfg.daemon_bin),
            )
        return _check(
            "daemon_provenance",
            "Daemon checksum/provenance",
            WARN,
            "Explicit daemon binary is configured but missing, so provenance cannot be checked",
            "Set agency.daemon_bin or install the daemon",
            path=str(cfg.daemon_bin),
        )
    return _check(
        "daemon_provenance",
        "Daemon checksum/provenance",
        PASS,
        "SDK-managed daemon downloads verify release SHA-256 checksums by default",
    )


def _daemon_socket_check(cfg: AgencyConfig) -> DoctorCheck:
    try:
        node = manager.compact_info()
    except Exception as exc:
        return _check(
            "daemon_socket",
            "Daemon socket health",
            WARN,
            f"Daemon compact health check is not available: {type(exc).__name__}: {exc}",
            "Run /agency start or hermes agency start",
        )
    if bool(node.get("started")) or bool(node.get("node_started")):
        return _check(
            "daemon_socket", "Daemon socket health", PASS, "Daemon/node health is responsive"
        )
    remediation = None if cfg.auto_start else "Run /agency start or hermes agency start"
    return _check(
        "daemon_socket",
        "Daemon socket health",
        WARN,
        "Hermes Agency node is not currently running",
        remediation,
        node=node,
    )


def _relay_config_check(cfg: AgencyConfig) -> DoctorCheck:
    relay = str(cfg.relay or "").strip()
    if not relay:
        return _check(
            "relay_config",
            "Relay config",
            WARN,
            "No relay is configured; discovery may be limited to local/LAN transports",
        )
    control_url = relay if relay.startswith(("http://", "https://")) else None
    if cfg.relay_security.auto_allow_team and cfg.relay_security.token:
        control_url = relay_control_url(cfg) or control_url
    if control_url and not _is_local_or_https(control_url):
        return _check(
            "relay_config",
            "Relay config",
            FAIL,
            f"Relay/control URL is not safe for token-bearing control traffic: {control_url}",
            "Use HTTPS or localhost for relay control",
            relay=relay,
            control_url=control_url,
        )
    return _check(
        "relay_config", "Relay config", PASS, "Relay is configured with a safe address", relay=relay
    )


def _registry_config_check() -> DoctorCheck:
    addrs = _registry_addresses()
    if not addrs:
        return _check(
            "registry_config",
            "Registry config",
            WARN,
            "No AGENTANYCAST_REGISTRY_ADDRS registry address is configured; anycast discovery may be empty",
        )
    return _check(
        "registry_config",
        "Registry config",
        PASS,
        "Registry address is configured; TLS mode is deployment-controlled",
        addresses=addrs,
    )


def _trust_store_check(cfg: AgencyConfig) -> DoctorCheck:
    store = store_for_config(cfg)
    peers = store.list_peers()
    if not store.path.exists():
        return _check(
            "trust_store",
            "Trust store",
            WARN,
            f"Trust store does not exist at {store.path}",
            "Add trusted peers or enable TOFU",
            path=str(store.path),
            tofu=cfg.trust.tofu,
        )
    if not peers:
        return _check(
            "trust_store",
            "Trust store",
            WARN,
            "Trust store exists but has no peers",
            "Add trusted peers or enable TOFU",
            path=str(store.path),
            tofu=cfg.trust.tofu,
        )
    return _check(
        "trust_store",
        "Trust store",
        PASS,
        f"Trust store has {len(peers)} peer(s)",
        path=str(store.path),
        tofu=cfg.trust.tofu,
    )


def _allowlist_check(cfg: AgencyConfig) -> DoctorCheck:
    security = cfg.relay_security
    if security.allow_all:
        return _check(
            "allowlist_mode",
            "Allowlist mode",
            WARN,
            "Relay allowlist mode is allow-all",
            "Use explicit agency.relay.allowlist entries outside trusted development networks",
            mode="allow_all",
        )
    if security.allowlist:
        return _check(
            "allowlist_mode",
            "Allowlist mode",
            PASS,
            f"Relay allowlist has {len(security.allowlist)} explicit peer(s)",
            mode="explicit",
        )
    return _check(
        "allowlist_mode",
        "Allowlist mode",
        FAIL,
        "Relay allowlist mode is deny because allowlist is empty and allow_all is false",
        "Add trusted peers or enable TOFU",
        mode="deny",
    )


def _remote_task_policy_check(cfg: AgencyConfig) -> DoctorCheck:
    details = cfg.incoming.as_dict()
    if not cfg.allow_remote_tasks:
        return _check(
            "remote_task_policy",
            "Remote task policy",
            WARN,
            "Remote task processing is disabled; incoming requests will use the safe fallback",
            "Set agency.incoming.allow_remote_tasks: true",
            allow_remote_tasks=False,
            incoming=details,
        )
    if cfg.incoming.mode == "subprocess" and not cfg.incoming.allow_subprocess:
        return _check(
            "remote_task_policy",
            "Remote task policy",
            FAIL,
            "Incoming mode is subprocess but subprocess execution is not explicitly allowed",
            "Set agency.incoming.allow_subprocess: true only for trusted peers",
            incoming=details,
        )
    return _check(
        "remote_task_policy",
        "Remote task policy",
        PASS,
        f"Remote tasks are enabled in {cfg.incoming.mode} mode",
        incoming=details,
    )


def _agent_card_check() -> DoctorCheck:
    try:
        card = card_to_dict(build_card())
    except Exception as exc:
        return _check(
            "agent_card",
            "AgentCard preview",
            FAIL,
            f"Could not generate AgentCard from SOUL.md and skills: {type(exc).__name__}: {exc}",
        )
    return _check(
        "agent_card",
        "AgentCard preview",
        PASS,
        f"Generated AgentCard for {card.get('name') or 'unnamed profile'}",
        skill_count=len(card.get("skills") or []),
    )


def _kanban_available() -> bool:
    try:
        importlib.import_module("hermes_cli.kanban_db")
    except Exception:
        return False
    return True


def _kanban_check(cfg: AgencyConfig) -> DoctorCheck:
    if not cfg.team.kanban_integration:
        return _check(
            "kanban_availability",
            "Kanban availability",
            WARN,
            "Kanban integration is disabled in agency.team.kanban_integration",
        )
    if _kanban_available():
        return _check(
            "kanban_availability", "Kanban availability", PASS, "Hermes Kanban module is importable"
        )
    return _check(
        "kanban_availability",
        "Kanban availability",
        WARN,
        "Hermes Kanban module is not importable in this runtime",
    )


def _nested_get(config: dict[str, Any], *path: str, default: Any = None) -> Any:
    value: Any = config
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _mcp_http_enabled_details() -> dict[str, Any] | None:
    env_transport = (
        (
            os.getenv("AGENTANYCAST_MCP_TRANSPORT")
            or os.getenv("HERMES_MCP_TRANSPORT")
            or os.getenv("MCP_TRANSPORT")
            or ""
        )
        .strip()
        .lower()
    )
    if env_transport == "http":
        return {"source": "env", "transport": "http"}
    try:
        from hermes_cli.config import load_config

        raw_config = load_config()
    except Exception:
        raw_config = {}
    candidates = [
        ("mcp.transport", _nested_get(raw_config, "mcp", "transport")),
        ("mcp.server.transport", _nested_get(raw_config, "mcp", "server", "transport")),
        ("mcp.http.enabled", _nested_get(raw_config, "mcp", "http", "enabled")),
        ("agency.mcp.transport", _nested_get(raw_config, "agency", "mcp", "transport")),
    ]
    for key, value in candidates:
        if str(value or "").strip().lower() == "http" or value is True:
            return {"source": "config", "key": key, "value": value}
    return None


def _mcp_http_exposure_check() -> DoctorCheck:
    details = _mcp_http_enabled_details()
    if not details:
        return _check(
            "mcp_http_exposure",
            "MCP HTTP exposure",
            PASS,
            "MCP HTTP mode was not detected in environment or config",
        )
    return _check(
        "mcp_http_exposure",
        "MCP HTTP exposure",
        WARN,
        "MCP HTTP mode is enabled; this is an unauthenticated tool server by default",
        "MCP HTTP mode is an unauthenticated tool server. Restrict network access or add authentication.",
        **details,
    )


def _editable_install_state() -> tuple[str, str]:
    root = Path(__file__).resolve().parents[1]
    if (root / ".git").exists() and (root / "pyproject.toml").exists():
        return PASS, "Running from a source checkout suitable for development/CI"
    direct_url = root.parent / "direct_url.json"
    if direct_url.exists():
        try:
            data = json.loads(direct_url.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if isinstance(data, dict) and data.get("dir_info", {}).get("editable"):
            return PASS, "Editable install metadata detected"
    return WARN, "Editable/source install state could not be confirmed"


def _model_sets_check() -> DoctorCheck:
    try:
        from .model_sets import active_model_set_name, load_model_set, validate_model_set
        from .profile_config_writer import plan_model_set
    except Exception as exc:
        return _check(
            "agency_model_sets",
            "Agency model sets",
            WARN,
            f"Model-set imports failed: {type(exc).__name__}: {exc}",
        )
    try:
        from hermes_cli.config import load_config

        raw_config = load_config()
    except Exception:
        raw_config = {}
    try:
        model_set = load_model_set(
            active_model_set_name(config=raw_config if isinstance(raw_config, dict) else {})
        )
        validation = validate_model_set(model_set)
        plan = plan_model_set(model_set)
    except Exception as exc:
        return _check(
            "agency_model_sets",
            "Agency model sets",
            WARN,
            f"Model-set diagnostics failed: {type(exc).__name__}: {exc}",
        )
    drift = [item.as_dict() for item in plan if item.status == "drift"]
    missing = [item.as_dict() for item in plan if item.status == "missing"]
    unchanged = sum(1 for item in plan if item.status == "unchanged")
    status = PASS if validation.ok and not drift and not missing else WARN
    if not validation.ok:
        status = FAIL
    return _check(
        "agency_model_sets",
        "Agency model sets",
        status,
        (
            f"Active model set: {model_set.name}; profiles checked: {len(plan)}; "
            f"missing: {len(missing)}; drift: {len(drift)}; unchanged: {unchanged}"
        ),
        active_set=model_set.name,
        preset_source=str(model_set.source_path),
        warnings=validation.warnings,
        errors=validation.errors,
        profiles_checked=len(plan),
        missing=missing,
        drift=drift,
        unchanged=unchanged,
    )


def run_doctor() -> DoctorReport:
    """Run Hermes Agency self-diagnostics without starting new daemon processes."""

    checks: list[DoctorCheck] = []
    cfg = get_config()

    checks.append(
        _check(
            "plugin_load",
            "Plugin load",
            PASS,
            "Hermes Agency plugin modules imported successfully",
        )
    )

    profile_home = Path(get_hermes_home()).expanduser()
    checks.append(
        _check(
            "profile_path",
            "Hermes profile path",
            PASS if profile_home.exists() and profile_home.is_dir() else FAIL,
            f"Hermes profile directory: {profile_home}",
            None
            if profile_home.exists() and profile_home.is_dir()
            else "Create or select a valid Hermes profile",
            path=str(profile_home),
        )
    )

    config_status, config_message, config_path = _config_file_state()
    checks.append(
        _check(
            "config_file",
            "Config file",
            config_status,
            config_message,
            None if config_status == PASS else "Run hermes config edit and fix the agency section",
            path=config_path,
        )
    )

    sdk_available = check_agency_available()
    checks.append(
        _check(
            "sdk_dependency",
            "SDK/transport dependency",
            PASS if sdk_available else FAIL,
            "agentanycast SDK is importable"
            if sdk_available
            else "agentanycast SDK is not importable",
            None
            if sdk_available
            else "Install the agentanycast package in the active Hermes runtime",
        )
    )

    checks.append(_daemon_binary_check(cfg))
    checks.append(_daemon_provenance_check(cfg))
    checks.append(_daemon_socket_check(cfg))
    checks.append(_relay_config_check(cfg))
    checks.append(_registry_config_check())
    checks.append(_trust_store_check(cfg))
    checks.append(_allowlist_check(cfg))
    checks.append(_remote_task_policy_check(cfg))
    checks.append(_mcp_http_exposure_check())
    checks.append(_agent_card_check())
    checks.append(_kanban_check(cfg))
    checks.append(_model_sets_check())

    editable_status, editable_message = _editable_install_state()
    checks.append(
        _check(
            "dev_install_state",
            "CI/dev install state",
            editable_status,
            editable_message,
            None
            if editable_status == PASS
            else "Use an editable/source checkout for plugin development",
            python=sys.executable,
        )
    )

    return DoctorReport(checks=checks)


def render_doctor_report(report: DoctorReport, *, json_output: bool = False) -> str:
    """Render a doctor report for humans or machines."""

    if json_output:
        return json.dumps(report.as_dict(), indent=2, sort_keys=True)

    symbols = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL", NA: "N/A"}
    lines = ["Hermes Agency doctor", ""]
    for check in report.checks:
        lines.append(
            f"[{symbols.get(check.status, check.status.upper())}] {check.label}: {check.message}"
        )
        if check.remediation:
            lines.append(f"      Fix: {check.remediation}")
    lines.extend(
        [
            "",
            "Summary: " + ", ".join(f"{key}={value}" for key, value in report.summary.items()),
            f"Exit code: {report.exit_code}",
        ]
    )
    return "\n".join(lines)
