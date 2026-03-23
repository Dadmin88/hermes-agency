"""Daemon lifecycle management — download, start, health check, stop."""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import platform
import shutil
import subprocess
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
_DEFAULT_DAEMON_VERSION = "0.7.0"


def _detect_platform() -> tuple[str, str]:
    """Detect OS and architecture, mapped to Go naming conventions."""
    system = platform.system()
    machine = platform.machine()
    key = (system, machine)
    if key not in _PLATFORM_MAP:
        raise DaemonNotFoundError(
            f"Unsupported platform: {system}/{machine}. Supported: {list(_PLATFORM_MAP.keys())}"
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
    ) -> None:
        # Resolve base directory — allows multiple instances with isolated state.
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
        self._process: subprocess.Popen[bytes] | None = None
        self._managed = False  # True if we started the daemon

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
            "agentanycastd binary not found. Install it or set daemon_bin parameter."
        )

    async def download_binary(self) -> Path:
        """Download the daemon binary for the current platform."""
        os_name, arch = _detect_platform()
        suffix = ".exe" if os_name == "windows" else ""
        url = _RELEASE_URL.format(version=self._daemon_version, os=os_name, arch=arch)

        dest = self._bin_dir / f"agentanycastd{suffix}"
        self._bin_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Downloading daemon binary from %s", url)
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise DaemonNotFoundError(
                    f"Daemon binary not found at {url} (HTTP 404). "
                    f"Pre-built binaries may not be available yet. "
                    f"You can either:\n"
                    f"  1. Build the daemon locally from "
                    f"https://github.com/agentanycast/agentanycast-node "
                    f"and pass daemon_path= to Node()\n"
                    f"  2. Place the built 'agentanycastd' binary on "
                    f"your PATH or in {self._bin_dir}"
                ) from e
            raise DaemonNotFoundError(
                f"Failed to download daemon binary from {url}: HTTP {e.response.status_code}"
            ) from e

        dest.chmod(0o755)
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

    async def start(self) -> None:
        """Start the daemon process if not already running."""
        if self._is_daemon_running():
            logger.info("Daemon already running at %s", self._grpc_listen)
            return

        binary = await self.ensure_binary()

        # Prepare log directory
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self._log_dir / "daemon.log"

        # Build command
        cmd = [
            str(binary),
            f"--key={self._key_path}",
            f"--grpc-listen={self._grpc_listen}",
            f"--log-level={self._log_level}",
        ]

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
                    f"Daemon exited with code {self._process.returncode}. "
                    f"Check logs at {self._log_dir / 'daemon.log'}"
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
            f"Daemon did not become ready within {timeout}s. "
            f"Check logs at {self._log_dir / 'daemon.log'}"
        )
        if logs:
            msg += f"\n\nRecent logs:\n{logs}"
        raise DaemonConnectionError(msg)

    async def _grpc_health_check(self) -> bool:
        """Attempt a single gRPC GetNodeInfo call to verify daemon readiness."""
        try:
            channel = grpc.aio.insecure_channel(self._grpc_listen)
            try:
                stub = node_service_pb2_grpc.NodeServiceStub(channel)
                await stub.GetNodeInfo(
                    node_service_pb2.GetNodeInfoRequest(),
                    timeout=2,
                )
                return True
            except grpc.aio.AioRpcError:
                return False
            finally:
                await channel.close()
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
