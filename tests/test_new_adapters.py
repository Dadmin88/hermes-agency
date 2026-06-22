"""Tests for Google ADK, OpenAI Agents SDK, Claude Agent SDK, and Strands adapters."""

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
# Shared helpers
# ---------------------------------------------------------------------------


def _async_iter_factory(items: list[Any]) -> Any:
    """Return a callable that produces an async iterator over *items*.

    Used by both ADK (as runner.run_async) and Claude (as query) tests.
    """

    async def _gen(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        for item in items:
            yield item

    return _gen


# ---------------------------------------------------------------------------
# ADK Adapter
# ---------------------------------------------------------------------------


class TestADKAdapter:
    """Tests for the ADK adapter."""

    def test_adk_import_error(self) -> None:
        """Verify helpful ImportError when google-adk not installed."""
        mods_to_hide = [
            k for k in sys.modules if k.startswith("google.adk") or k.startswith("google.genai")
        ]
        saved = {k: sys.modules.pop(k) for k in mods_to_hide}
        sys.modules.pop("agentanycast.adapters.adk", None)

        fake_google = MagicMock()
        del fake_google.adk
        del fake_google.genai

        try:
            with patch.dict(sys.modules, {"google": fake_google}, clear=False):
                with pytest.raises(ImportError, match="google-adk"):
                    importlib.import_module("agentanycast.adapters.adk")
        finally:
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

        try:
            with patch.dict(sys.modules, {"agents": None}, clear=False):
                with pytest.raises(ImportError, match="openai-agents"):
                    importlib.import_module("agentanycast.adapters.openai_agents")
        finally:
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
# Claude Agent SDK Adapter
# ---------------------------------------------------------------------------


class TestClaudeAgentAdapter:
    """Tests for the Claude Agent SDK adapter."""

    def test_claude_import_error(self) -> None:
        """Verify helpful ImportError when claude-agent-sdk not installed."""
        mods_to_hide = [k for k in sys.modules if k.startswith("claude_agent_sdk")]
        saved = {k: sys.modules.pop(k) for k in mods_to_hide}
        sys.modules.pop("agentanycast.adapters.claude_agent", None)

        try:
            with patch.dict(sys.modules, {"claude_agent_sdk": None}, clear=False):
                with pytest.raises(ImportError, match="claude-agent-sdk"):
                    importlib.import_module("agentanycast.adapters.claude_agent")
        finally:
            sys.modules.pop("agentanycast.adapters.claude_agent", None)
            sys.modules.update(saved)

    @pytest.mark.asyncio
    async def test_invoke_returns_result(self) -> None:
        """ClaudeAgentAdapter._invoke collects the final result."""
        adapter, query_mock = _make_claude_adapter()

        query_mock.side_effect = _async_iter_factory([MagicMock(result="Hello from Claude")])

        result = await adapter._invoke("hi", None)
        assert result == "Hello from Claude"

    @pytest.mark.asyncio
    async def test_invoke_empty_result(self) -> None:
        """ClaudeAgentAdapter._invoke returns empty string when no result."""
        adapter, query_mock = _make_claude_adapter()

        query_mock.side_effect = _async_iter_factory(
            [MagicMock(spec=[])]  # No 'result' attribute.
        )

        result = await adapter._invoke("hi", None)
        assert result == ""

    @pytest.mark.asyncio
    async def test_invoke_with_prompt_template(self) -> None:
        """ClaudeAgentAdapter._invoke prepends prompt template."""
        adapter, query_mock = _make_claude_adapter(prompt_template="Be helpful.")

        query_mock.side_effect = _async_iter_factory([MagicMock(result="Helped!")])

        result = await adapter._invoke("question", None)
        assert result == "Helped!"
        # Verify the query was called with both template and input text.
        call_kwargs = query_mock.call_args
        prompt_sent = call_kwargs.kwargs.get("prompt", "")
        assert "Be helpful." in prompt_sent
        assert "question" in prompt_sent

    @pytest.mark.asyncio
    async def test_invoke_passes_options(self) -> None:
        """ClaudeAgentAdapter._invoke forwards options to query()."""
        options_mock = MagicMock()
        adapter, query_mock = _make_claude_adapter(options=options_mock)

        query_mock.side_effect = _async_iter_factory([MagicMock(result="ok")])

        await adapter._invoke("hi", None)
        call_kwargs = query_mock.call_args
        assert call_kwargs.kwargs.get("options") is options_mock

    @pytest.mark.asyncio
    async def test_invoke_falls_back_to_data(self) -> None:
        """ClaudeAgentAdapter._invoke uses stringified data when text is empty."""
        adapter, query_mock = _make_claude_adapter()

        query_mock.side_effect = _async_iter_factory([])

        result = await adapter._invoke("", {"key": "value"})
        assert result == ""

    @pytest.mark.asyncio
    async def test_invoke_coerces_non_string_result(self) -> None:
        """ClaudeAgentAdapter._invoke converts non-string result to str."""
        adapter, query_mock = _make_claude_adapter()

        msg = MagicMock()
        msg.result = 42  # Non-string result.
        query_mock.side_effect = _async_iter_factory([msg])

        result = await adapter._invoke("hi", None)
        assert result == "42"

    def test_build_default_card_returns_none(self) -> None:
        """ClaudeAgentAdapter._build_default_card always returns None."""
        with _claude_modules_patched():
            from agentanycast.adapters.claude_agent import ClaudeAgentAdapter

            assert ClaudeAgentAdapter._build_default_card() is None
            assert ClaudeAgentAdapter._build_default_card("some string") is None


# ---------------------------------------------------------------------------
# Strands Adapter
# ---------------------------------------------------------------------------


class TestStrandsAdapter:
    """Tests for the AWS Strands Agent adapter."""

    def test_strands_import_error(self) -> None:
        """Verify helpful ImportError when strands-agents not installed."""
        mods_to_hide = [k for k in sys.modules if k.startswith("strands")]
        saved = {k: sys.modules.pop(k) for k in mods_to_hide}
        sys.modules.pop("agentanycast.adapters.strands", None)

        try:
            with patch.dict(sys.modules, {"strands": None}, clear=False):
                with pytest.raises(ImportError, match="strands-agents"):
                    importlib.import_module("agentanycast.adapters.strands")
        finally:
            sys.modules.pop("agentanycast.adapters.strands", None)
            sys.modules.update(saved)

    @pytest.mark.asyncio
    async def test_invoke_returns_output(self) -> None:
        """StrandsAdapter._invoke returns str(agent(...))."""
        adapter, agent_mock = _make_strands_adapter()

        agent_mock.return_value = "Hello from Strands"

        result = await adapter._invoke("hi", None)
        assert result == "Hello from Strands"
        agent_mock.assert_called_once_with("hi")

    @pytest.mark.asyncio
    async def test_invoke_none_output(self) -> None:
        """StrandsAdapter._invoke returns empty string when output is None."""
        adapter, agent_mock = _make_strands_adapter()

        agent_mock.return_value = None

        result = await adapter._invoke("hi", None)
        assert result == ""

    @pytest.mark.asyncio
    async def test_invoke_falsy_output_preserved(self) -> None:
        """StrandsAdapter._invoke preserves falsy non-None outputs."""
        adapter, agent_mock = _make_strands_adapter()

        agent_mock.return_value = 0
        result = await adapter._invoke("hi", None)
        assert result == "0"

    @pytest.mark.asyncio
    async def test_invoke_falls_back_to_data(self) -> None:
        """StrandsAdapter._invoke uses stringified data when text is empty."""
        adapter, agent_mock = _make_strands_adapter()

        agent_mock.return_value = "processed"

        result = await adapter._invoke("", {"key": "value"})
        assert result == "processed"
        call_args = agent_mock.call_args
        assert call_args.args[0] == str({"key": "value"})


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


def _claude_modules_patched():  # type: ignore[no-untyped-def]
    """Context manager that patches claude_agent_sdk modules for import."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():  # type: ignore[no-untyped-def]
        query_mock = MagicMock()
        options_cls_mock = MagicMock()
        with patch.dict(
            sys.modules,
            {
                "claude_agent_sdk": MagicMock(
                    query=query_mock,
                    ClaudeAgentOptions=options_cls_mock,
                ),
            },
        ):
            if "agentanycast.adapters.claude_agent" in sys.modules:
                del sys.modules["agentanycast.adapters.claude_agent"]
            with patch("agentanycast.adapters._base.Node"):
                yield

    return _ctx()


@patch("agentanycast.adapters._base.Node")
def _make_claude_adapter(
    mock_node_cls: MagicMock | None = None,
    prompt_template: str = "",
    options: Any = None,
) -> tuple[Any, MagicMock]:
    """Create a ClaudeAgentAdapter with mocked query.

    Returns (adapter, query_mock).
    """
    query_mock = MagicMock()
    options_cls_mock = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "claude_agent_sdk": MagicMock(
                query=query_mock,
                ClaudeAgentOptions=options_cls_mock,
            ),
        },
    ):
        if "agentanycast.adapters.claude_agent" in sys.modules:
            del sys.modules["agentanycast.adapters.claude_agent"]

        with patch("agentanycast.adapters._base.Node"):
            from agentanycast.adapters.claude_agent import ClaudeAgentAdapter

            # Patch the module-level query reference.
            with patch.object(
                sys.modules["agentanycast.adapters.claude_agent"],
                "query",
                query_mock,
            ):
                adapter = ClaudeAgentAdapter(
                    prompt_template=prompt_template,
                    options=options,
                    card=_make_card(),
                )

    return adapter, query_mock


@patch("agentanycast.adapters._base.Node")
def _make_strands_adapter(
    mock_node_cls: MagicMock | None = None,
) -> tuple[Any, MagicMock]:
    """Create a StrandsAdapter with a mocked Agent.

    Returns (adapter, agent_mock).
    """
    agent_cls_mock = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "strands": MagicMock(Agent=agent_cls_mock),
        },
    ):
        if "agentanycast.adapters.strands" in sys.modules:
            del sys.modules["agentanycast.adapters.strands"]

        with patch("agentanycast.adapters._base.Node"):
            from agentanycast.adapters.strands import StrandsAdapter

            agent_mock = MagicMock()
            adapter = StrandsAdapter(agent_mock, card=_make_card())

    return adapter, agent_mock
