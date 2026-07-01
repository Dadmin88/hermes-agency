"""Tests for DaemonManager — pure logic only, no subprocess or network."""

import asyncio
import hashlib
import importlib
import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from agentanycast.daemon import (
    _DAEMON_SHA256,
    _DEFAULT_DAEMON_VERSION,
    _PLATFORM_MAP,
    DaemonManager,
    _detect_platform,
)
from agentanycast.exceptions import DaemonConnectionError, DaemonNotFoundError, DaemonStartError

daemon_module = importlib.import_module("agentanycast.daemon")

# ── Platform Detection ───────────────────────────────────────


class TestDetectPlatform:
    @patch("agentanycast.daemon.platform.system", return_value="Darwin")
    @patch("agentanycast.daemon.platform.machine", return_value="arm64")
    def test_darwin_arm64(self, _machine, _system):
        assert _detect_platform() == ("darwin", "arm64")

    @patch("agentanycast.daemon.platform.system", return_value="Darwin")
    @patch("agentanycast.daemon.platform.machine", return_value="x86_64")
    def test_darwin_amd64(self, _machine, _system):
        assert _detect_platform() == ("darwin", "amd64")

    @patch("agentanycast.daemon.platform.system", return_value="Linux")
    @patch("agentanycast.daemon.platform.machine", return_value="x86_64")
    def test_linux_amd64(self, _machine, _system):
        assert _detect_platform() == ("linux", "amd64")

    @patch("agentanycast.daemon.platform.system", return_value="Linux")
    @patch("agentanycast.daemon.platform.machine", return_value="aarch64")
    def test_linux_arm64(self, _machine, _system):
        assert _detect_platform() == ("linux", "arm64")

    @patch("agentanycast.daemon.platform.system", return_value="Windows")
    @patch("agentanycast.daemon.platform.machine", return_value="AMD64")
    def test_windows_amd64(self, _machine, _system):
        assert _detect_platform() == ("windows", "amd64")

    @patch("agentanycast.daemon.platform.system", return_value="FreeBSD")
    @patch("agentanycast.daemon.platform.machine", return_value="x86_64")
    def test_unsupported_platform_raises(self, _machine, _system):
        with pytest.raises(DaemonNotFoundError, match="Unsupported platform"):
            _detect_platform()

    def test_platform_map_has_five_entries(self):
        assert len(_PLATFORM_MAP) == 5


# ── DaemonManager Initialization ────────────────────────────


class TestDaemonManagerInit:
    def test_default_home_directory(self):
        dm = DaemonManager()
        assert dm._base == Path.home() / ".agentanycast"

    def test_custom_home_directory(self, tmp_path):
        dm = DaemonManager(home=tmp_path / "my-node")
        assert dm._base == tmp_path / "my-node"

    def test_bin_dir_under_base(self, tmp_path):
        dm = DaemonManager(home=tmp_path / "node1")
        assert dm._bin_dir == tmp_path / "node1" / "bin"

    def test_log_dir_under_base(self, tmp_path):
        dm = DaemonManager(home=tmp_path / "node1")
        assert dm._log_dir == tmp_path / "node1" / "logs"

    def test_default_grpc_listen_is_unix(self, tmp_path):
        dm = DaemonManager(home=tmp_path / "node1")
        assert dm._grpc_listen.startswith("unix://")
        assert "node1/daemon.sock" in dm._grpc_listen

    def test_custom_grpc_listen(self, tmp_path):
        dm = DaemonManager(home=tmp_path, grpc_listen="tcp://localhost:50051")
        assert dm._grpc_listen == "tcp://localhost:50051"

    def test_daemon_bin_path(self, tmp_path):
        custom_bin = tmp_path / "my-daemon"
        dm = DaemonManager(daemon_bin=custom_bin)
        assert dm._daemon_bin == custom_bin

    def test_daemon_bin_none_by_default(self):
        dm = DaemonManager()
        assert dm._daemon_bin is None

    def test_default_version(self):
        dm = DaemonManager()
        assert dm._daemon_version == _DEFAULT_DAEMON_VERSION

    def test_custom_version(self):
        dm = DaemonManager(daemon_version="0.2.0")
        assert dm._daemon_version == "0.2.0"

    def test_default_log_level(self):
        dm = DaemonManager()
        assert dm._log_level == "info"

    def test_custom_log_level(self):
        dm = DaemonManager(log_level="debug")
        assert dm._log_level == "debug"

    def test_relay_stored(self):
        dm = DaemonManager(relay="/ip4/1.2.3.4/tcp/4001/p2p/12D3KooWRelay")
        assert dm._relay == "/ip4/1.2.3.4/tcp/4001/p2p/12D3KooWRelay"

    def test_relay_none_by_default(self):
        dm = DaemonManager()
        assert dm._relay is None

    def test_key_path_defaults_to_base(self, tmp_path):
        dm = DaemonManager(home=tmp_path / "node1")
        assert dm._key_path == str(tmp_path / "node1" / "key")

    def test_custom_key_path(self, tmp_path):
        key = tmp_path / "my.key"
        dm = DaemonManager(key_path=key)
        assert dm._key_path == str(key)

    def test_process_is_none_initially(self):
        dm = DaemonManager()
        assert dm._process is None

    def test_not_managed_initially(self):
        dm = DaemonManager()
        assert dm._managed is False


