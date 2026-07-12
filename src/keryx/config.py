"""Configuration loading for the Keryx Python SDK."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from keryx.client import default_daemon_endpoint

DEFAULT_DAEMON_ENDPOINT = "unix://~/.hermes/keryx/run/keryx-daemon.sock"


@dataclass(frozen=True)
class KeryxConfig:
    """Runtime configuration for :class:`keryx.node.KeryxNode`.

    Environment variables intentionally accept both the Hermes-prefixed names used
    by the daemon/CLI and shorter SDK aliases so Agency profiles can be configured
    without changing existing Keryx deployments.
    """

    daemon_endpoint: str = field(default_factory=default_daemon_endpoint)
    registry_endpoint: str | None = None
    relay_endpoint: str | None = None
    worker_id: str | None = None
    default_lease_duration_ms: int = 0
    request_timeout_ms: int | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "KeryxConfig":
        """Build a config from environment variables only."""

        source = env if env is not None else os.environ
        return cls(
            daemon_endpoint=_first_env(
                source,
                "HERMES_KERYX_DAEMON_ENDPOINT",
                "KERYX_DAEMON_ENDPOINT",
                default=default_daemon_endpoint(),
            ) or default_daemon_endpoint(),
            registry_endpoint=_first_env(
                source,
                "HERMES_KERYX_REGISTRY_ENDPOINT",
                "KERYX_REGISTRY_ENDPOINT",
            ),
            relay_endpoint=_first_env(
                source,
                "HERMES_KERYX_RELAY_ENDPOINT",
                "KERYX_RELAY_ENDPOINT",
            ),
            worker_id=_first_env(
                source,
                "HERMES_KERYX_WORKER_ID",
                "KERYX_WORKER_ID",
            ),
            default_lease_duration_ms=_first_int_env(
                source,
                "HERMES_KERYX_DEFAULT_LEASE_DURATION_MS",
                "KERYX_DEFAULT_LEASE_DURATION_MS",
                default=0,
            ),
            request_timeout_ms=_first_optional_int_env(
                source,
                "HERMES_KERYX_REQUEST_TIMEOUT_MS",
                "KERYX_REQUEST_TIMEOUT_MS",
            ),
        )

    @classmethod
    def from_toml(cls, path: str | Path) -> "KeryxConfig":
        """Load config values from a TOML file.

        Supported keys may be top-level (``daemon_endpoint``) or grouped as
        ``[daemon] endpoint = ...``, ``[registry] endpoint = ...``,
        ``[relay] endpoint = ...``, and ``[worker] id = ...``.
        """

        with Path(path).expanduser().open("rb") as handle:
            data = tomllib.load(handle)

        daemon = _table(data, "daemon")
        registry = _table(data, "registry")
        relay = _table(data, "relay")
        worker = _table(data, "worker")
        defaults = _table(data, "defaults")

        return cls(
            daemon_endpoint=str(
                data.get("daemon_endpoint")
                or daemon.get("endpoint")
                or default_daemon_endpoint()
            ),
            registry_endpoint=_optional_str(
                data.get("registry_endpoint") or registry.get("endpoint")
            ),
            relay_endpoint=_optional_str(data.get("relay_endpoint") or relay.get("endpoint")),
            worker_id=_optional_str(data.get("worker_id") or worker.get("id")),
            default_lease_duration_ms=int(
                data.get("default_lease_duration_ms")
                or defaults.get("lease_duration_ms")
                or worker.get("default_lease_duration_ms")
                or 0
            ),
            request_timeout_ms=_optional_int(
                data.get("request_timeout_ms") or defaults.get("request_timeout_ms")
            ),
        )

    def with_env_overrides(self, env: Mapping[str, str] | None = None) -> "KeryxConfig":
        """Return a copy with any configured environment variables applied."""

        source = env if env is not None else os.environ
        changes: dict[str, Any] = {}
        if daemon := _first_env(source, "HERMES_KERYX_DAEMON_ENDPOINT", "KERYX_DAEMON_ENDPOINT"):
            changes["daemon_endpoint"] = daemon
        if registry := _first_env(source, "HERMES_KERYX_REGISTRY_ENDPOINT", "KERYX_REGISTRY_ENDPOINT"):
            changes["registry_endpoint"] = registry
        if relay := _first_env(source, "HERMES_KERYX_RELAY_ENDPOINT", "KERYX_RELAY_ENDPOINT"):
            changes["relay_endpoint"] = relay
        if worker := _first_env(source, "HERMES_KERYX_WORKER_ID", "KERYX_WORKER_ID"):
            changes["worker_id"] = worker
        lease = _first_optional_int_env(
            source,
            "HERMES_KERYX_DEFAULT_LEASE_DURATION_MS",
            "KERYX_DEFAULT_LEASE_DURATION_MS",
        )
        if lease is not None:
            changes["default_lease_duration_ms"] = lease
        timeout = _first_optional_int_env(
            source,
            "HERMES_KERYX_REQUEST_TIMEOUT_MS",
            "KERYX_REQUEST_TIMEOUT_MS",
        )
        if timeout is not None:
            changes["request_timeout_ms"] = timeout
        return replace(self, **changes) if changes else self

    @property
    def grpc_daemon_target(self) -> str:
        """Endpoint string normalized for ``grpc.aio.insecure_channel``."""

        return grpc_target(self.daemon_endpoint)


def load_config(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> KeryxConfig:
    """Load Keryx SDK config from TOML and/or environment.

    If ``path`` is omitted, ``HERMES_KERYX_CONFIG``/``KERYX_CONFIG`` is honored
    when present. Environment variables override TOML values.
    """

    source = env if env is not None else os.environ
    config_path = path or _first_env(source, "HERMES_KERYX_CONFIG", "KERYX_CONFIG")
    config = KeryxConfig.from_toml(config_path) if config_path else KeryxConfig()
    return config.with_env_overrides(source)


def grpc_target(endpoint: str) -> str:
    """Convert Keryx endpoint notation into a gRPC Python channel target."""

    endpoint = endpoint.strip()
    if endpoint.startswith("unix://"):
        return endpoint
    for prefix in ("tcp://", "http://", "https://"):
        if endpoint.startswith(prefix):
            return endpoint.removeprefix(prefix)
    return endpoint


def _first_env(source: Mapping[str, str], *names: str, default: str | None = None) -> str | None:
    for name in names:
        value = source.get(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _first_int_env(source: Mapping[str, str], *names: str, default: int) -> int:
    value = _first_env(source, *names)
    return int(value) if value is not None else default


def _first_optional_int_env(source: Mapping[str, str], *names: str) -> int | None:
    value = _first_env(source, *names)
    return int(value) if value is not None else None


def _table(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name)
    return value if isinstance(value, Mapping) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
