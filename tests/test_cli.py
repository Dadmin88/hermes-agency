"""Tests for the CLI module."""

from __future__ import annotations

from click.testing import CliRunner

from agentanycast import __version__
from agentanycast.cli.main import _demo_terminal_echo_lines, _safe_terminal_text, cli


def test_cli_version() -> None:
    """--version should print the version string."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_help() -> None:
    """--help should succeed."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "AgentAnycast" in result.output


def test_info_command() -> None:
    """info command should print version and config info."""
    runner = CliRunner()
    result = runner.invoke(cli, ["info"])
    assert result.exit_code == 0
    assert f"AgentAnycast SDK v{__version__}" in result.output
    assert "Python:" in result.output
    assert "Default home:" in result.output


def test_discover_help() -> None:
    """discover --help should describe the command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", "--help"])
    assert result.exit_code == 0
    assert "Discover agents" in result.output


def test_discover_requires_skill_arg() -> None:
    """discover without a skill argument should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["discover"])
    assert result.exit_code != 0


def test_discover_invalid_tag() -> None:
    """discover with invalid tag format should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", "echo", "--tag", "invalid-no-equals"])
    assert result.exit_code != 0
    assert "Invalid tag format" in result.output


def test_send_help() -> None:
    """send --help should describe the command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["send", "--help"])
    assert result.exit_code == 0
    assert "Send a task" in result.output


def test_send_requires_args() -> None:
    """send without arguments should fail."""
    runner = CliRunner()
    result = runner.invoke(cli, ["send"])
    assert result.exit_code != 0


def test_status_help() -> None:
    """status --help should describe the command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--help"])
    assert result.exit_code == 0


def test_demo_help() -> None:
    """demo --help should describe the command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["demo", "--help"])
    assert result.exit_code == 0
    assert "echo agent" in result.output.lower()


def test_safe_terminal_text_strips_ansi_and_osc_controls() -> None:
    """Remote-originated terminal controls should be rendered inert."""
    value = "agent \x1b[31mRED\x1b[0m \x1b]52;c;SGVsbG8=\x07 done"

    safe = _safe_terminal_text(value)

    assert "\x1b" not in safe
    assert "\x07" not in safe
    assert safe == "agent [31mRED[0m ]52;c;SGVsbG8= done"


def test_safe_terminal_text_preserves_newlines_and_tabs() -> None:
    """Legitimate multiline text remains readable after sanitization."""
    assert _safe_terminal_text("line 1\n\tline 2") == "line 1\n\tline 2"


def test_demo_terminal_echo_lines_sanitize_remote_input() -> None:
    """Demo task logging should not emit terminal controls from remote input."""
    payload = "hello \x1b[31mRED\x1b[0m \x1b]52;c;SGVsbG8=\x07"

    input_line, reply_line = _demo_terminal_echo_lines(payload)

    assert "\x1b" not in input_line
    assert "\x07" not in input_line
    assert "\x1b" not in reply_line
    assert "\x07" not in reply_line
    assert input_line == "    Input:  'hello [31mRED[0m ]52;c;SGVsbG8='"
    assert reply_line == "    Reply:  Echo: hello [31mRED[0m ]52;c;SGVsbG8="
