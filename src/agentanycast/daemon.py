"""Daemon lifecycle management — download, start, health check, stop."""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import grpc
import httpx

from agentanycast._generated.agentanycast.v1 import node_service_pb2, node_service_pb2_grpc
from agentanycast.exceptions import DaemonConnectionError, DaemonNotFoundError, DaemonStartError

logger = logging.getLogger(__name__)

# GitHub release URL pattern
_RELEASE_URL = (
    "https://github.com/agentanycast/agentanycast-node/releases/download/"
    "v{version}/agentanycastd-{os}-{arch}"
)

_PLATFORM_MAP = {
    ("Darwin", "arm64"): ("darwin", "arm64"),
    ("Darwin", "x86_64"): ("darwin", "amd64"),
    ("Linux", "x86_64"): ("linux", "amd64"),
    ("Linux", "aarch64"): ("linux", "arm64"),
    ("Windows", "AMD64"): ("windows", "amd64"),
}

_DEFAULT_BASE = Path.home() / ".agentanycast"

# Daemon binary version — independent of the SDK package version.
# Update this when a new agentanycast-node release is published.
_DEFAULT_DAEMON_VERSION = "0.7.2"

# Pinned SHA-256 digests for daemon release assets.
# Keys are (daemon_version, os_name, arch). Values must be updated in the SDK
# before enabling automatic download of a new daemon release.
_DAEMON_SHA256: dict[tuple[str, str, str], str] = {
    (
        "0.7.2",
        "darwin",
        "amd64",
    ): "6966dc390898b9bb4a2d760ab6c1e2c1c69ec923755ce75d313214812ff902ac",
    (
        "0.7.2",
        "darwin",
        "arm64",
    ): "b01f5ea2b302a762b42d78773859ba36b3e7a500ed08111442a3fe32f69cf9e0",
    ("0.7.2", "linux", "amd64"): "c6fb41049f2b25b9f109b07073fd90f87a44e0e85b932c5646c37f4b2cd2df82",
    ("0.7.2", "linux", "arm64"): "8ffc9122dd4d5ade67a08f4a47415c9c15c518407a7417548dec8d485d38ac00",
}


def _detect_platform() -> tuple[str, str]:
    """Detect OS and architecture, mapped to Go naming conventions."""
    system = platform.system()
    machine = platform.machine()
    key = (system, machine)
    if key not in _PLATFORM_MAP:
        raise DaemonNotFoundError(
            f"Unsupported platform: {system}/{machine}.\n"
            "\n"
            "Supported: macOS (arm64/x86_64), Linux (x86_64/aarch64), Windows (AMD64).\n"
            "\n"
            "To build from source:\n"
            "  git clone https://github.com/agentanycast/agentanycast-node\n"
            "  cd agentanycast-node && make build\n"
            "  export PATH=$PWD/bin:$PATH"
        )
    return _PLATFORM_MAP[key]


