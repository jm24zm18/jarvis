from typing import Any

import httpx
import pytest

from jarvis.tools import web_search as web_search_module


@pytest.mark.asyncio
async def test_web_search_uses_searxng_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_json(
        url: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
        timeout_s: int,
    ) -> dict[str, Any]:
        assert url.endswith("/search")
        assert params["q"] == "meaning of life"
        assert headers["Accept"] == "application/json"
        assert timeout_s == 10
        return {
            "results": [
                {
                    "title": "Stanford Encyclopedia",
                    "url": "https://plato.stanford.edu/",
                    "content": "Survey",
                }
            ]
        }

    monkeypatch.setattr(web_search_module, "_http_get_json", fake_get_json)

    result = await web_search_module.web_search({"query": "meaning of life", "max_results": 3})
    assert result["source"] == "searxng"
    assert len(result["results"]) == 1
    assert "warning" not in result


@pytest.mark.asyncio
async def test_web_search_falls_back_to_duckduckgo_on_searxng_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_json(
        url: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
        timeout_s: int,
    ) -> dict[str, Any]:
        del params, headers, timeout_s
        if url.endswith("/search"):
            request = httpx.Request("GET", "http://localhost:8080/search")
            response = httpx.Response(403, request=request)
            raise httpx.HTTPStatusError("Forbidden", request=request, response=response)
        return {
            "Heading": "Meaning of life",
            "AbstractText": "A broad philosophical question.",
            "AbstractURL": "https://duckduckgo.com/Meaning_of_life",
            "RelatedTopics": [],
        }

    monkeypatch.setattr(web_search_module, "_http_get_json", fake_get_json)

    result = await web_search_module.web_search({"query": "meaning of life", "max_results": 3})
    assert result["source"] == "duckduckgo"
    assert len(result["results"]) == 1
    assert "warning" in result
    assert "SEARXNG_API_KEY" in str(result["warning"])


@pytest.mark.asyncio
async def test_web_search_returns_combined_error_when_primary_and_fallback_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_json(
        url: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
        timeout_s: int,
    ) -> dict[str, Any]:
        del params, headers, timeout_s
        request = httpx.Request("GET", url)
        if url.endswith("/search"):
            response = httpx.Response(403, request=request)
            raise httpx.HTTPStatusError("Forbidden", request=request, response=response)
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError("Server error", request=request, response=response)

    monkeypatch.setattr(web_search_module, "_http_get_json", fake_get_json)

    result = await web_search_module.web_search({"query": "meaning of life", "max_results": 3})
    assert "error" in result
    assert result["results"] == []
    assert "fallback failed" in str(result["error"])
