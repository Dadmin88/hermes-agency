"""Tests for AGNTCY Agent Directory integration."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agentanycast.compat.agntcy import AGNTCYDirectory


class TestAGNTCYDirectory:
    def test_init_default_url(self):
        d = AGNTCYDirectory()
        assert d._base_url == "https://directory.agntcy.org"

    def test_init_custom_url(self):
        d = AGNTCYDirectory("https://custom.example.com/")
        assert d._base_url == "https://custom.example.com"  # trailing slash stripped

    def test_init_custom_timeout(self):
        d = AGNTCYDirectory(timeout=30.0)
        assert d._timeout == 30.0


class TestAGNTCYSearch:
    async def test_search_returns_agent_cards(self):
        mock_response = httpx.Response(
            200,
            json={
                "agents": [
                    {
                        "name": "WeatherBot",
                        "description": "Provides weather data",
                        "capabilities": [
                            {"name": "get_weather", "description": "Get current weather"},
                        ],
                    },
                    {
                        "name": "TranslateBot",
                        "description": "Translates text",
                        "capabilities": [
                            {"name": "translate", "description": "Translate text"},
                        ],
                    },
                ]
            },
            request=httpx.Request("GET", "https://directory.agntcy.org/api/v1/agents/search"),
        )

        with patch("agentanycast.compat.agntcy.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            d = AGNTCYDirectory()
            cards = await d.search("weather")

        assert len(cards) == 2
        assert cards[0].name == "WeatherBot"
        assert cards[0].skills[0].id == "get_weather"
        assert cards[1].name == "TranslateBot"

    async def test_search_empty_results(self):
        mock_response = httpx.Response(
            200,
            json={"agents": []},
            request=httpx.Request("GET", "https://directory.agntcy.org/api/v1/agents/search"),
        )

        with patch("agentanycast.compat.agntcy.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            d = AGNTCYDirectory()
            cards = await d.search("nonexistent")

        assert cards == []

    async def test_search_http_error_raises(self):
        mock_response = httpx.Response(
            500,
            request=httpx.Request("GET", "https://directory.agntcy.org/api/v1/agents/search"),
        )

        with patch("agentanycast.compat.agntcy.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            d = AGNTCYDirectory()
            with pytest.raises(httpx.HTTPStatusError):
                await d.search("weather")


class TestAGNTCYGetAgent:
    async def test_get_agent_found(self):
        mock_response = httpx.Response(
            200,
            json={
                "name": "TestAgent",
                "description": "A test agent",
                "version": "2.0.0",
                "capabilities": [
                    {"name": "echo", "description": "Echo input"},
                ],
            },
            request=httpx.Request("GET", "https://directory.agntcy.org/api/v1/agents/abc"),
        )

        with patch("agentanycast.compat.agntcy.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            d = AGNTCYDirectory()
            card = await d.get_agent("abc")

        assert card is not None
        assert card.name == "TestAgent"
        assert card.version == "2.0.0"
        assert len(card.skills) == 1

    async def test_get_agent_not_found(self):
        mock_response = httpx.Response(
            404,
            request=httpx.Request("GET", "https://directory.agntcy.org/api/v1/agents/missing"),
        )

        with patch("agentanycast.compat.agntcy.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            d = AGNTCYDirectory()
            card = await d.get_agent("missing")

        assert card is None


class TestTranslateEntry:
    def test_translate_full_entry(self):
        entry = {
            "name": "FullAgent",
            "description": "Full description",
            "version": "3.0.0",
            "capabilities": [
                {"name": "skill1", "description": "First skill"},
                {"name": "skill2", "description": "Second skill"},
            ],
        }
        card = AGNTCYDirectory._translate_entry(entry)
        assert card.name == "FullAgent"
        assert card.description == "Full description"
        assert card.version == "3.0.0"
        assert len(card.skills) == 2

    def test_translate_minimal_entry(self):
        card = AGNTCYDirectory._translate_entry({})
        assert card.name == ""
        assert card.skills == []

    def test_translate_entry_missing_capability_fields(self):
        entry = {"name": "Sparse", "capabilities": [{}]}
        card = AGNTCYDirectory._translate_entry(entry)
        assert len(card.skills) == 1
        assert card.skills[0].id == ""
        assert card.skills[0].description == ""
