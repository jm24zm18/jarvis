import json

import httpx
import pytest

from jarvis.providers.openrouter import OpenRouterProvider


@pytest.mark.asyncio
async def test_openrouter_generate_text_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_TIMEOUT_SECONDS", "30")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/chat/completions":
            assert request.headers.get("authorization") == "Bearer test-key"
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["model"] == "or-test"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "hello world",
                                "tool_calls": [],
                            }
                        }
                    ]
                },
            )
        return httpx.Response(404)

    from jarvis.config import get_settings

    get_settings.cache_clear()
    try:
        provider = OpenRouterProvider("or-test", transport=httpx.MockTransport(handler))
        response = await provider.generate([{"role": "user", "content": "hi"}])
        assert response.text == "hello world"
        assert response.tool_calls == []
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_openrouter_generate_with_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_TIMEOUT_SECONDS", "30")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/chat/completions":
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "search",
                                            "arguments": '{"query":"test"}',
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        return httpx.Response(404)

    from jarvis.config import get_settings

    get_settings.cache_clear()
    try:
        provider = OpenRouterProvider("or-test", transport=httpx.MockTransport(handler))
        response = await provider.generate(
            [{"role": "user", "content": "search something"}],
            tools=[{"name": "search", "description": "web search"}],
        )
        assert response.tool_calls == [{"name": "search", "arguments": {"query": "test"}}]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_openrouter_health_check_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404)

    from jarvis.config import get_settings

    get_settings.cache_clear()
    try:
        provider = OpenRouterProvider("or-test", transport=httpx.MockTransport(handler))
        assert await provider.health_check() is True
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_openrouter_health_check_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    from jarvis.config import get_settings

    get_settings.cache_clear()
    try:
        provider = OpenRouterProvider("or-test", transport=httpx.MockTransport(handler))
        assert await provider.health_check() is False
    finally:
        get_settings.cache_clear()


def test_openrouter_to_tools_normalization() -> None:
    tools = [
        {"name": "lookup", "description": "search tool", "parameters": {"type": "object"}},
        {"name": "", "description": "bad tool"},  # skipped
        {"name": "bare"},  # no description/params
    ]
    result = OpenRouterProvider._to_tools(tools)
    assert result is not None
    assert len(result) == 2
    assert result[0] == {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "search tool",
            "parameters": {"type": "object"},
        },
    }
    assert result[1] == {
        "type": "function",
        "function": {
            "name": "bare",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_openrouter_to_tools_empty() -> None:
    assert OpenRouterProvider._to_tools([]) is None
    assert OpenRouterProvider._to_tools(None) is None
