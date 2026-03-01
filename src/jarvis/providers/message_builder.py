"""OpenAI-format conversation message builders.

These helpers ensure that assistant messages include the ``tool_calls`` array
and that tool results are delivered as ``role: "tool"`` messages with matching
``tool_call_id`` values.  OSS models fine-tuned on the OpenAI standard require
this format; frontier models accept it without issue.
"""

import json
from typing import Any

from jarvis.ids import new_id


def build_assistant_message(text: str, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Return an assistant message dict, optionally including a tool_calls array.

    Args:
        text: The assistant's text content (may be empty when only tool calls
              were produced).
        tool_calls: Normalised tool call dicts, each containing at minimum
                    ``id``, ``name``, and ``arguments`` keys.

    Returns:
        A message dict suitable for appending to the conversation.
    """
    msg: dict[str, Any] = {"role": "assistant", "content": text or ""}
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc.get("arguments") or {}),
                },
            }
            for tc in tool_calls
        ]
    return msg


def build_tool_result_message(tool_call_id: str, content: str) -> dict[str, Any]:
    """Return a ``role: "tool"`` message for the given tool call result.

    Args:
        tool_call_id: The ID of the assistant tool_call this result answers.
        content: Serialised result payload (JSON string).

    Returns:
        A message dict with ``role="tool"``, ``tool_call_id``, and ``content``.
    """
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def ensure_tool_ids(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of *tool_calls* where every entry has an ``id`` field.

    When the model omits ``id`` values (common for some OSS checkpoints) a
    synthetic ``spn_<uuid>`` ID is injected so that tool-result pairing works
    correctly in subsequent turns.
    """
    result: list[dict[str, Any]] = []
    for tc in tool_calls:
        if tc.get("id"):
            result.append(tc)
        else:
            result.append({**tc, "id": new_id("spn")})
    return result


def inject_synthetic_errors_for_orphaned_calls(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Inject synthetic ``role: "tool"`` error messages for unacknowledged tool calls.

    An OSS model that sees an assistant message with ``tool_calls`` but no
    matching ``role: "tool"`` response will often loop or hallucinate.  This
    function performs a two-pass scan: first collecting all tool-call IDs from
    assistant messages, then collecting all acknowledged IDs from tool messages.
    Any orphaned IDs receive a synthetic error result appended after the
    existing messages.

    When no orphaned calls are found the original list is returned unchanged.
    """
    expected_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls", []):
                tc_id = tc.get("id")
                if tc_id:
                    expected_ids.add(tc_id)

    acknowledged_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id")
            if tc_id:
                acknowledged_ids.add(tc_id)

    orphaned = expected_ids - acknowledged_ids
    if not orphaned:
        return messages

    injected = list(messages)
    for orphan_id in sorted(orphaned):  # sorted for determinism
        injected.append(
            {
                "role": "tool",
                "tool_call_id": orphan_id,
                "content": json.dumps({"error": "tool call did not complete"}),
            }
        )
    return injected
