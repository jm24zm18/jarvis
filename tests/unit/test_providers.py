import json

import httpx
import pytest

from jarvis.config import get_settings
from jarvis.providers.gemini import GeminiProvider
from jarvis.providers.sglang import SGLangProvider


@pytest.mark.asyncio
async def test_gemini_generate_with_oauth_refresh_and_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_TOKEN", "refresh")
    get_settings.cache_clear()
    token_calls = {"count": 0}
    generate_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            token_calls["count"] += 1
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if request.url.path.endswith(":generateContent"):
            generate_calls["count"] += 1
            body = json.loads(request.content.decode("utf-8"))
            assert "contents" in body
            if body["contents"]:
                assert body["contents"][0]["role"] == "user"
            if generate_calls["count"] == 1:
                assert body["systemInstruction"]["parts"][0]["text"] == "You are concise."
            else:
                assert "systemInstruction" not in body
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "hello"},
                                    {"functionCall": {"name": "echo", "args": {"k": "v"}}},
                                ]
                            }
                        }
                    ]
                },
            )
        if request.url.path.endswith("/models/gemini-test"):
            return httpx.Response(200, json={"name": "gemini-test"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    provider = GeminiProvider("gemini-test", transport=transport)
    first = await provider.generate(
        [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "hi"},
        ],
        tools=[{"name": "echo"}],
    )
    second = await provider.generate([{"role": "user", "content": "again"}])
    healthy = await provider.health_check()
    assert first.text == "hello"
    assert first.tool_calls == [{"name": "echo", "arguments": {"k": "v"}}]
    assert second.text == "hello"
    assert token_calls["count"] == 1
    assert healthy is True


@pytest.mark.asyncio
async def test_sglang_generate_parses_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SGLANG_BASE_URL", "http://sglang.local/v1")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["model"] == "sg-test"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "done",
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "lookup",
                                            "arguments": '{"term":"abc"}',
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404)

    provider = SGLangProvider("sg-test", transport=httpx.MockTransport(handler))
    response = await provider.generate(
        [{"role": "user", "content": "run"}],
        tools=[{"name": "lookup", "description": "search"}],
    )
    healthy = await provider.health_check()
    assert response.text == "done"
    assert response.tool_calls == [{"name": "lookup", "arguments": {"term": "abc"}}]
    assert healthy is True
