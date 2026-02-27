import json

import httpx
import pytest

from jarvis.config import get_settings
from jarvis.providers.compat import ProviderCompat
from jarvis.providers.factory import build_fallback_provider, build_primary_provider
from jarvis.providers.lmstudio import LMStudioProvider
from jarvis.providers.openrouter import OpenRouterProvider
from jarvis.providers.sglang import SGLangProvider


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
                                        "id": "call_abc123",
                                        "function": {
                                            "name": "lookup",
                                            "arguments": '{"term":"abc"}',
                                        },
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
    assert response.tool_calls == [
        {"id": "call_abc123", "name": "lookup", "arguments": {"term": "abc"}}
    ]
    assert healthy is True


@pytest.mark.asyncio
async def test_sglang_id_preserved_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """_parse_response preserves the `id` field from raw tool_calls."""
    monkeypatch.setenv("SGLANG_BASE_URL", "http://sglang.local/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_xyz",
                                    "function": {
                                        "name": "search",
                                        "arguments": '{"q":"test"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    provider = SGLangProvider("model", transport=httpx.MockTransport(handler))
    response = await provider.generate([{"role": "user", "content": "go"}])
    assert response.tool_calls[0]["id"] == "call_xyz"


@pytest.mark.asyncio
async def test_sglang_id_absent_when_not_in_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the model omits `id`, the parsed tool call dict also omits it."""
    monkeypatch.setenv("SGLANG_BASE_URL", "http://sglang.local/v1")

    def handler(request: httpx.Request) -> httpx.Response:
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
                                        "name": "noop",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    provider = SGLangProvider("model", transport=httpx.MockTransport(handler))
    response = await provider.generate([{"role": "user", "content": "go"}])
    assert "id" not in response.tool_calls[0]


@pytest.mark.asyncio
async def test_sglang_compat_parallel_tool_calls_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """With parallel_tool_calls=False, the request body includes the flag."""
    monkeypatch.setenv("SGLANG_BASE_URL", "http://sglang.local/v1")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok", "tool_calls": []}}]},
        )

    compat = ProviderCompat(tool_choice="auto", parallel_tool_calls=False)
    provider = SGLangProvider("model", transport=httpx.MockTransport(handler), compat=compat)
    await provider.generate(
        [{"role": "user", "content": "go"}],
        tools=[{"name": "f", "description": "d"}],
    )
    body = captured["body"]
    assert body.get("parallel_tool_calls") is False  # type: ignore[union-attr]
    assert body.get("tool_choice") == "auto"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_openrouter_id_preserved_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """_parse_response preserves the `id` field from OpenRouter tool_calls."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://or.local/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_or_99",
                                    "function": {
                                        "name": "do_thing",
                                        "arguments": '{"a":1}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    provider = OpenRouterProvider("model", transport=httpx.MockTransport(handler))
    response = await provider.generate([{"role": "user", "content": "go"}])
    assert response.tool_calls[0]["id"] == "call_or_99"


@pytest.mark.asyncio
async def test_openrouter_compat_tool_choice_in_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """With compat, tool_choice appears in the request body."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://or.local/v1")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "done", "tool_calls": []}}]},
        )

    compat = ProviderCompat(tool_choice="auto", parallel_tool_calls=True)
    provider = OpenRouterProvider("model", transport=httpx.MockTransport(handler), compat=compat)
    await provider.generate(
        [{"role": "user", "content": "go"}],
        tools=[{"name": "f", "description": "d"}],
    )
    body = captured["body"]
    assert body.get("tool_choice") == "auto"  # type: ignore[union-attr]
    assert body.get("parallel_tool_calls") is True  # type: ignore[union-attr]


def test_provider_factory_builds_openrouter_as_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIMARY_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        primary = build_primary_provider(settings)
        fallback = build_fallback_provider(settings)
    finally:
        get_settings.cache_clear()
    assert isinstance(primary, OpenRouterProvider)
    assert isinstance(fallback, SGLangProvider)


def test_provider_factory_passes_openrouter_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIMARY_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-3-opus")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        primary = build_primary_provider(settings)
    finally:
        get_settings.cache_clear()
    assert isinstance(primary, OpenRouterProvider)
    assert primary.model == "anthropic/claude-3-opus"


def test_provider_factory_supports_switching_primary_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIMARY_PROVIDER", "sglang")
    monkeypatch.setenv("SGLANG_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        primary = build_primary_provider(settings)
        fallback = build_fallback_provider(settings)
    finally:
        get_settings.cache_clear()
    assert isinstance(primary, SGLangProvider)
    assert isinstance(fallback, OpenRouterProvider)


def test_provider_factory_supports_lmstudio_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIMARY_PROVIDER", "lmstudio")
    monkeypatch.setenv("LMSTUDIO_MODEL", "qwen2.5-coder-7b-instruct")
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
    monkeypatch.setenv("SGLANG_MODEL", "openai/gpt-oss-120b")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        primary = build_primary_provider(settings)
        fallback = build_fallback_provider(settings)
    finally:
        get_settings.cache_clear()
    assert isinstance(primary, LMStudioProvider)
    assert isinstance(fallback, OpenRouterProvider)


def test_provider_factory_supports_explicit_fallback_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIMARY_PROVIDER", "openrouter")
    monkeypatch.setenv("FALLBACK_PROVIDER", "lmstudio")
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
    monkeypatch.setenv("LMSTUDIO_MODEL", "qwen2.5-coder-7b-instruct")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        fallback = build_fallback_provider(settings)
    finally:
        get_settings.cache_clear()
    assert isinstance(fallback, LMStudioProvider)
