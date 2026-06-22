"""Tests for the AgentAnycast exception hierarchy."""

import pytest

from agentanycast.exceptions import (
    AgentAnycastError,
    CardError,
    CardNotAvailableError,
    DaemonConnectionError,
    DaemonError,
    DaemonNotFoundError,
    DaemonStartError,
    PeerAuthenticationError,
    PeerDisconnectedError,
    PeerError,
    PeerNotFoundError,
    TaskCanceledError,
    TaskError,
    TaskFailedError,
    TaskNotFoundError,
    TaskRejectedError,
    TaskTimeoutError,
)

# ── Hierarchy Tests ──────────────────────────────────────────


class TestExceptionHierarchy:
    """All exceptions must descend from AgentAnycastError."""

    @pytest.mark.parametrize(
        "exc_cls",
        [
            DaemonError,
            DaemonNotFoundError,
            DaemonStartError,
            DaemonConnectionError,
            PeerError,
            PeerNotFoundError,
            PeerDisconnectedError,
            PeerAuthenticationError,
            TaskError,
            TaskNotFoundError,
            TaskTimeoutError,
            TaskCanceledError,
            TaskFailedError,
            TaskRejectedError,
            CardError,
            CardNotAvailableError,
        ],
    )
    def test_is_subclass_of_base(self, exc_cls: type):
        assert issubclass(exc_cls, AgentAnycastError)

    def test_daemon_errors_inherit_daemon_error(self):
        assert issubclass(DaemonNotFoundError, DaemonError)
        assert issubclass(DaemonStartError, DaemonError)
        assert issubclass(DaemonConnectionError, DaemonError)

    def test_peer_errors_inherit_peer_error(self):
        assert issubclass(PeerNotFoundError, PeerError)
        assert issubclass(PeerDisconnectedError, PeerError)
        assert issubclass(PeerAuthenticationError, PeerError)

    def test_task_errors_inherit_task_error(self):
        assert issubclass(TaskNotFoundError, TaskError)
        assert issubclass(TaskTimeoutError, TaskError)
        assert issubclass(TaskCanceledError, TaskError)
        assert issubclass(TaskFailedError, TaskError)
        assert issubclass(TaskRejectedError, TaskError)

    def test_card_errors_inherit_card_error(self):
        assert issubclass(CardNotAvailableError, CardError)

    def test_all_are_exceptions(self):
        assert issubclass(AgentAnycastError, Exception)


# ── Instantiation Tests ──────────────────────────────────────


class TestExceptionMessages:
    def test_base_error_message(self):
        err = AgentAnycastError("something went wrong")
        assert str(err) == "something went wrong"

    def test_daemon_not_found_error(self):
        err = DaemonNotFoundError("binary missing")
        assert "binary missing" in str(err)

    def test_daemon_start_error(self):
        err = DaemonStartError("exit code 1")
        assert "exit code 1" in str(err)

    def test_daemon_connection_error(self):
        err = DaemonConnectionError("timeout connecting")
        assert "timeout connecting" in str(err)

    def test_peer_not_found_error(self):
        err = PeerNotFoundError("peer 12D3KooW... unreachable")
        assert "unreachable" in str(err)

    def test_peer_disconnected_error(self):
        err = PeerDisconnectedError("lost connection")
        assert "lost connection" in str(err)

    def test_peer_authentication_error(self):
        err = PeerAuthenticationError("Noise handshake failed")
        assert "Noise" in str(err)

    def test_task_not_found_error(self):
        err = TaskNotFoundError("task-123 not found")
        assert "task-123" in str(err)

    def test_task_timeout_error(self):
        err = TaskTimeoutError("timed out after 30s")
        assert "30s" in str(err)

    def test_task_canceled_error(self):
        err = TaskCanceledError("canceled by user")
        assert "canceled" in str(err)

    def test_task_rejected_error(self):
        err = TaskRejectedError("rejected")
        assert "rejected" in str(err)

    def test_card_not_available_error(self):
        err = CardNotAvailableError("no card shared")
        assert "no card" in str(err)


class TestTaskFailedErrorDetail:
    """TaskFailedError has an extra error_detail attribute."""

    def test_with_message_only(self):
        err = TaskFailedError("task failed")
        assert str(err) == "task failed"
        assert err.error_detail == ""

    def test_with_error_detail_only(self):
        err = TaskFailedError(error_detail="internal server error")
        assert str(err) == "internal server error"
        assert err.error_detail == "internal server error"

    def test_with_both(self):
        err = TaskFailedError("task failed", error_detail="OOM")
        assert str(err) == "task failed"
        assert err.error_detail == "OOM"

    def test_catchable_as_task_error(self):
        with pytest.raises(TaskError):
            raise TaskFailedError("boom")

    def test_catchable_as_base_error(self):
        with pytest.raises(AgentAnycastError):
            raise TaskFailedError("boom")
