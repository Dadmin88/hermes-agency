"""Tests for DaemonManager — pure logic only, no subprocess or network."""

from pathlib import Path
from unittest.mock import patch

import pytest

from agentanycast.daemon import _PLATFORM_MAP, DaemonManager, _detect_platform
from agentanycast.exceptions import DaemonNotFoundError

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
        # Default version comes from importlib.metadata; verify it's a valid semver string.
        import re

        assert re.match(r"^\d+\.\d+\.\d+", dm._daemon_version)

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


# ── Store Path ───────────────────────────────────────────────


class TestStorePath:
    def test_store_path_under_base(self, tmp_path):
        dm = DaemonManager(home=tmp_path / "node1")
        assert dm._store_path == str(tmp_path / "node1" / "data")
