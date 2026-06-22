"""Tests for Task, Message, Part, TaskHandle, and IncomingTask."""

import asyncio

import pytest

from agentanycast import Artifact, Message, Part, Task, TaskStatus
from agentanycast.task import IncomingTask, TaskHandle


def test_part_text_roundtrip():
    part = Part(text="Hello world")
    d = part.to_dict()
    assert d["text"] == "Hello world"
    restored = Part.from_dict(d)
    assert restored.text == "Hello world"


def test_part_data_roundtrip():
    part = Part(data={"total": 42, "items": ["a", "b"]})
    d = part.to_dict()
    restored = Part.from_dict(d)
    assert restored.data == {"total": 42, "items": ["a", "b"]}


def test_message_roundtrip():
    msg = Message(
        role="user",
        parts=[Part(text="Analyze Q4 sales")],
        message_id="msg-1",
    )
    d = msg.to_dict()
    assert d["role"] == "user"
    assert len(d["parts"]) == 1

    restored = Message.from_dict(d)
    assert restored.role == "user"
    assert restored.parts[0].text == "Analyze Q4 sales"


def test_artifact_roundtrip():
    artifact = Artifact(
        artifact_id="art-1",
        name="result",
        parts=[Part(data={"status": "ok"})],
    )
    d = artifact.to_dict()
    restored = Artifact.from_dict(d)
    assert restored.name == "result"
    assert restored.parts[0].data == {"status": "ok"}


def test_task_status_terminal():
    assert TaskStatus.COMPLETED.is_terminal
    assert TaskStatus.FAILED.is_terminal
    assert TaskStatus.CANCELED.is_terminal
    assert TaskStatus.REJECTED.is_terminal
    assert not TaskStatus.SUBMITTED.is_terminal
    assert not TaskStatus.WORKING.is_terminal
    assert not TaskStatus.INPUT_REQUIRED.is_terminal


@pytest.mark.asyncio
async def test_task_handle_wait_completed():
    task = Task(task_id="t1", status=TaskStatus.SUBMITTED)

    async def noop() -> None:
        pass

    handle = TaskHandle(task=task, cancel_fn=noop)

    # Simulate async update
    async def update_later():
        await asyncio.sleep(0.05)
        handle._update(TaskStatus.WORKING)
        await asyncio.sleep(0.05)
        handle._update(TaskStatus.COMPLETED, [Artifact(name="result")])

    asyncio.create_task(update_later())
    result = await handle.wait(timeout=2.0)
    assert result.status == TaskStatus.COMPLETED
    assert len(result.artifacts) == 1


@pytest.mark.asyncio
async def test_task_handle_wait_timeout():
    task = Task(task_id="t2", status=TaskStatus.SUBMITTED)

    async def noop() -> None:
        pass

    handle = TaskHandle(task=task, cancel_fn=noop)

    from agentanycast.exceptions import TaskTimeoutError

    with pytest.raises(TaskTimeoutError):
        await handle.wait(timeout=0.1)


@pytest.mark.asyncio
async def test_task_handle_already_terminal():
    task = Task(task_id="t3", status=TaskStatus.COMPLETED)

    async def noop() -> None:
        pass

    handle = TaskHandle(task=task, cancel_fn=noop)
    result = await handle.wait(timeout=1.0)
    assert result.status == TaskStatus.COMPLETED


# ── IncomingTask Tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_incoming_task_request_input_with_message_object():
    """request_input() should pass message text through the update function."""
    task = Task(task_id="t-input-1", status=TaskStatus.WORKING)
    captured: list[tuple[str, TaskStatus, object, str | None]] = []

    async def update_fn(
        task_id: str,
        status: TaskStatus,
        artifacts: list[Artifact] | None,
        error: str | None,
    ) -> None:
        captured.append((task_id, status, artifacts, error))

    incoming = IncomingTask(task=task, sender_card=None, update_fn=update_fn)

    msg = Message(role="agent", parts=[Part(text="What is your name?")])
    await incoming.request_input(msg)

    assert len(captured) == 1
    tid, status, arts, err_msg = captured[0]
    assert tid == "t-input-1"
    assert status == TaskStatus.INPUT_REQUIRED
    assert arts is None
    assert err_msg == "What is your name?"


