"""Tests for framework adapter base class and adapter implementations."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentanycast.adapters._base import BaseAdapter
from agentanycast.card import AgentCard, Skill
from agentanycast.task import IncomingTask, Message, Part


class DummyAdapter(BaseAdapter):
    """Concrete adapter for testing."""

    def __init__(self, return_value: str | dict[str, Any] = "ok", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._return_value = return_value
        self.received_text: str = ""
        self.received_data: dict[str, Any] | None = None

    async def _invoke(
        self,
        input_text: str,
        input_data: dict[str, Any] | None,
    ) -> str | dict[str, Any]:
        self.received_text = input_text
        self.received_data = input_data
        return self._return_value


class FailingAdapter(BaseAdapter):
    """Adapter that raises during invocation."""

    async def _invoke(
        self,
        input_text: str,
        input_data: dict[str, Any] | None,
    ) -> str | dict[str, Any]:
        raise ValueError("Framework error")


def _make_card() -> AgentCard:
    return AgentCard(
        name="Test Agent",
        skills=[Skill(id="test", description="Test skill")],
    )


def _make_incoming_task(
    text: str = "Hello",
    data: dict[str, Any] | None = None,
) -> IncomingTask:
    """Create a mock IncomingTask."""
    parts = []
    if text:
        parts.append(Part(text=text))
    if data:
        parts.append(Part(data=data))

    task = MagicMock(spec=IncomingTask)
    task.task_id = "task-1"
    task.messages = [Message(role="user", parts=parts)]
    task.update_status = AsyncMock()
    task.complete = AsyncMock()
    task.fail = AsyncMock()
    return task


@patch("agentanycast.adapters._base.Node")
def test_base_adapter_init(mock_node_cls: MagicMock) -> None:
    """BaseAdapter should create a Node with the given config."""
    card = _make_card()
    adapter = DummyAdapter(card=card, relay="/ip4/1.2.3.4/tcp/9000")
    assert adapter._card == card
    mock_node_cls.assert_called_once_with(
        card=card,
        relay="/ip4/1.2.3.4/tcp/9000",
    )


@patch("agentanycast.adapters._base.Node")
async def test_handle_task_string_output(mock_node_cls: MagicMock) -> None:
    """String output should produce a text artifact."""
    adapter = DummyAdapter(return_value="Echo: Hello", card=_make_card())
    task = _make_incoming_task("Hello")

    await adapter._handle_task(task)

    task.update_status.assert_called_once_with("working")
    task.complete.assert_called_once()
    artifacts = task.complete.call_args.kwargs["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0].parts[0].text == "Echo: Hello"


@patch("agentanycast.adapters._base.Node")
async def test_handle_task_dict_output(mock_node_cls: MagicMock) -> None:
    """Dict output should produce a data artifact."""
    adapter = DummyAdapter(return_value={"key": "value"}, card=_make_card())
    task = _make_incoming_task("Input")

    await adapter._handle_task(task)

    task.complete.assert_called_once()
    artifacts = task.complete.call_args.kwargs["artifacts"]
    assert artifacts[0].parts[0].data == {"key": "value"}


@patch("agentanycast.adapters._base.Node")
async def test_handle_task_failure(mock_node_cls: MagicMock) -> None:
    """Adapter errors should call task.fail()."""
    adapter = FailingAdapter(card=_make_card())
    task = _make_incoming_task("Trigger error")

    await adapter._handle_task(task)

    task.update_status.assert_called_once_with("working")
    task.fail.assert_called_once()
    assert "Framework error" in task.fail.call_args.args[0]


@patch("agentanycast.adapters._base.Node")
async def test_handle_task_extracts_data(mock_node_cls: MagicMock) -> None:
    """_invoke should receive both text and structured data from message parts."""
    adapter = DummyAdapter(card=_make_card())
    task = _make_incoming_task(text="query text", data={"param": 42})

    await adapter._handle_task(task)

    assert adapter.received_text == "query text"
    assert adapter.received_data == {"param": 42}


def test_base_adapter_is_abstract() -> None:
    """BaseAdapter cannot be instantiated directly (ABC with abstract _invoke)."""
    with pytest.raises(TypeError, match="abstract"):
        BaseAdapter(card=_make_card())  # type: ignore[abstract]
