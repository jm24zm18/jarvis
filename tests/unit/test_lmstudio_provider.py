import json

import httpx
import pytest

from jarvis.providers.lmstudio import LMStudioProvider


@pytest.mark.asyncio
async def test_lmstudio_generate_text_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LMSTUDIO_API_KEY", "")
    monkeypatch.setenv("LMSTUDIO_TIMEOUT_SECONDS", "30")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["model"] == "local-model"
            assert "authorization" not in request.headers
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "hello local",
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
        provider = LMStudioProvider("local-model", transport=httpx.MockTransport(handler))
        response = await provider.generate([{"role": "user", "content": "hi"}])
        assert response.text == "hello local"
        assert response.tool_calls == []
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_lmstudio_generate_with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LMSTUDIO_API_KEY", "test-lmstudio-key")
    monkeypatch.setenv("LMSTUDIO_TIMEOUT_SECONDS", "30")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            assert request.headers.get("authorization") == "Bearer test-lmstudio-key"
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
        provider = LMStudioProvider("local-model", transport=httpx.MockTransport(handler))
        response = await provider.generate(
            [{"role": "user", "content": "search something"}],
            tools=[{"name": "search", "description": "web search"}],
        )
        assert response.tool_calls == [{"name": "search", "arguments": {"query": "test"}}]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_lmstudio_health_check_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404)

    from jarvis.config import get_settings

    get_settings.cache_clear()
    try:
        provider = LMStudioProvider("local-model", transport=httpx.MockTransport(handler))
        assert await provider.health_check() is True
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_lmstudio_health_check_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    from jarvis.config import get_settings

    get_settings.cache_clear()
    try:
        provider = LMStudioProvider("local-model", transport=httpx.MockTransport(handler))
        assert await provider.health_check() is False
    finally:
        get_settings.cache_clear()
