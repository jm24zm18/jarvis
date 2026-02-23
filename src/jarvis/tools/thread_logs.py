"""Helpers for summarizing thread activity for new thread_logs tool."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

FEATURE_BUILD_PREFIX = "feature.build."


def _truncate(value: str | None, limit: int = 400) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit-3]}..."


def _payload_summary(payload_json: str | None) -> str:
    if not payload_json:
        return ""
    try:
        parsed = json.loads(payload_json)
    except Exception:
        return _truncate(payload_json, limit=400)
    if isinstance(parsed, dict):
        if reason := parsed.get("reason"):
            return _truncate(str(reason), limit=400)
        if summary := parsed.get("status"):
            return _truncate(str(summary), limit=400)
        if summary := parsed.get("summary"):
            return _truncate(str(summary), limit=400)
    if isinstance(parsed, str):
        return _truncate(parsed, limit=400)
    return _truncate(str(parsed), limit=400)


def summarize_thread_logs(
    conn: sqlite3.Connection,
    thread_id: str,
    *,
    max_messages: int = 25,
    max_events: int = 25,
    max_escalations: int = 5,
) -> dict[str, Any]:
    total_row = conn.execute(
        "SELECT COUNT(*) AS c FROM messages WHERE thread_id=?",
        (thread_id,),
    ).fetchone()
    message_count = int(total_row["c"]) if total_row is not None else 0

    message_rows = conn.execute(
        "SELECT id, role, content, created_at FROM messages "
        "WHERE thread_id=? ORDER BY created_at DESC LIMIT ?",
        (thread_id, max_messages),
    ).fetchall()
    messages = [
        {
            "id": str(row["id"]),
            "role": str(row["role"]),
            "content": _truncate(row["content"], limit=400),
            "created_at": str(row["created_at"]),
        }
        for row in message_rows
    ]

    event_rows = conn.execute(
        "SELECT id, event_type, component, actor_id, payload_json, created_at "
        "FROM events WHERE thread_id=? ORDER BY created_at DESC LIMIT ?",
        (thread_id, max_events),
    ).fetchall()
    events = [
        {
            "id": str(row["id"]),
            "event_type": str(row["event_type"]),
            "component": str(row["component"]),
            "actor_id": str(row["actor_id"]),
            "payload_summary": _payload_summary(row["payload_json"]),
            "created_at": str(row["created_at"]),
        }
        for row in event_rows
    ]

    feature_events = [row for row in events if row["event_type"].startswith(FEATURE_BUILD_PREFIX)]
    feature_build: dict[str, Any] | None = None
    if feature_events:
        feature_build = {
            "last_event": feature_events[0]["event_type"],
            "last_reason": feature_events[0]["payload_summary"],
            "event_count": len(feature_events),
        }

    escalation_rows = conn.execute(
        "SELECT id, status, reason, priority, channel_type, created_at "
        "FROM human_escalations WHERE thread_id=? ORDER BY created_at DESC LIMIT ?",
        (thread_id, max_escalations),
    ).fetchall()
    escalations = [
        {
            "id": str(row["id"]),
            "status": str(row["status"]),
            "reason": _truncate(row["reason"], limit=200),
            "priority": str(row["priority"]),
            "channel_type": str(row["channel_type"]),
            "created_at": str(row["created_at"]),
        }
        for row in escalation_rows
    ]
    escalation_counts: dict[str, int] = {}
    for row in escalation_rows:
        status = str(row["status"])
        escalation_counts[status] = escalation_counts.get(status, 0) + 1

    return {
        "thread_id": thread_id,
        "message_count": message_count,
        "recent_messages": messages,
        "recent_events": events,
        "feature_build": feature_build,
        "human_escalations": escalations,
        "human_escalation_counts": escalation_counts,
    }
