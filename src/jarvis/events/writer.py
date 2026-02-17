"""Event emission helpers."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, cast

from jarvis.events.models import EventInput
from jarvis.ids import new_id
from jarvis.memory.service import MemoryService

SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "password",
    "api_key",
    "authorization",
    "phone",
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else _redact_value(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], _redact_value(payload))


def emit_event(conn: sqlite3.Connection, event: EventInput) -> str:
    event_id = new_id("evt")
    conn.execute(
        """
        INSERT INTO events(
          id, trace_id, span_id, parent_span_id, thread_id,
          event_type, component, actor_type, actor_id,
          payload_json, payload_redacted_json, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            event_id,
            event.trace_id,
            event.span_id,
            event.parent_span_id,
            event.thread_id,
            event.event_type,
            event.component,
            event.actor_type,
            event.actor_id,
            event.payload_json,
            event.payload_redacted_json,
            now_iso(),
        ),
    )

    try:
        redacted_payload = json.loads(event.payload_redacted_json)
    except json.JSONDecodeError:
        redacted_payload = {}
    text_value = redacted_payload.get("text")
    if isinstance(text_value, str):
        conn.execute(
            (
                "INSERT OR REPLACE INTO event_text("
                "event_id, thread_id, redacted_text, created_at"
                ") VALUES(?,?,?,?)"
            ),
            (event_id, event.thread_id, text_value, now_iso()),
        )
        conn.execute(
            (
                "INSERT INTO event_fts(event_id, thread_id, redacted_text) "
                "VALUES(?,?,?)"
            ),
            (event_id, event.thread_id, text_value),
        )
        memory = MemoryService()
        vector = memory.embed_text(text_value)
        memory.upsert_event_vector(conn, event_id, event.thread_id, vector)
    return event_id