@pytest.mark.asyncio
async def test_incoming_task_request_input_with_dict():
    """request_input() should extract text from dict message."""
    task = Task(task_id="t-input-2", status=TaskStatus.WORKING)
    captured: list[tuple[str, TaskStatus, object, str | None]] = []

    async def update_fn(
        task_id: str,
        status: TaskStatus,
        artifacts: list[Artifact] | None,
        error: str | None,
    ) -> None:
        captured.append((task_id, status, artifacts, error))

    incoming = IncomingTask(task=task, sender_card=None, update_fn=update_fn)

    await incoming.request_input({"parts": [{"text": "Please provide more details"}]})

    assert len(captured) == 1
    _, _, _, err_msg = captured[0]
    assert err_msg == "Please provide more details"


@pytest.mark.asyncio
async def test_incoming_task_request_input_without_message():
    """request_input() with no message should pass None."""
    task = Task(task_id="t-input-3", status=TaskStatus.WORKING)
    captured: list[tuple[str, TaskStatus, object, str | None]] = []

    async def update_fn(
        task_id: str,
        status: TaskStatus,
        artifacts: list[Artifact] | None,
        error: str | None,
    ) -> None:
        captured.append((task_id, status, artifacts, error))

    incoming = IncomingTask(task=task, sender_card=None, update_fn=update_fn)

    await incoming.request_input()

    assert len(captured) == 1
    _, status, _, err_msg = captured[0]
    assert status == TaskStatus.INPUT_REQUIRED
    assert err_msg is None


@pytest.mark.asyncio
async def test_incoming_task_request_input_with_multiple_parts():
    """request_input() should join text from multiple parts."""
    task = Task(task_id="t-input-4", status=TaskStatus.WORKING)
    captured: list[tuple[str, TaskStatus, object, str | None]] = []

    async def update_fn(
        task_id: str,
        status: TaskStatus,
        artifacts: list[Artifact] | None,
        error: str | None,
    ) -> None:
        captured.append((task_id, status, artifacts, error))

    incoming = IncomingTask(task=task, sender_card=None, update_fn=update_fn)

    msg = Message(role="agent", parts=[Part(text="Please provide"), Part(text="your email")])
    await incoming.request_input(msg)

    assert len(captured) == 1
    _, _, _, err_msg = captured[0]
    assert err_msg == "Please provide your email"


@pytest.mark.asyncio
async def test_incoming_task_complete():
    """complete() should pass COMPLETED status and artifacts."""
    task = Task(task_id="t-complete-1", status=TaskStatus.WORKING)
    captured: list[tuple[str, TaskStatus, object, str | None]] = []

    async def update_fn(
        task_id: str,
        status: TaskStatus,
        artifacts: list[Artifact] | None,
        error: str | None,
    ) -> None:
        captured.append((task_id, status, artifacts, error))

    incoming = IncomingTask(task=task, sender_card=None, update_fn=update_fn)

    await incoming.complete(artifacts=[Artifact(name="result", parts=[Part(text="done")])])

    assert len(captured) == 1
    _, status, arts, err_msg = captured[0]
    assert status == TaskStatus.COMPLETED
    assert arts is not None
    assert len(arts) == 1
    assert arts[0].name == "result"
    assert err_msg is None


@pytest.mark.asyncio
async def test_incoming_task_fail():
    """fail() should pass FAILED status and error message."""
    task = Task(task_id="t-fail-1", status=TaskStatus.WORKING)
    captured: list[tuple[str, TaskStatus, object, str | None]] = []

    async def update_fn(
        task_id: str,
        status: TaskStatus,
        artifacts: list[Artifact] | None,
        error: str | None,
    ) -> None:
        captured.append((task_id, status, artifacts, error))

    incoming = IncomingTask(task=task, sender_card=None, update_fn=update_fn)

    await incoming.fail("something went wrong")

    assert len(captured) == 1
    _, status, arts, err_msg = captured[0]
    assert status == TaskStatus.FAILED
    assert arts is None
    assert err_msg == "something went wrong"


@pytest.mark.asyncio
async def test_incoming_task_update_status():
    """update_status() should pass the correct status."""
    task = Task(task_id="t-status-1", status=TaskStatus.SUBMITTED)
    captured: list[tuple[str, TaskStatus, object, str | None]] = []

    async def update_fn(
        task_id: str,
        status: TaskStatus,
        artifacts: list[Artifact] | None,
        error: str | None,
    ) -> None:
        captured.append((task_id, status, artifacts, error))

    incoming = IncomingTask(task=task, sender_card=None, update_fn=update_fn)

    await incoming.update_status("working")

    assert len(captured) == 1
    _, status, arts, err_msg = captured[0]
    assert status == TaskStatus.WORKING
    assert arts is None
    assert err_msg is None


