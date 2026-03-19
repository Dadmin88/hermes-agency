"""Tests for Google ADK and OpenAI Agents SDK adapters."""

from __future__ import annotations

import importlib
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentanycast.card import AgentCard, Skill


def _make_card() -> AgentCard:
    return AgentCard(
        name="Test Agent",
        skills=[Skill(id="test", description="Test skill")],
    )


# ---------------------------------------------------------------------------
# ADK Adapter
# ---------------------------------------------------------------------------


class TestADKAdapter:
    """Tests for the ADK adapter."""

    def test_adk_import_error(self) -> None:
        """Verify helpful ImportError when google-adk not installed."""
        # Ensure the real google.adk modules are NOT available.
        mods_to_hide = [
            k for k in sys.modules if k.startswith("google.adk") or k.startswith("google.genai")
        ]
        saved = {k: sys.modules.pop(k) for k in mods_to_hide}
        # Also remove cached adapter module so it re-imports.
        sys.modules.pop("agentanycast.adapters.adk", None)

        fake_google = MagicMock()
        # Make the nested attribute lookup raise ImportError.
        del fake_google.adk
        del fake_google.genai

        with patch.dict(sys.modules, {"google": fake_google}, clear=False):
            with pytest.raises(ImportError, match="google-adk"):
                importlib.import_module("agentanycast.adapters.adk")

        # Restore original state.
        sys.modules.pop("agentanycast.adapters.adk", None)
        sys.modules.update(saved)

    @pytest.mark.asyncio
    async def test_invoke_collects_final_response(self) -> None:
        """ADKAdapter._invoke collects text from final response events."""
        adapter, runner_mock = _make_adk_adapter()

        event = _adk_event(parts_text=["Hello from ADK"], is_final=True)
        runner_mock.run_async = _async_iter_factory([event])

        result = await adapter._invoke("hi", None)
        assert result == "Hello from ADK"

    @pytest.mark.asyncio
    async def test_invoke_empty_response(self) -> None:
        """ADKAdapter._invoke returns empty string when no final response."""
        adapter, runner_mock = _make_adk_adapter()

        # Non-final event only.
        event = _adk_event(parts_text=["thinking..."], is_final=False)
        runner_mock.run_async = _async_iter_factory([event])

        result = await adapter._invoke("hi", None)
        assert result == ""

    @pytest.mark.asyncio
    async def test_invoke_multiple_parts(self) -> None:
        """ADKAdapter._invoke joins multiple response parts."""
        adapter, runner_mock = _make_adk_adapter()

        event = _adk_event(parts_text=["Part A", "Part B"], is_final=True)
        runner_mock.run_async = _async_iter_factory([event])

        result = await adapter._invoke("hi", None)
        assert result == "Part A\nPart B"

    @pytest.mark.asyncio
    async def test_invoke_falls_back_to_data(self) -> None:
        """ADKAdapter._invoke uses stringified data when text is empty."""
        adapter, runner_mock = _make_adk_adapter()

        runner_mock.run_async = _async_iter_factory([])

        result = await adapter._invoke("", {"key": "value"})
        # When text is empty and data is provided, text becomes str(data).
        # The runner returns no events, so result is "".
        assert result == ""


# ---------------------------------------------------------------------------
# OpenAI Agents Adapter
# ---------------------------------------------------------------------------


