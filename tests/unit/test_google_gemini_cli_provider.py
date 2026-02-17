import json
import time
from collections import deque

import httpx
import pytest

from jarvis.providers.google_gemini_cli import GeminiCodeAssistProvider


@pytest.fixture(autouse=True)
def _reset_quota_state() -> None:
    GeminiCodeAssistProvider._quota_block_until_monotonic = 0.0
    GeminiCodeAssistProvider._quota_block_reason = ""
    GeminiCodeAssistProvider._request_timestamps_monotonic = deque()
    GeminiCodeAssistProvider._daily_count_utc = 0
    GeminiCodeAssistProvider._daily_count_date_utc = ""
    GeminiCodeAssistProvider._last_refresh_attempt_at_utc = ""
    GeminiCodeAssistProvider._last_refresh_status_global = ""


def test_extract_event_candidates_handles_nested_and_direct() -> None:
    payload = {
        "response": {
            "candidates": [
                {"content": {"parts": [{"text": "one"}]}}
            ]
        },
        "candidates": [
            {"content": {"parts": [{"text": "two"}]}}
        ],
    }
    candidates = GeminiCodeAssistProvider._extract_event_candidates(payload)
    assert len(candidates) == 2


@pytest.mark.asyncio
async def test_generate_streams_text_and_tool_calls(tmp_path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "tok",
                "refresh_token": "refresh",
                "expires_at_ms": 9_999_999_999_999,
                "cloudaicompanion_project": "cap-proj",
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":streamGenerateContent"):
            body = request.content.decode("utf-8")
            assert '"project": "cap-proj"' in body
            assert '"model": "gemini-test"' in body
            data = "\n\n".join(
                [
                    (
                        "data: "
                        '{"response":{"candidates":[{"content":{"parts":['
                        '{"thought":true,"text":"plan first "},{"text":"hello "}]}}]}}'
                    ),
                    (
                        "data: "
                        '{"candidates":[{"content":{"parts":[{"text":"world"},'
                        '{"functionCall":{"name":"lookup","args":{"q":"x"}}}]}}]}'
                    ),
                    "data: [DONE]",
                    "",
                ]
            )
            return httpx.Response(200, text=data)
        return httpx.Response(404)

    provider = GeminiCodeAssistProvider(
        "gemini-test",
        token_path=str(token_path),
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate(
        [{"role": "user", "content": "hi"}],
        tools=[{"name": "lookup"}],
    )
    assert result.text == "hello world"
    assert result.tool_calls == [{"name": "lookup", "arguments": {"q": "x"}}]
    assert result.reasoning_text == "plan first "
    assert result.reasoning_parts == [{"text": "plan first "}]


@pytest.mark.asyncio
async def test_generate_bootstraps_missing_project(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "tok",
                "refresh_token": "refresh",
                "expires_at_ms": 9_999_999_999_999,
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":loadCodeAssist"):
            assert request.headers["user-agent"].startswith("GeminiCLI/0.28.2/gemini-test (")
            assert request.headers["x-goog-api-client"] == "gl-node/22.22.0"
            assert request.headers["accept"] == "application/json"
            return httpx.Response(200, json={"cloudaicompanionProject": "cap-proj"})
        if request.url.path.endswith(":streamGenerateContent"):
            assert request.headers["user-agent"].startswith("GeminiCLI/0.28.2/gemini-test (")
            assert request.headers["x-goog-api-client"] == "gl-node/22.22.0"
            return httpx.Response(
                200,
                text='data: {"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}\n\n'
                "data: [DONE]\n\n",
            )
        return httpx.Response(404)

    monkeypatch.setattr(
        "jarvis.providers.google_gemini_cli._get_client_credentials",
        lambda: ("cid", "csecret"),
    )
    monkeypatch.setattr(
        "jarvis.providers.google_gemini_cli._detect_cli_version",
        lambda: "0.28.2",
    )
    monkeypatch.setattr(
        "jarvis.providers.google_gemini_cli._build_api_client_header",
        lambda: "gl-node/22.22.0",
    )

    provider = GeminiCodeAssistProvider(
        "gemini-test",
        token_path=str(token_path),
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate([{"role": "user", "content": "hi"}], tools=[])
    assert result.text == "ok"

    persisted = json.loads(token_path.read_text(encoding="utf-8"))
    assert persisted["cloudaicompanion_project"] == "cap-proj"


def test_plan_tier_defaults_match_documented_limits() -> None:
    pro = GeminiCodeAssistProvider("gemini-test", quota_plan_tier="pro")
    free = GeminiCodeAssistProvider("gemini-test", quota_plan_tier="unknown")
    assert pro.requests_per_minute_limit == 120
    assert pro.requests_per_day_limit == 1500
    assert free.requests_per_minute_limit == 60
    assert free.requests_per_day_limit == 1000


def test_local_quota_limit_enforced_by_tier() -> None:
    provider = GeminiCodeAssistProvider("gemini-test", quota_plan_tier="pro")
    now = time.monotonic()
    GeminiCodeAssistProvider._request_timestamps_monotonic = deque([now - 1] * 120)
    with pytest.raises(RuntimeError, match="120/min"):
        provider._consume_local_quota()


def test_quota_block_fallback_uses_short_default_cooldown() -> None:
    provider = GeminiCodeAssistProvider(
        "gemini-test",
        quota_cooldown_default_seconds=75,
    )
    provider._maybe_set_quota_block("quota exceeded", 429)
    status = GeminiCodeAssistProvider.quota_status()
    assert status["blocked"] is True
    assert 1 <= int(status["seconds_remaining"]) <= 75


def test_classify_validation_required_error() -> None:
    provider = GeminiCodeAssistProvider("gemini-test")
    detail = json.dumps(
        {
            "error": {
                "code": 403,
                "message": "Account validation required",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "domain": "cloudcode-pa.googleapis.com",
                        "reason": "VALIDATION_REQUIRED",
                        "metadata": {"validation_link": "https://example.test/verify"},
                    }
                ],
            }
        }
    )
    classified = provider._classify_google_api_error(403, detail)
    assert classified["kind"] == "validation_required"
    assert classified["validation_link"] == "https://example.test/verify"