@pytest.mark.asyncio
async def test_incoming_task_complete_with_dict_artifacts():
    """complete() should convert dict artifacts to Artifact objects."""
    task = Task(task_id="t-dict-art", status=TaskStatus.WORKING)
    captured: list[tuple[str, TaskStatus, object, str | None]] = []

    async def update_fn(
        task_id: str,
        status: TaskStatus,
        artifacts: list[Artifact] | None,
        error: str | None,
    ) -> None:
        captured.append((task_id, status, artifacts, error))

    incoming = IncomingTask(task=task, sender_card=None, update_fn=update_fn)

    await incoming.complete(
        artifacts=[{"artifact_id": "a1", "name": "output", "parts": [{"text": "result"}]}]
    )

    assert len(captured) == 1
    _, status, arts, _ = captured[0]
    assert status == TaskStatus.COMPLETED
    assert arts is not None
    assert len(arts) == 1
    assert isinstance(arts[0], Artifact)
    assert arts[0].artifact_id == "a1"
    assert arts[0].name == "output"


@pytest.mark.asyncio
async def test_incoming_task_properties():
    """IncomingTask should expose task properties correctly."""
    task = Task(
        task_id="t-props",
        status=TaskStatus.SUBMITTED,
        originator_peer_id="12D3KooWPeer",
        target_skill_id="analyze",
        messages=[Message(role="user", parts=[Part(text="hello")])],
    )

    async def noop_fn(
        task_id: str,
        status: TaskStatus,
        artifacts: list[Artifact] | None,
        error: str | None,
    ) -> None:
        pass

    incoming = IncomingTask(task=task, sender_card=None, update_fn=noop_fn)

    assert incoming.task_id == "t-props"
    assert incoming.peer_id == "12D3KooWPeer"
    assert incoming.target_skill_id == "analyze"
    assert len(incoming.messages) == 1
    assert incoming.messages[0].parts[0].text == "hello"
    assert incoming.sender_card is None


@pytest.mark.asyncio
async def test_incoming_task_request_input_non_text_parts_ignored():
    """request_input() with non-text parts should produce None msg_text."""
    task = Task(task_id="t-input-notext", status=TaskStatus.WORKING)
    captured: list[tuple[str, TaskStatus, object, str | None]] = []

    async def update_fn(
        task_id: str,
        status: TaskStatus,
        artifacts: list[Artifact] | None,
        error: str | None,
    ) -> None:
        captured.append((task_id, status, artifacts, error))

    incoming = IncomingTask(task=task, sender_card=None, update_fn=update_fn)

    # Message with only URL parts, no text.
    msg = Message(role="agent", parts=[Part(url="https://example.com")])
    await incoming.request_input(msg)

    assert len(captured) == 1
    _, _, _, err_msg = captured[0]
    assert err_msg is None


@pytest.mark.asyncio
async def test_task_handle_wait_failed():
    """wait() should raise TaskFailedError when task fails."""
    task = Task(task_id="t-fail-wait", status=TaskStatus.SUBMITTED)

    async def noop() -> None:
        pass

    handle = TaskHandle(task=task, cancel_fn=noop)

    from agentanycast.exceptions import TaskFailedError

    async def fail_later():
        await asyncio.sleep(0.05)
        handle._update(TaskStatus.FAILED)

    asyncio.create_task(fail_later())

    with pytest.raises(TaskFailedError):
        await handle.wait(timeout=2.0)


@pytest.mark.asyncio
async def test_task_handle_wait_canceled():
    """wait() should raise TaskCanceledError when task is canceled."""
    task = Task(task_id="t-cancel-wait", status=TaskStatus.SUBMITTED)

    async def noop() -> None:
        pass

    handle = TaskHandle(task=task, cancel_fn=noop)

    from agentanycast.exceptions import TaskCanceledError

    async def cancel_later():
        await asyncio.sleep(0.05)
        handle._update(TaskStatus.CANCELED)

    asyncio.create_task(cancel_later())

    with pytest.raises(TaskCanceledError):
        await handle.wait(timeout=2.0)


@pytest.mark.asyncio
async def test_task_handle_cancel_calls_fn():
    """cancel() should call the cancel function."""
    task = Task(task_id="t-cancel-fn", status=TaskStatus.SUBMITTED)

    cancel_called = False

    async def cancel_fn() -> None:
        nonlocal cancel_called
        cancel_called = True

    handle = TaskHandle(task=task, cancel_fn=cancel_fn)
    await handle.cancel()
    assert cancel_called