class DaemonManager:
    """Manages the agentanycastd daemon process lifecycle.

    Responsibilities:
    - Locate or download the daemon binary
    - Start the daemon subprocess
    - Health check via gRPC
    - Stop daemon on exit
    """

    def __init__(
        self,
        daemon_bin: str | Path | None = None,
        daemon_version: str | None = None,
        key_path: str | Path | None = None,
        grpc_listen: str | None = None,
        relay: str | None = None,
        log_level: str = "info",
        home: str | Path | None = None,
        transport: str | None = None,
        namespace: str | None = None,
        status_callback: Callable[[str], None] | None = None,
        verify_checksum: bool = True,
    ) -> None:
        # Resolve base directory — allows multiple instances with isolated state.
        self._uses_custom_home = home is not None
        self._base = Path(home) if home else _DEFAULT_BASE
        self._bin_dir = self._base / "bin"
        self._log_dir = self._base / "logs"

        self._daemon_bin = Path(daemon_bin) if daemon_bin else None
        self._daemon_version = daemon_version or _DEFAULT_DAEMON_VERSION
        self._key_path = str(key_path) if key_path else str(self._base / "key")
        self._grpc_listen = grpc_listen or f"unix://{self._base / 'daemon.sock'}"
        self._relay = relay
        self._log_level = log_level
        self._transport = transport
        self._namespace = namespace
        self._store_path = str(self._base / "data")
        self._config_path = self._base / "daemon.toml" if self._uses_custom_home else None
        self._identity_path = self._base / "daemon.identity.json"
        self._process: subprocess.Popen[bytes] | None = None
        self._managed = False  # True if we started the daemon
        self._status_callback = status_callback
        self._verify_checksum = verify_checksum

    def _emit(self, msg: str) -> None:
        """Send a status message to the callback (if set)."""
        if self._status_callback:
            self._status_callback(msg)

    @property
    def grpc_address(self) -> str:
        """The gRPC address the daemon is listening on."""
        return self._grpc_listen

    @property
    def sock_path(self) -> Path:
        """The UDS path (if using unix://)."""
        if self._grpc_listen.startswith("unix://"):
            return Path(self._grpc_listen[7:])
        return self._base / "daemon.sock"

    @staticmethod
    def _toml_quote(value: str) -> str:
        """Quote a string for the minimal daemon TOML config we generate."""
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _write_config_file(self) -> Path | None:
        """Write a per-home daemon config file when running with isolated state.

        The daemon binary's default config still points at ~/.agentanycast/data.
        SDK callers that pass ``home=...`` need a real TOML config file because
        daemon builds do not consistently honor AGENTANYCAST_STORE_PATH. Keep the
        file minimal so CLI flags continue to own key, gRPC, relay, and log
        settings.
        """
        if self._config_path is None:
            return None

        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        content = f"store_path = {self._toml_quote(self._store_path)}\n"
        self._config_path.write_text(content, encoding="utf-8")
        return self._config_path

    def _find_binary(self) -> Path:
        """Find the daemon binary, checking explicit path, PATH, and default location."""
        if self._daemon_bin and self._daemon_bin.exists():
            return self._daemon_bin

        # Check PATH
        found = shutil.which("agentanycastd")
        if found:
            return Path(found)

        # Check default install location
        default_bin = self._bin_dir / "agentanycastd"
        if default_bin.exists():
            return default_bin

        raise DaemonNotFoundError(
            "agentanycastd binary not found.\n"
            "\n"
            "The SDK downloads it automatically on first use. If that failed:\n"
            "  1. Check your internet connection\n"
            "  2. Manual download: https://github.com/agentanycast/agentanycast-node/releases\n"
            f"  3. Place the binary in {self._bin_dir}/ or on your PATH\n"
            "  4. Or build from source: https://github.com/agentanycast/agentanycast-node#building"
        )

    def _expected_binary_checksum(self, os_name: str, arch: str) -> str:
        """Return the SDK-pinned SHA-256 digest for a daemon release asset."""

        checksum = _DAEMON_SHA256.get((self._daemon_version, os_name, arch))
        if checksum:
            return checksum
        raise DaemonNotFoundError(
            "No pinned SHA-256 checksum is available for daemon "
            f"v{self._daemon_version} on {os_name}/{arch}; refusing to download an "
            "unverified executable. Install agentanycastd manually or use a newer SDK "
            "with a pinned checksum for this platform."
        )

    def _verify_binary_checksum(self, path: Path, expected_sha256: str) -> None:
        """Verify a downloaded daemon binary against its expected SHA-256 digest."""

        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = expected_sha256.strip().lower()
        if actual == expected:
            logger.info("Verified daemon binary SHA-256 checksum for %s", path)
            return

        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to delete daemon binary after checksum mismatch: %s", path)
        raise DaemonNotFoundError(
            "Daemon binary checksum mismatch; deleted the downloaded binary. "
            f"Expected {expected}, got {actual}."
        )

    async def download_binary(self) -> Path:
        """Download the daemon binary for the current platform."""
        os_name, arch = _detect_platform()
        suffix = ".exe" if os_name == "windows" else ""
        url = _RELEASE_URL.format(version=self._daemon_version, os=os_name, arch=arch)
        expected_sha256 = (
            self._expected_binary_checksum(os_name, arch) if self._verify_checksum else None
        )

        dest = self._bin_dir / f"agentanycastd{suffix}"
        self._bin_dir.mkdir(parents=True, exist_ok=True)

        self._emit(f"Downloading daemon (v{self._daemon_version})...")
        logger.info("Downloading daemon binary from %s", url)
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    last_pct = -1
                    with open(dest, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                pct = downloaded * 100 // total
                                # Emit at every 25% milestone.
                                milestone = pct // 25 * 25
                                if milestone > last_pct:
                                    last_pct = milestone
                                    if milestone < 100:
                                        self._emit(f"Downloading daemon... {milestone}%")
                if expected_sha256 is not None:
                    self._verify_binary_checksum(dest, expected_sha256)
                else:
                    logger.warning(
                        "Skipping daemon binary checksum verification for %s because "
                        "verify_checksum=False; only use this for trusted legacy releases.",
                        dest,
                    )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise DaemonNotFoundError(
                    f"Daemon binary not found at {url} (HTTP 404).\n"
                    f"Pre-built binaries may not be available for this platform/version.\n"
                    f"\n"
                    f"Build from source:\n"
                    f"  git clone https://github.com/agentanycast/agentanycast-node\n"
                    f"  cd agentanycast-node && make build\n"
                    f"  Node(card=card, daemon_path='./bin/agentanycastd')\n"
                    f"\n"
                    f"Or place a pre-built binary in: {self._bin_dir}"
                ) from e
            raise DaemonNotFoundError(
                f"Failed to download daemon binary from {url}: HTTP {e.response.status_code}"
            ) from e

        dest.chmod(0o755)
        self._emit("Daemon binary ready.")
        logger.info("Daemon binary downloaded to %s", dest)
        return dest

    async def ensure_binary(self) -> Path:
        """Ensure the daemon binary is available, downloading if needed."""
        try:
            return self._find_binary()
        except DaemonNotFoundError:
            return await self.download_binary()

    def _is_daemon_running(self) -> bool:
        """Check if a daemon is already running by testing the UDS."""
        sock = self.sock_path
        return sock.exists()

    def _requested_identity(self) -> dict[str, str]:
        """Return daemon identity fields explicitly requested by this caller."""
        identity = {}
        if self._transport:
            identity["transport"] = self._transport
        if self._namespace:
            identity["namespace"] = self._namespace
        return identity

    def _write_identity_file(self) -> None:
        """Persist the daemon isolation identity used for safe socket reuse."""
        identity = self._requested_identity()
        if not identity:
            return
        self._identity_path.parent.mkdir(parents=True, exist_ok=True)
        self._identity_path.write_text(
            json.dumps(identity, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _validate_existing_daemon_identity(self) -> None:
        """Refuse to reuse a daemon with unknown or mismatched isolation settings."""
        requested = self._requested_identity()
        if not requested:
            return

        try:
            existing = json.loads(self._identity_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            requested_desc = ", ".join(f"{k}={v!r}" for k, v in sorted(requested.items()))
            raise DaemonConnectionError(
                "Existing daemon identity is unknown; refusing to reuse daemon at "
                f"{self._grpc_listen} for requested {requested_desc}. "
                "Stop the existing daemon or use a separate home directory for this "
                "transport/namespace."
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise DaemonConnectionError(
                "Existing daemon identity could not be read; refusing to reuse daemon at "
                f"{self._grpc_listen}. Stop the existing daemon or use a separate home directory."
            ) from exc

        mismatches = [
            f"{key}: requested {value!r}, existing {existing.get(key)!r}"
            for key, value in sorted(requested.items())
            if existing.get(key) != value
        ]
        if mismatches:
            raise DaemonConnectionError(
                "Existing daemon identity does not match requested isolation settings; "
                f"refusing to reuse daemon at {self._grpc_listen}. "
                + "; ".join(mismatches)
                + ". Stop the existing daemon or use a separate home directory."
            )

    async def _reuse_or_cleanup_existing_socket(self) -> bool:
        """Return True for a healthy existing daemon; clean stale UDS files.

        A leftover Unix socket from a crashed daemon is not proof that a daemon is
        still running. Confirm the daemon answers gRPC before reusing it; when it
        does not, remove the stale socket so a fresh daemon can bind normally.
        """

        if not self._grpc_listen.startswith("unix://"):
            return False

        sock = self.sock_path
        if not sock.exists():
            return False

        try:
            if await self._grpc_health_check(timeout=2.0, raise_on_timeout=True):
                self._validate_existing_daemon_identity()
                return True
        except TimeoutError as exc:
            raise DaemonConnectionError(
                f"Health check timed out for existing daemon socket at {sock}.\n"
                "\n"
                "A daemon may be wedged or unreachable. Remediation:\n"
                "  - Check daemon logs for errors\n"
                "  - Kill stale daemon: pkill agentanycastd\n"
                f"  - Remove stale socket after confirming no daemon is healthy: rm -f {sock}"
            ) from exc

        warning = f"Removed stale daemon socket at {sock}; daemon did not answer health check."
        try:
            sock.unlink()
        except PermissionError as exc:
            raise DaemonStartError(
                f"Found stale daemon socket at {sock}, but could not remove it due to "
                "permission error. Remove the stale socket manually or fix ownership, then "
                f"retry. Suggested command: rm -f {sock}"
            ) from exc
        except OSError as exc:
            raise DaemonStartError(
                f"Found stale daemon socket at {sock}, but could not remove it: {exc}. "
                f"Remove the stale socket manually, then retry: rm -f {sock}"
            ) from exc

        logger.warning(warning)
        self._emit(f"Warning: {warning}")
        return False

    async def start(self) -> None:
        """Start the daemon process if not already running."""
        if await self._reuse_or_cleanup_existing_socket():
            logger.info("Daemon already running at %s", self._grpc_listen)
            self._emit("Daemon already running.")
            return

        binary = await self.ensure_binary()
        self._emit("Starting daemon...")

        # Prepare log directory
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self._log_dir / "daemon.log"

        # Build command
        config_path = self._write_config_file()
        cmd = [
            str(binary),
        ]
        if config_path is not None:
            cmd.append(f"--config={config_path}")
        cmd.extend(
            [
                f"--key={self._key_path}",
                f"--grpc-listen={self._grpc_listen}",
                f"--log-level={self._log_level}",
            ]
        )

        if self._relay:
            cmd.append(f"--bootstrap-peers={self._relay}")

        if self._transport:
            cmd.append(f"--transport={self._transport}")

        if self._namespace:
            cmd.append(f"--namespace={self._namespace}")

        logger.info("Starting daemon: %s", " ".join(cmd))

        env = {**os.environ, "AGENTANYCAST_STORE_PATH": self._store_path}

        with open(log_file, "a") as lf:
            self._process = subprocess.Popen(
                cmd,
                stdout=lf,
                stderr=lf,
                env=env,
                start_new_session=True,
            )

        self._managed = True

        # Register cleanup
        atexit.register(self.stop_sync)

        # Wait for daemon to be ready (health check)
        await self._wait_ready(timeout=10.0)
        self._write_identity_file()
        self._emit("Daemon ready.")

    def _read_recent_logs(self, max_lines: int = 20) -> str:
        """Read the last N lines of daemon.log for error diagnostics."""
        log_file = self._log_dir / "daemon.log"
        if not log_file.exists():
            return ""
        try:
            lines = log_file.read_text().splitlines()
            tail = lines[-max_lines:]
            return "\n".join(tail)
        except OSError:
            return ""

    async def _wait_ready(self, timeout: float) -> None:
        """Poll until the daemon's UDS appears and responds to gRPC calls."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self._process and self._process.poll() is not None:
                logs = self._read_recent_logs()
                msg = (
                    f"Daemon exited with code {self._process.returncode}.\n"
                    f"\n"
                    f"Common causes:\n"
                    f"  - Port conflict: another daemon may be running"
                    f" (check: ps aux | grep agentanycastd)\n"
                    f"  - Corrupted binary: delete {self._bin_dir}/agentanycastd"
                    f" and restart\n"
                    f"\n"
                    f"Logs: {self._log_dir / 'daemon.log'}"
                )
                if logs:
                    msg += f"\n\nRecent logs:\n{logs}"
                raise DaemonStartError(msg)

            if self.sock_path.exists():
                # Socket exists — verify gRPC server is actually ready.
                if await self._grpc_health_check():
                    logger.info("Daemon ready at %s", self._grpc_listen)
                    return

            await asyncio.sleep(0.1)

        logs = self._read_recent_logs()
        msg = (
            f"Daemon did not become ready within {timeout}s.\n"
            f"\n"
            f"Troubleshooting:\n"
            f"  - Check logs: cat {self._log_dir / 'daemon.log'}\n"
            f"  - Kill stale daemon: pkill agentanycastd\n"
            f"  - Remove stale socket: rm -f {self.sock_path}\n"
            f"  - Try verbose mode: agentanycast --verbose demo"
        )
        if logs:
            msg += f"\n\nRecent logs:\n{logs}"
        raise DaemonConnectionError(msg)

    async def _grpc_health_check(
        self, *, timeout: float = 2.0, raise_on_timeout: bool = False
    ) -> bool:
        """Attempt a single gRPC GetNodeInfo call to verify daemon readiness."""
        try:
            channel = grpc.aio.insecure_channel(self._grpc_listen)
            try:
                stub = node_service_pb2_grpc.NodeServiceStub(channel)
                await stub.GetNodeInfo(
                    node_service_pb2.GetNodeInfoRequest(),
                    timeout=timeout,
                )
                return True
            except grpc.aio.AioRpcError as exc:
                if raise_on_timeout and exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                    raise TimeoutError("daemon health check timed out") from exc
                return False
            finally:
                await channel.close()
        except TimeoutError:
            if raise_on_timeout:
                raise
            return False
        except Exception:
            return False

    def stop_sync(self) -> None:
        """Synchronously stop the daemon (for atexit)."""
        if self._process and self._managed:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            finally:
                self._process = None
                # Clean up stale socket
                if self.sock_path.exists():
                    self.sock_path.unlink(missing_ok=True)

    async def stop(self) -> None:
        """Stop the daemon process."""
        self.stop_sync()
