"""SGLang provider adapter using OpenAI-compatible chat completions API."""

import json
from typing import Any

import httpx

from jarvis.config import get_settings
from jarvis.providers.base import ModelResponse


class SGLangProvider:
    def __init__(
        self,
        model: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._transport = transport

    @staticmethod
    def _coerce_text(value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            chunks: list[str] = []
            for item in value:
                if isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            return "".join(chunks)
        return ""

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        return base_url.rstrip("/")

    @staticmethod
    def _to_tools(tools: list[dict[str, object]] | None) -> list[dict[str, object]] | None:
        if not tools:
            return None
        normalized: list[dict[str, object]] = []
        for tool in tools:
            name = tool.get("name")
            if not isinstance(name, str) or not name:
                continue
            description = tool.get("description")
            params = tool.get("parameters")
            function: dict[str, object] = {
                "name": name,
                "parameters": (
                    params
                    if isinstance(params, dict)
                    else {"type": "object", "properties": {}}
                ),
            }
            if isinstance(description, str) and description:
                function["description"] = description
            normalized.append({"type": "function", "function": function})
        if not normalized:
            return None
        return normalized

    @staticmethod
    def _parse_response(payload: dict[str, Any]) -> ModelResponse:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("sglang response missing choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise RuntimeError("sglang response choice malformed")
        message = first.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("sglang response message missing")
        content = SGLangProvider._coerce_text(message.get("content"))
        reasoning = SGLangProvider._coerce_text(message.get("reasoning_content"))
        tool_calls_raw = message.get("tool_calls", [])
        tool_calls: list[dict[str, Any]] = []
        if isinstance(tool_calls_raw, list):
            for call in tool_calls_raw:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function")
                if not isinstance(fn, dict):
                    continue
                name = fn.get("name")
                arguments = fn.get("arguments", {})
                parsed_arguments: dict[str, Any] = {}
                if isinstance(arguments, str):
                    try:
                        decoded = json.loads(arguments)
                        if isinstance(decoded, dict):
                            parsed_arguments = decoded
                    except json.JSONDecodeError:
                        parsed_arguments = {}
                elif isinstance(arguments, dict):
                    parsed_arguments = arguments
                if isinstance(name, str) and name:
                    tool_calls.append({"name": name, "arguments": parsed_arguments})
        return ModelResponse(text=content, tool_calls=tool_calls, reasoning_text=reasoning)

    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ModelResponse:
        settings = get_settings()
        base_url = self._normalize_base_url(settings.sglang_base_url)
        body: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "separate_reasoning": True,
        }
        normalized_tools = self._to_tools(tools)
        if normalized_tools is not None:
            body["tools"] = normalized_tools
        endpoint = f"{base_url}/chat/completions"
        timeout_seconds = max(10, int(settings.sglang_timeout_seconds))
        async with httpx.AsyncClient(timeout=timeout_seconds, transport=self._transport) as client:
            response = await client.post(endpoint, json=body)
            response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("sglang response is not an object")
        return self._parse_response(payload)

    async def health_check(self) -> bool:
        settings = get_settings()
        base_url = self._normalize_base_url(settings.sglang_base_url)
        endpoint = f"{base_url}/models"
        try:
            async with httpx.AsyncClient(timeout=10, transport=self._transport) as client:
                response = await client.get(endpoint)
            return response.status_code < 400
        except Exception:
            return False
