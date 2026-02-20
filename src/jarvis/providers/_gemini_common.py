"""Shared helpers for Gemini providers (REST API request building + response parsing)."""

from __future__ import annotations

from typing import Any

from jarvis.providers.base import ModelResponse


def to_contents(messages: list[dict[str, str]]) -> list[dict[str, object]]:
    contents: list[dict[str, object]] = []
    for msg in messages:
        role = msg.get("role", "user")
        text = msg.get("content", "")
        gemini_role = "model" if role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": text}]})
    return contents


def to_tools(tools: list[dict[str, object]] | None) -> list[dict[str, object]] | None:
    if not tools:
        return None
    declarations: list[dict[str, object]] = []
    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            continue
        description = tool.get("description")
        decl: dict[str, object] = {"name": name}
        if isinstance(description, str) and description:
            decl["description"] = description
        params = tool.get("parameters")
        decl["parameters"] = (
            params
            if isinstance(params, dict)
            else {"type": "object", "properties": {}}
        )
        declarations.append(decl)
    if not declarations:
        return None
    return [{"function_declarations": declarations}]


def parse_candidate_parts(
    parts: Any,
) -> tuple[list[str], list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    thought_text_parts: list[str] = []
    thought_parts: list[dict[str, Any]] = []
    if not isinstance(parts, list):
        return text_parts, tool_calls, thought_text_parts, thought_parts
    for part in parts:
        if not isinstance(part, dict):
            continue
        if bool(part.get("thought")):
            thought_text = part.get("text")
            if isinstance(thought_text, str) and thought_text:
                thought_text_parts.append(thought_text)
            thought_part_payload: dict[str, Any] = {}
            if isinstance(thought_text, str) and thought_text:
                thought_part_payload["text"] = thought_text
            thought_signature = part.get("thoughtSignature")
            if isinstance(thought_signature, str) and thought_signature:
                thought_part_payload["thought_signature"] = thought_signature
            if thought_part_payload:
                thought_parts.append(thought_part_payload)
            continue
        text = part.get("text")
        if isinstance(text, str) and text:
            text_parts.append(text)
        function_call = part.get("functionCall")
        if isinstance(function_call, dict):
            name = function_call.get("name")
            args = function_call.get("args", {})
            if isinstance(name, str) and name:
                tool_calls.append(
                    {
                        "name": name,
                        "arguments": args if isinstance(args, dict) else {},
                    }
                )
    return text_parts, tool_calls, thought_text_parts, thought_parts


def parse_candidates(candidates: Any) -> ModelResponse:
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("gemini response missing candidates")
    first = candidates[0]
    if not isinstance(first, dict):
        raise RuntimeError("gemini response candidate malformed")
    content = first.get("content")
    if not isinstance(content, dict):
        raise RuntimeError("gemini response content missing")
    parts = content.get("parts", [])
    text_parts, tool_calls, thought_text_parts, thought_parts = parse_candidate_parts(parts)
    return ModelResponse(
        text="\n".join(text_parts),
        tool_calls=tool_calls,
        reasoning_text="\n".join(thought_text_parts),
        reasoning_parts=thought_parts,
    )


def parse_response(payload: dict[str, Any]) -> ModelResponse:
    return parse_candidates(payload.get("candidates"))


def build_request_body(
    messages: list[dict[str, str]],
    tools: list[dict[str, object]] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict[str, object]:
    system_parts: list[str] = []
    non_system_messages: list[dict[str, str]] = []
    for item in messages:
        role = str(item.get("role", "user")).strip().lower()
        content = str(item.get("content", ""))
        if role == "system":
            if content.strip():
                system_parts.append(content)
            continue
        non_system_messages.append({"role": role, "content": content})
    body: dict[str, object] = {
        "contents": to_contents(non_system_messages),
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {
                "thinkingBudget": 8192,
                "includeThoughts": True,
            },
        },
    }
    if system_parts:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    gemini_tools = to_tools(tools)
    if gemini_tools is not None:
        body["tools"] = gemini_tools
    return body
