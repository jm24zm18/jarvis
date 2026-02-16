"""Web search tool with SearXNG primary and DuckDuckGo fallback."""

from typing import Any

import httpx

from jarvis.config import get_settings


def _result_item(title: str, url: str, content: str) -> dict[str, str]:
    return {"title": title.strip(), "url": url.strip(), "content": content.strip()}


def _error_hint_from_status(status_code: int) -> str:
    if status_code in {401, 403}:
        return (
            " SearXNG rejected the request. "
            "Set SEARXNG_API_KEY/SEARXNG_API_KEY_HEADER if your instance requires auth."
        )
    return ""


async def _http_get_json(
    url: str,
    *,
    params: dict[str, str | int],
    headers: dict[str, str],
    timeout_s: int,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("response is not a JSON object")
    return payload


async def _search_searxng(
    query: str,
    limit: int,
    categories: str,
) -> tuple[list[dict[str, str]], str | None]:
    settings = get_settings()
    base_url = settings.searxng_base_url.rstrip("/")
    header_name = settings.searxng_api_key_header.strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": settings.web_search_user_agent.strip() or "Jarvis/1.0",
    }
    api_key = settings.searxng_api_key.strip()
    if api_key and header_name:
        headers[header_name] = api_key
    params: dict[str, str | int] = {"q": query, "format": "json", "categories": categories}
    try:
        body = await _http_get_json(
            f"{base_url}/search",
            params=params,
            headers=headers,
            timeout_s=10,
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        err = f"search request failed ({status_code}): {exc}{_error_hint_from_status(status_code)}"
        return [], err
    except httpx.HTTPError as exc:
        return [], f"search request failed: {exc}"
    except Exception as exc:
        return [], f"unexpected search error: {exc}"

    raw_results = body.get("results", [])
    if not isinstance(raw_results, list):
        return [], "unexpected response format from SearXNG"

    results: list[dict[str, str]] = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        results.append(
            _result_item(
                str(item.get("title", "")),
                str(item.get("url", "")),
                str(item.get("content", "")),
            )
        )
    return results, None


async def _search_duckduckgo(query: str, limit: int) -> tuple[list[dict[str, str]], str | None]:
    settings = get_settings()
    headers = {
        "Accept": "application/json",
        "User-Agent": settings.web_search_user_agent.strip() or "Jarvis/1.0",
    }
    params: dict[str, str | int] = {
        "q": query,
        "format": "json",
        "no_redirect": 1,
        "no_html": 1,
        "skip_disambig": 1,
    }
    try:
        body = await _http_get_json(
            "https://api.duckduckgo.com/",
            params=params,
            headers=headers,
            timeout_s=10,
        )
    except httpx.HTTPStatusError as exc:
        return [], f"fallback search failed ({exc.response.status_code}): {exc}"
    except httpx.HTTPError as exc:
        return [], f"fallback search failed: {exc}"
    except Exception as exc:
        return [], f"unexpected fallback search error: {exc}"

    results: list[dict[str, str]] = []

    abstract_text = str(body.get("AbstractText", "")).strip()
    abstract_url = str(body.get("AbstractURL", "")).strip()
    heading = str(body.get("Heading", "")).strip() or query
    if abstract_text or abstract_url:
        results.append(_result_item(heading, abstract_url, abstract_text))

    related = body.get("RelatedTopics", [])
    if isinstance(related, list):
        for topic in related:
            if len(results) >= limit:
                break
            if isinstance(topic, dict):
                nested = topic.get("Topics")
                if isinstance(nested, list):
                    for subtopic in nested:
                        if len(results) >= limit:
                            break
                        if not isinstance(subtopic, dict):
                            continue
                        text = str(subtopic.get("Text", "")).strip()
                        url = str(subtopic.get("FirstURL", "")).strip()
                        if text or url:
                            title = text.split(" - ", 1)[0] if text else query
                            results.append(_result_item(title, url, text))
                    continue
                text = str(topic.get("Text", "")).strip()
                url = str(topic.get("FirstURL", "")).strip()
                if text or url:
                    title = text.split(" - ", 1)[0] if text else query
                    results.append(_result_item(title, url, text))

    return results[:limit], None


async def web_search(args: dict[str, Any]) -> dict[str, Any]:
    """Query SearXNG and fallback to DuckDuckGo on failure."""
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"error": "query is required", "results": []}
    normalized_query = query.strip()

    max_results = args.get("max_results", 5)
    try:
        limit = max(1, min(int(max_results), 20))
    except (TypeError, ValueError):
        limit = 5

    categories = args.get("categories", "general")
    if not isinstance(categories, str) or not categories.strip():
        categories = "general"

    searx_results, searx_error = await _search_searxng(normalized_query, limit, categories)
    if searx_results:
        return {"query": normalized_query, "source": "searxng", "results": searx_results}

    fallback_results, fallback_error = await _search_duckduckgo(normalized_query, limit)
    if fallback_results:
        payload: dict[str, Any] = {
            "query": normalized_query,
            "source": "duckduckgo",
            "results": fallback_results,
        }
        if searx_error:
            payload["warning"] = searx_error
        return payload

    if searx_error and fallback_error:
        return {
            "error": f"{searx_error}; fallback failed: {fallback_error}",
            "results": [],
        }
    if searx_error:
        return {"error": searx_error, "results": []}
    if fallback_error:
        return {"error": fallback_error, "results": []}
    return {"error": "no search results", "results": []}