def test_classify_retryable_quota_with_retry_info() -> None:
    provider = GeminiCodeAssistProvider("gemini-test")
    detail = json.dumps(
        {
            "error": {
                "code": 429,
                "message": "Rate limit exceeded",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "domain": "cloudcode-pa.googleapis.com",
                        "reason": "RATE_LIMIT_EXCEEDED",
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "12s",
                    },
                ],
            }
        }
    )
    classified = provider._classify_google_api_error(429, detail)
    assert classified["kind"] == "quota_retryable"
    assert classified["retry_seconds"] == 12


def test_classify_terminal_quota_daily() -> None:
    provider = GeminiCodeAssistProvider("gemini-test")
    detail = json.dumps(
        {
            "error": {
                "code": 429,
                "message": "Quota exhausted",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": "GenerateRequestsPerDay"}],
                    }
                ],
            }
        }
    )
    classified = provider._classify_google_api_error(429, detail)
    assert classified["kind"] == "quota_terminal"


def test_classify_model_not_found_and_invalid_argument() -> None:
    provider = GeminiCodeAssistProvider("gemini-test")
    missing = provider._classify_google_api_error(
        404,
        '{"error":{"code":404,"message":"not found"}}',
    )
    invalid = provider._classify_google_api_error(
        400,
        '{"error":{"code":400,"message":"Request contains an invalid argument"}}',
    )
    assert missing["kind"] == "model_not_found"
    assert invalid["kind"] == "invalid_argument"


def test_classify_timeout_error() -> None:
    provider = GeminiCodeAssistProvider("gemini-test")
    classified = provider._classify_google_api_error(500, "request timed out upstream")
    assert classified["kind"] == "timeout"
