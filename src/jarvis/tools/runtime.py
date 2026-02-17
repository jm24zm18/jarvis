"""Tool runtime with policy/audit integration."""

import json
import sqlite3
from typing import Any

from jarvis.errors import PolicyError
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.policy.engine import decision
from jarvis.tools.registry import ToolRegistry


class ToolRuntime:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute(
        self,
        conn: sqlite3.Connection,
        tool_name: str,
        arguments: dict[str, Any],
        caller_id: str,
        trace_id: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        span_id = new_id("spn")

        def _emit_terminal_error(error_kind: str, message: str, reason: str | None = None) -> None:
            payload: dict[str, Any] = {
                "tool": tool_name,
                "error": {
                    "kind": error_kind,
                    "message": message,
                },
            }
            if reason:
                payload["error"]["reason"] = reason
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=span_id,
                    thread_id=thread_id,
                    event_type="tool.call.end",
                    component="tools.runtime",
                    actor_type="agent",
                    actor_id=caller_id,
                    payload_json=json.dumps(payload),
                    payload_redacted_json=json.dumps(redact_payload(payload)),
                ),
            )

        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                thread_id=thread_id,
                event_type="tool.call.start",
                component="tools.runtime",
                actor_type="agent",
                actor_id=caller_id,
                payload_json=json.dumps({"tool": tool_name, "arguments": arguments}),
                payload_redacted_json=json.dumps(
                    redact_payload({"tool": tool_name, "arguments": arguments})
                ),
            ),
        )

        tool = self.registry.get(tool_name)
        if tool is None:
            reason = "R3: unknown tool"
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=span_id,
                    thread_id=thread_id,
                    event_type="policy.decision",
                    component="policy",
                    actor_type="agent",
                    actor_id=caller_id,
                    payload_json=json.dumps(
                        {"tool": tool_name, "allowed": False, "reason": reason}
                    ),
                    payload_redacted_json=json.dumps(
                        redact_payload({"tool": tool_name, "allowed": False, "reason": reason})
                    ),
                ),
            )
            _emit_terminal_error(
                "unknown_tool",
                "tool denied by policy: R3: unknown tool",
                reason=reason,
            )
            raise PolicyError("tool denied by policy: R3: unknown tool")

        allowed, reason = decision(conn, caller_id, tool_name)
        if not allowed:
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=span_id,
                    thread_id=thread_id,
                    event_type="policy.decision",
                    component="policy",
                    actor_type="agent",
                    actor_id=caller_id,
                    payload_json=json.dumps(
                        {"tool": tool_name, "allowed": False, "reason": reason}
                    ),
                    payload_redacted_json=json.dumps(
                        redact_payload({"tool": tool_name, "allowed": False, "reason": reason})
                    ),
                ),
            )
            _emit_terminal_error(
                "policy_deny",
                f"tool denied by policy: {reason}",
                reason=reason,
            )
            raise PolicyError(f"tool denied by policy: {reason}")

        try:
            result = await tool.handler(arguments)
        except Exception as exc:
            _emit_terminal_error("runtime_exception", str(exc))
            raise

        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=span_id,
                thread_id=thread_id,
                event_type="tool.call.end",
                component="tools.runtime",
                actor_type="agent",
                actor_id=caller_id,
                payload_json=json.dumps({"tool": tool_name, "result": result}),
                payload_redacted_json=json.dumps(
                    redact_payload({"tool": tool_name, "result": result})
                ),
            ),
        )
        return result