class TestOpenAIAgentsAdapter:
    """Tests for the OpenAI Agents SDK adapter."""

    def test_openai_agents_import_error(self) -> None:
        """Verify helpful ImportError when openai-agents not installed."""
        mods_to_hide = [k for k in sys.modules if k.startswith("agents")]
        saved = {k: sys.modules.pop(k) for k in mods_to_hide}
        sys.modules.pop("agentanycast.adapters.openai_agents", None)

        with patch.dict(sys.modules, {"agents": None}, clear=False):
            with pytest.raises(ImportError, match="openai-agents"):
                importlib.import_module("agentanycast.adapters.openai_agents")

        sys.modules.pop("agentanycast.adapters.openai_agents", None)
        sys.modules.update(saved)

    @pytest.mark.asyncio
    async def test_invoke_returns_final_output(self) -> None:
        """OpenAIAgentsAdapter._invoke returns str(result.final_output)."""
        adapter, runner_cls_mock = _make_openai_adapter()

        run_result = MagicMock()
        run_result.final_output = "Hello from OpenAI"
        runner_cls_mock.run = AsyncMock(return_value=run_result)

        result = await adapter._invoke("hi", None)
        assert result == "Hello from OpenAI"
        runner_cls_mock.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invoke_none_output(self) -> None:
        """OpenAIAgentsAdapter._invoke returns empty string when output is None."""
        adapter, runner_cls_mock = _make_openai_adapter()

        run_result = MagicMock()
        run_result.final_output = None
        runner_cls_mock.run = AsyncMock(return_value=run_result)

        result = await adapter._invoke("hi", None)
        assert result == ""

    @pytest.mark.asyncio
    async def test_invoke_falls_back_to_data(self) -> None:
        """OpenAIAgentsAdapter._invoke uses stringified data when text is empty."""
        adapter, runner_cls_mock = _make_openai_adapter()

        run_result = MagicMock()
        run_result.final_output = "{'key': 'value'}"
        runner_cls_mock.run = AsyncMock(return_value=run_result)

        result = await adapter._invoke("", {"key": "value"})
        assert result == "{'key': 'value'}"
        # Verify the agent received str(data) since text was empty.
        call_args = runner_cls_mock.run.call_args
        assert call_args.args[1] == str({"key": "value"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _adk_event(
    parts_text: list[str],
    is_final: bool,
) -> MagicMock:
    """Create a mock ADK event with content parts and actions."""
    parts = []
    for t in parts_text:
        p = MagicMock()
        p.text = t
        parts.append(p)

    content = MagicMock()
    content.parts = parts

    actions = MagicMock()
    actions.is_final_response.return_value = is_final

    event = MagicMock()
    event.content = content
    event.actions = actions
    return event


def _async_iter_factory(events: list[Any]) -> Any:
    """Return a callable that produces an async iterator over *events*."""

    async def _run_async(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        for e in events:
            yield e

    return _run_async


@patch("agentanycast.adapters._base.Node")
def _make_adk_adapter(
    mock_node_cls: MagicMock | None = None,
) -> tuple[Any, MagicMock]:
    """Create an ADKAdapter with a mocked InMemoryRunner.

    Returns (adapter, runner_mock).
    """
    runner_mock = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "google": MagicMock(),
            "google.adk": MagicMock(),
            "google.adk.agents": MagicMock(),
            "google.adk.runners": MagicMock(),
            "google.genai": MagicMock(),
            "google.genai.types": MagicMock(),
        },
    ):
        # Reload the adapter module so it picks up the mocked imports.
        if "agentanycast.adapters.adk" in sys.modules:
            del sys.modules["agentanycast.adapters.adk"]

        with patch("agentanycast.adapters._base.Node"):
            from agentanycast.adapters.adk import ADKAdapter

            # Patch InMemoryRunner to return our mock.
            with patch.object(
                sys.modules["agentanycast.adapters.adk"],
                "InMemoryRunner",
                return_value=runner_mock,
            ):
                agent_mock = MagicMock()
                adapter = ADKAdapter(agent_mock, card=_make_card())

    return adapter, runner_mock


@patch("agentanycast.adapters._base.Node")
def _make_openai_adapter(
    mock_node_cls: MagicMock | None = None,
) -> tuple[Any, MagicMock]:
    """Create an OpenAIAgentsAdapter with mocked Runner.

    Returns (adapter, runner_cls_mock).
    """
    runner_cls_mock = MagicMock()
    agent_cls_mock = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "agents": MagicMock(Agent=agent_cls_mock, Runner=runner_cls_mock),
        },
    ):
        if "agentanycast.adapters.openai_agents" in sys.modules:
            del sys.modules["agentanycast.adapters.openai_agents"]

        with patch("agentanycast.adapters._base.Node"):
            from agentanycast.adapters.openai_agents import OpenAIAgentsAdapter

            # Patch the module-level Runner reference.
            with patch.object(
                sys.modules["agentanycast.adapters.openai_agents"],
                "Runner",
                runner_cls_mock,
            ):
                agent_mock = MagicMock()
                adapter = OpenAIAgentsAdapter(agent_mock, card=_make_card())

    return adapter, runner_cls_mock
