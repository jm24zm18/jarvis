import json

import httpx
import pytest

from jarvis.config import get_settings
from jarvis.providers.factory import build_fallback_provider, build_primary_provider
from jarvis.providers.google_gemini_cli import GeminiCodeAssistProvider
from jarvis.providers.sglang import SGLangProvider


@pytest.mark.asyncio
async def test_code_assist_generate_with_token_cache(tmp_path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "tok",
                "refresh_token": "refresh",
                "expires_at_ms": 9_999_999_999_999,
                "cloudaicompanion_project": "cap-1",
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":streamGenerateContent"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["project"] == "cap-1"
            request_payload = body["request"]
            assert "contents" in request_payload
            if request_payload["contents"]:
                assert request_payload["contents"][0]["role"] == "user"
            if "systemInstruction" in request_payload:
                assert (
                    request_payload["systemInstruction"]["parts"][0]["text"]
                    == "You are concise."
                )
            return httpx.Response(
                200,
                text="\n\n".join(
                    [
                        (
                            "data: "
                            '{"candidates":[{"content":{"parts":[{"text":"hello"},'
                            '{"functionCall":{"name":"echo","args":{"k":"v"}}}]}}]}'
                        ),
                        "data: [DONE]",
                        "",
                    ]
                ),
            )
        return httpx.Response(404)

    provider = GeminiCodeAssistProvider(
        "gemini-test",
        token_path=str(token_path),
        transport=httpx.MockTransport(handler),
    )
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
    assert healthy is True


@pytest.mark.asyncio
async def test_sglang_generate_parses_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SGLANG_BASE_URL", "http://sglang.local/v1")

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
                                "reasoning_content": "inspect args",
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
    assert response.reasoning_text == "inspect args"
    assert response.tool_calls == [{"name": "lookup", "arguments": {"term": "abc"}}]
    assert healthy is True


def test_provider_factory_supports_switching_primary_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIMARY_PROVIDER", "sglang")
    monkeypatch.setenv("SGLANG_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        primary = build_primary_provider(settings)
        fallback = build_fallback_provider(settings)
    finally:
        get_settings.cache_clear()
    assert isinstance(primary, SGLangProvider)
    assert isinstance(fallback, GeminiCodeAssistProvider)


def test_provider_factory_passes_gemini_quota_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIMARY_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_CODE_ASSIST_PLAN_TIER", "pro")
    monkeypatch.setenv("GEMINI_CODE_ASSIST_REQUESTS_PER_MINUTE", "0")
    monkeypatch.setenv("GEMINI_CODE_ASSIST_REQUESTS_PER_DAY", "0")
    monkeypatch.setenv("GEMINI_QUOTA_COOLDOWN_DEFAULT_SECONDS", "90")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        primary = build_primary_provider(settings)
    finally:
        get_settings.cache_clear()
    assert isinstance(primary, GeminiCodeAssistProvider)
    assert primary.quota_plan_tier == "pro"
    assert primary.requests_per_minute_limit == 120
    assert primary.requests_per_day_limit == 1500
    assert primary.quota_cooldown_default_seconds == 90