# ── Properties ───────────────────────────────────────────────


class TestDaemonManagerProperties:
    def test_grpc_address_property(self, tmp_path):
        dm = DaemonManager(home=tmp_path)
        assert dm.grpc_address == dm._grpc_listen

    def test_sock_path_from_unix_address(self, tmp_path):
        dm = DaemonManager(home=tmp_path)
        expected = tmp_path / "daemon.sock"
        assert dm.sock_path == expected

    def test_sock_path_fallback_for_tcp(self, tmp_path):
        dm = DaemonManager(home=tmp_path, grpc_listen="tcp://localhost:50051")
        # Falls back to default sock path under base
        assert dm.sock_path == tmp_path / "daemon.sock"


# ── Binary Finding ───────────────────────────────────────────


class TestFindBinary:
    def test_explicit_path_found(self, tmp_path):
        binary = tmp_path / "agentanycastd"
        binary.write_text("#!/bin/sh\necho hello")
        dm = DaemonManager(daemon_bin=binary, home=tmp_path)
        assert dm._find_binary() == binary

    def test_explicit_path_not_exists(self, tmp_path):
        dm = DaemonManager(daemon_bin=tmp_path / "nonexistent", home=tmp_path)
        with pytest.raises(DaemonNotFoundError, match="not found"):
            dm._find_binary()

    @patch("agentanycast.daemon.shutil.which", return_value="/usr/local/bin/agentanycastd")
    def test_found_on_path(self, _which, tmp_path):
        dm = DaemonManager(home=tmp_path)
        assert dm._find_binary() == Path("/usr/local/bin/agentanycastd")

    def test_found_in_default_bin_dir(self, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        binary = bin_dir / "agentanycastd"
        binary.write_text("#!/bin/sh\necho hello")
        dm = DaemonManager(home=tmp_path)
        assert dm._find_binary() == binary

    @patch("agentanycast.daemon.shutil.which", return_value=None)
    def test_not_found_anywhere(self, _which, tmp_path):
        dm = DaemonManager(home=tmp_path)
        with pytest.raises(DaemonNotFoundError, match="not found"):
            dm._find_binary()


# ── Daemon Running Check ─────────────────────────────────────


class TestIsDaemonRunning:
    def test_not_running_when_no_socket(self, tmp_path):
        dm = DaemonManager(home=tmp_path)
        assert dm._is_daemon_running() is False

    def test_running_when_socket_exists(self, tmp_path):
        sock = tmp_path / "daemon.sock"
        sock.touch()
        dm = DaemonManager(home=tmp_path)
        assert dm._is_daemon_running() is True


class TestExistingSocketStartup:
    @pytest.mark.asyncio
    async def test_start_reuses_existing_healthy_socket_without_restart(self, tmp_path):
        sock = tmp_path / "daemon.sock"
        sock.touch()
        emitted = []
        dm = DaemonManager(home=tmp_path, status_callback=emitted.append)

        async def healthy(*, timeout=2.0, raise_on_timeout=False):
            return True

        async def ensure_binary():  # pragma: no cover - must not be called
            raise AssertionError("healthy existing daemon should not resolve/start a binary")

        dm._grpc_health_check = healthy
        dm.ensure_binary = ensure_binary

        await dm.start()

        assert dm._managed is False
        assert "Daemon already running." in emitted

    @pytest.mark.asyncio
    async def test_start_refuses_existing_socket_with_unknown_identity_for_requested_isolation(
        self, tmp_path
    ):
        sock = tmp_path / "daemon.sock"
        sock.touch()
        dm = DaemonManager(home=tmp_path, transport="libp2p", namespace="tenant-b")

        async def healthy(*, timeout=2.0, raise_on_timeout=False):
            return True

        dm._grpc_health_check = healthy

        with pytest.raises(DaemonConnectionError, match="identity is unknown") as excinfo:
            await dm.start()

        message = str(excinfo.value)
        assert "transport='libp2p'" in message
        assert "namespace='tenant-b'" in message

    @pytest.mark.asyncio
    async def test_start_refuses_existing_socket_with_mismatched_identity(self, tmp_path):
        sock = tmp_path / "daemon.sock"
        sock.touch()
        (tmp_path / "daemon.identity.json").write_text(
            '{"namespace": "tenant-a", "transport": "nats://broker:4222"}\n',
            encoding="utf-8",
        )
        dm = DaemonManager(home=tmp_path, transport="libp2p", namespace="tenant-b")

        async def healthy(*, timeout=2.0, raise_on_timeout=False):
            return True

        dm._grpc_health_check = healthy

        with pytest.raises(DaemonConnectionError, match="does not match") as excinfo:
            await dm.start()

        message = str(excinfo.value)
        assert "namespace: requested 'tenant-b', existing 'tenant-a'" in message
        assert "transport: requested 'libp2p', existing 'nats://broker:4222'" in message

    @pytest.mark.asyncio
    async def test_start_reuses_existing_socket_with_matching_identity(self, tmp_path):
        sock = tmp_path / "daemon.sock"
        sock.touch()
        (tmp_path / "daemon.identity.json").write_text(
            '{"namespace": "tenant-b", "transport": "libp2p"}\n', encoding="utf-8"
        )
        emitted = []
        dm = DaemonManager(
            home=tmp_path,
            transport="libp2p",
            namespace="tenant-b",
            status_callback=emitted.append,
        )

        async def healthy(*, timeout=2.0, raise_on_timeout=False):
            return True

        async def ensure_binary():  # pragma: no cover - must not be called
            raise AssertionError("matching existing daemon should not resolve/start a binary")

        dm._grpc_health_check = healthy
        dm.ensure_binary = ensure_binary

        await dm.start()

        assert dm._managed is False
        assert "Daemon already running." in emitted

    @pytest.mark.asyncio
    async def test_start_removes_stale_socket_and_starts_daemon(
        self, tmp_path, monkeypatch, caplog
    ):
        sock = tmp_path / "daemon.sock"
        sock.touch()
        emitted = []
        dm = DaemonManager(home=tmp_path, status_callback=emitted.append)
        binary = tmp_path / "agentanycastd"
        binary.write_text("#!/bin/sh\n")

        class FakeProcess:
            returncode = None

            def poll(self):
                return None

            def terminate(self):
                return None

            def wait(self, timeout=None):
                return 0

            def kill(self):
                return None

        async def unhealthy(*, timeout=2.0, raise_on_timeout=False):
            return False

        async def ensure_binary():
            return binary

        async def wait_ready(timeout):
            assert not sock.exists()

        dm._grpc_health_check = unhealthy
        dm.ensure_binary = ensure_binary
        dm._wait_ready = wait_ready
        popen_calls = []
        monkeypatch.setattr(
            daemon_module.subprocess,
            "Popen",
            lambda *args, **kwargs: popen_calls.append((args, kwargs)) or FakeProcess(),
        )

        with caplog.at_level("WARNING"):
            await dm.start()

        assert not sock.exists()
        assert popen_calls
        assert dm._managed is True
        assert "Removed stale daemon socket" in caplog.text
        assert any("Removed stale daemon socket" in message for message in emitted)

    @pytest.mark.asyncio
    async def test_start_passes_relay_as_bootstrap_peers(self, tmp_path, monkeypatch):
        relay = "/ip4/198.51.100.10/tcp/4001/p2p/12D3KooWRelay"
        dm = DaemonManager(home=tmp_path, relay=relay)
        binary = tmp_path / "agentanycastd"
        binary.write_text("#!/bin/sh\n")

        class FakeProcess:
            returncode = None

            def poll(self):
                return None

            def terminate(self):
                return None

            def wait(self, timeout=None):
                return 0

            def kill(self):
                return None

        async def ensure_binary():
            return binary

        async def wait_ready(timeout):
            return None

        dm.ensure_binary = ensure_binary
        dm._wait_ready = wait_ready
        popen_calls = []
        monkeypatch.setattr(
            daemon_module.subprocess,
            "Popen",
            lambda *args, **kwargs: popen_calls.append((args, kwargs)) or FakeProcess(),
        )

        await dm.start()

        cmd = popen_calls[0][0][0]
        assert f"--bootstrap-peers={relay}" in cmd

    @pytest.mark.asyncio
    async def test_start_writes_identity_for_requested_transport_and_namespace(
        self, tmp_path, monkeypatch
    ):
        dm = DaemonManager(home=tmp_path, transport="libp2p", namespace="tenant-b")
        binary = tmp_path / "agentanycastd"
        binary.write_text("#!/bin/sh\n")

        class FakeProcess:
            returncode = None

            def poll(self):
                return None

            def terminate(self):
                return None

            def wait(self, timeout=None):
                return 0

            def kill(self):
                return None

        async def ensure_binary():
            return binary

        async def wait_ready(timeout):
            return None

        dm.ensure_binary = ensure_binary
        dm._wait_ready = wait_ready
        monkeypatch.setattr(
            daemon_module.subprocess, "Popen", lambda *args, **kwargs: FakeProcess()
        )

        await dm.start()

        assert (tmp_path / "daemon.identity.json").read_text(encoding="utf-8") == (
            '{"namespace": "tenant-b", "transport": "libp2p"}\n'
        )

    @pytest.mark.asyncio
    async def test_permission_error_removing_stale_socket_is_actionable(
        self, tmp_path, monkeypatch
    ):
        sock = tmp_path / "daemon.sock"
        sock.touch()
        dm = DaemonManager(home=tmp_path)

        async def unhealthy(*, timeout=2.0, raise_on_timeout=False):
            return False

        original_unlink = Path.unlink

        def deny_socket_unlink(path, *args, **kwargs):
            if path == sock:
                raise PermissionError("denied")
            return original_unlink(path, *args, **kwargs)

        dm._grpc_health_check = unhealthy
        monkeypatch.setattr(Path, "unlink", deny_socket_unlink)

        with pytest.raises(DaemonStartError, match="permission") as excinfo:
            await dm.start()

        assert str(sock) in str(excinfo.value)
        assert "Remove the stale socket manually" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_existing_socket_health_check_timeout_has_remediation(self, tmp_path):
        sock = tmp_path / "daemon.sock"
        sock.touch()
        dm = DaemonManager(home=tmp_path)

        async def timeout(*, timeout=2.0, raise_on_timeout=False):
            raise TimeoutError("health check deadline exceeded")

        dm._grpc_health_check = timeout

        with pytest.raises(DaemonConnectionError, match="timed out") as excinfo:
            await dm.start()

        message = str(excinfo.value)
        assert str(sock) in message
        assert "pkill agentanycastd" in message
        assert "rm -f" in message


# ── Store Path ───────────────────────────────────────────────


class TestStorePath:
    def test_store_path_under_base(self, tmp_path):
        dm = DaemonManager(home=tmp_path / "node1")
        assert dm._store_path == str(tmp_path / "node1" / "data")


# ── Download Integrity ───────────────────────────────────────


class TestDownloadChecksumVerification:
    class _FakeStreamResponse:
        def __init__(self, payload: bytes, *, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code
            self.headers = {"content-length": str(len(payload))}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            if self.status_code >= 400:
                request = httpx.Request("GET", "https://example.invalid/daemon")
                response = httpx.Response(self.status_code, request=request)
                raise httpx.HTTPStatusError("download failed", request=request, response=response)

        async def aiter_bytes(self, chunk_size=65536):
            yield self._payload

    class _FakeAsyncClient:
        def __init__(self, payload: bytes, *, status_code: int = 200, **_kwargs):
            self._payload = payload
            self._status_code = status_code

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, _method, _url):
            return TestDownloadChecksumVerification._FakeStreamResponse(
                self._payload, status_code=self._status_code
            )

    def test_verify_binary_checksum_accepts_matching_sha256(self, tmp_path):
        binary = tmp_path / "agentanycastd"
        payload = b"trusted daemon binary"
        binary.write_bytes(payload)
        expected = hashlib.sha256(payload).hexdigest()

        dm = DaemonManager(home=tmp_path)
        dm._verify_binary_checksum(binary, expected)

        assert binary.exists()

    def test_verify_binary_checksum_deletes_mismatch_and_raises(self, tmp_path):
        binary = tmp_path / "agentanycastd"
        binary.write_bytes(b"tampered daemon binary")

        dm = DaemonManager(home=tmp_path)
        with pytest.raises(DaemonNotFoundError, match="checksum mismatch"):
            dm._verify_binary_checksum(binary, "0" * 64)

        assert not binary.exists()

    def test_checksum_verification_enabled_by_default(self, tmp_path):
        dm = DaemonManager(home=tmp_path)

        assert dm._verify_checksum is True

    def test_checksum_verification_can_be_disabled_for_rollout(self, tmp_path):
        dm = DaemonManager(home=tmp_path, verify_checksum=False)

        assert dm._verify_checksum is False

    def test_daemon_sha256_dict_has_entries_for_current_version(self):
        current_entries = {
            k: v for k, v in _DAEMON_SHA256.items() if k[0] == _DEFAULT_DAEMON_VERSION
        }
        assert len(current_entries) >= 2, (
            f"_DAEMON_SHA256 should have entries for daemon v{_DEFAULT_DAEMON_VERSION} "
            f"(darwin/amd64, linux/amd64 at minimum); found {len(current_entries)}"
        )

    def test_expected_binary_checksum_returns_pinned_hash(self, tmp_path):
        dm = DaemonManager(home=tmp_path, daemon_version="9.9.9")
        with patch.dict(_DAEMON_SHA256, {("9.9.9", "linux", "amd64"): "a" * 64}):
            assert dm._expected_binary_checksum("linux", "amd64") == "a" * 64

    def test_expected_binary_checksum_fails_closed_without_pinned_hash(self, tmp_path):
        dm = DaemonManager(home=tmp_path, daemon_version="9.9.9")
        with pytest.raises(DaemonNotFoundError, match="No pinned SHA-256 checksum"):
            dm._expected_binary_checksum("linux", "amd64")

    def test_download_verifies_temp_file_before_replacing_existing_binary(
        self, tmp_path, monkeypatch
    ):
        existing_payload = b"existing trusted daemon"
        malicious_payload = b"tampered daemon binary"
        dest = tmp_path / "bin" / "agentanycastd"
        dest.parent.mkdir()
        dest.write_bytes(existing_payload)
        dest.chmod(0o755)

        dm = DaemonManager(home=tmp_path, daemon_version="9.9.9")
        monkeypatch.setattr(daemon_module, "_detect_platform", lambda: ("linux", "amd64"))
        monkeypatch.setattr(
            daemon_module.httpx,
            "AsyncClient",
            lambda **kwargs: self._FakeAsyncClient(malicious_payload, **kwargs),
        )

        with patch.dict(_DAEMON_SHA256, {("9.9.9", "linux", "amd64"): "0" * 64}):
            with pytest.raises(DaemonNotFoundError, match="checksum mismatch"):
                asyncio.run(dm.download_binary())

        assert dest.read_bytes() == existing_payload
        assert oct(dest.stat().st_mode & 0o777) == "0o755"
        assert not list(dest.parent.glob(".*.tmp"))

    def test_download_replaces_binary_only_after_checksum_match(self, tmp_path, monkeypatch):
        payload = b"trusted replacement daemon"
        expected = hashlib.sha256(payload).hexdigest()
        dest = tmp_path / "bin" / "agentanycastd"
        dest.parent.mkdir()
        dest.write_bytes(b"old daemon")

        dm = DaemonManager(home=tmp_path, daemon_version="9.9.9")
        monkeypatch.setattr(daemon_module, "_detect_platform", lambda: ("linux", "amd64"))
        monkeypatch.setattr(
            daemon_module.httpx,
            "AsyncClient",
            lambda **kwargs: self._FakeAsyncClient(payload, **kwargs),
        )

        with patch.dict(_DAEMON_SHA256, {("9.9.9", "linux", "amd64"): expected}):
            result = asyncio.run(dm.download_binary())

        assert result == dest
        assert dest.read_bytes() == payload
        assert os.access(dest, os.X_OK)
        assert not list(dest.parent.glob(".*.tmp"))
