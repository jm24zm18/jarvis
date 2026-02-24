"""Unit tests for src/jarvis/providers/message_builder.py."""

import json

from jarvis.providers.message_builder import (
    build_assistant_message,
    build_tool_result_message,
    ensure_tool_ids,
    inject_synthetic_errors_for_orphaned_calls,
)

# ---------------------------------------------------------------------------
# build_assistant_message
# ---------------------------------------------------------------------------


def test_build_assistant_message_no_tool_calls() -> None:
    msg = build_assistant_message("Hello!", [])
    assert msg["role"] == "assistant"
    assert msg["content"] == "Hello!"
    assert "tool_calls" not in msg


def test_build_assistant_message_empty_text_no_tool_calls() -> None:
    msg = build_assistant_message("", [])
    assert msg["content"] == ""
    assert "tool_calls" not in msg


def test_build_assistant_message_with_tool_calls() -> None:
    calls = [
        {"id": "spn_abc", "name": "search", "arguments": {"query": "hello"}},
        {"id": "spn_def", "name": "echo", "arguments": {}},
    ]
    msg = build_assistant_message("thinking...", calls)
    assert msg["role"] == "assistant"
    assert msg["content"] == "thinking..."
    assert "tool_calls" in msg
    tc = msg["tool_calls"]
    assert len(tc) == 2
    assert tc[0]["id"] == "spn_abc"
    assert tc[0]["type"] == "function"
    assert tc[0]["function"]["name"] == "search"
    assert json.loads(tc[0]["function"]["arguments"]) == {"query": "hello"}
    assert tc[1]["id"] == "spn_def"
    assert json.loads(tc[1]["function"]["arguments"]) == {}


def test_build_assistant_message_none_arguments_serialised_as_empty() -> None:
    calls = [{"id": "spn_x", "name": "noop", "arguments": None}]
    msg = build_assistant_message("", calls)
    tc = msg["tool_calls"]
    assert json.loads(tc[0]["function"]["arguments"]) == {}


# ---------------------------------------------------------------------------
# build_tool_result_message
# ---------------------------------------------------------------------------


def test_build_tool_result_message_format() -> None:
    msg = build_tool_result_message("spn_abc", '{"ok": true}')
    assert msg["role"] == "tool"
    assert msg["tool_call_id"] == "spn_abc"
    assert msg["content"] == '{"ok": true}'


def test_build_tool_result_message_empty_id() -> None:
    msg = build_tool_result_message("", "result")
    assert msg["tool_call_id"] == ""
    assert msg["content"] == "result"


# ---------------------------------------------------------------------------
# ensure_tool_ids
# ---------------------------------------------------------------------------


def test_ensure_tool_ids_preserves_existing() -> None:
    calls = [{"id": "existing_id", "name": "foo", "arguments": {}}]
    result = ensure_tool_ids(calls)
    assert result[0]["id"] == "existing_id"


def test_ensure_tool_ids_synthesises_missing() -> None:
    calls = [{"name": "bar", "arguments": {"x": 1}}]
    result = ensure_tool_ids(calls)
    assert "id" in result[0]
    assert result[0]["id"].startswith("spn_")
    assert result[0]["name"] == "bar"


def test_ensure_tool_ids_mixed() -> None:
    calls = [
        {"id": "abc", "name": "a", "arguments": {}},
        {"name": "b", "arguments": {}},
    ]
    result = ensure_tool_ids(calls)
    assert result[0]["id"] == "abc"
    assert result[1]["id"].startswith("spn_")


def test_ensure_tool_ids_returns_new_list() -> None:
    original = [{"name": "f", "arguments": {}}]
    result = ensure_tool_ids(original)
    assert result is not original


def test_ensure_tool_ids_empty_list() -> None:
    assert ensure_tool_ids([]) == []


# ---------------------------------------------------------------------------
# inject_synthetic_errors_for_orphaned_calls
# ---------------------------------------------------------------------------


def test_inject_no_op_when_all_paired() -> None:
    tc = {"id": "spn_1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [tc]},
        {"role": "tool", "tool_call_id": "spn_1", "content": '{"ok": true}'},
    ]
    result = inject_synthetic_errors_for_orphaned_calls(messages)
    assert result is messages  # unchanged, same object


def test_inject_synthetic_for_orphaned() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "spn_1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
                {"id": "spn_2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "spn_1", "content": "done"},
    ]
    result = inject_synthetic_errors_for_orphaned_calls(messages)
    assert len(result) == 3  # original 2 + 1 synthetic
    injected = result[2]
    assert injected["role"] == "tool"
    assert injected["tool_call_id"] == "spn_2"
    error_body = json.loads(injected["content"])
    assert "error" in error_body


def test_inject_no_assistant_tool_calls() -> None:
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = inject_synthetic_errors_for_orphaned_calls(messages)
    assert result is messages


def test_inject_empty_messages() -> None:
    result = inject_synthetic_errors_for_orphaned_calls([])
    assert result == []
