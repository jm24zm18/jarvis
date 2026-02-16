"""Session tool implementations."""

import json
import sqlite3
from typing import Any

from jarvis.db.queries import insert_message, now_iso
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id


def session_list(
    conn: sqlite3.Connection, agent_id: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[object] = []
    if status:
        filters.append("s.status=?")
        params.append(status)
    if agent_id:
        filters.append(
            "EXISTS ("
            "SELECT 1 FROM session_participants sp2 "
            "WHERE sp2.session_id=s.id AND sp2.actor_type='agent' AND sp2.actor_id=?"
            ")"
        )
        params.append(agent_id)
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = conn.execute(
        (
            "SELECT s.id AS session_id, s.status, s.updated_at, "
            "sp.actor_type, sp.actor_id, sp.role "
            "FROM sessions s "
            "LEFT JOIN session_participants sp ON sp.session_id=s.id "
            f"{where_sql} "
            "ORDER BY s.updated_at DESC"
        ),
        params,
    ).fetchall()
    by_session: dict[str, dict[str, Any]] = {}
    for row in rows:
        session_id = str(row["session_id"])
        item = by_session.setdefault(
            session_id,
            {
                "session_id": session_id,
                "status": str(row["status"]),
                "updated_at": str(row["updated_at"]),
                "participants": [],
            },
        )
        actor_type = row["actor_type"]
        actor_id = row["actor_id"]
        role = row["role"]
        if (
            isinstance(actor_type, str)
            and isinstance(actor_id, str)
            and isinstance(role, str)
            and actor_type
            and actor_id
            and role
        ):
            participants = item["participants"]
            if isinstance(participants, list):
                participants.append(
                    {"actor_type": actor_type, "actor_id": actor_id, "role": role}
                )
    return list(by_session.values())


def session_history(
    conn: sqlite3.Connection, session_id: str, limit: int = 200, before: str | None = None
) -> list[dict[str, str]]:
    capped = max(1, min(limit, 500))
    if before:
        rows = conn.execute(
            (
                "SELECT role, actor_id, content, created_at, event_id "
                "FROM v_session_timeline "
                "WHERE session_id=? AND created_at<? "
                "ORDER BY created_at DESC LIMIT ?"
            ),
            (session_id, before, capped),
        ).fetchall()
    else:
        rows = conn.execute(
            (
                "SELECT role, actor_id, content, created_at, event_id "
                "FROM v_session_timeline "
                "WHERE session_id=? ORDER BY created_at DESC LIMIT ?"
            ),
            (session_id, capped),
        ).fetchall()
    return [
        {
            "role": str(row["role"]) if row["role"] is not None else "",
            "actor_id": str(row["actor_id"]) if row["actor_id"] is not None else "",
            "content": str(row["content"]) if row["content"] is not None else "",
            "created_at": str(row["created_at"]) if row["created_at"] is not None else "",
            "event_id": str(row["event_id"]) if row["event_id"] is not None else "",
        }
        for row in rows
    ]


def session_send(
    conn: sqlite3.Connection,
    session_id: str,
    to_agent_id: str,
    message: str,
    trace_id: str,
    from_agent_id: str = "main",
) -> str:
    conn.execute(
        (
            "INSERT OR IGNORE INTO sessions("
            "id, kind, status, created_at, updated_at"
            ") VALUES(?,?,?,?,?)"
        ),
        (session_id, "thread", "open", now_iso(), now_iso()),
    )
    conn.execute(
        (
            "INSERT OR IGNORE INTO session_participants("
            "session_id, actor_type, actor_id, role"
            ") VALUES(?,?,?,?)"
        ),
        (session_id, "agent", from_agent_id, "main" if from_agent_id == "main" else "worker"),
    )
    conn.execute(
        (
            "INSERT OR IGNORE INTO session_participants("
            "session_id, actor_type, actor_id, role"
            ") VALUES(?,?,?,?)"
        ),
        (session_id, "agent", to_agent_id, "worker"),
    )
    conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now_iso(), session_id))
    _ = insert_message(
        conn,
        thread_id=session_id,
        role="agent",
        content=f"[{from_agent_id}->{to_agent_id}] {message}",
    )
    payload = {
        "session_id": session_id,
        "to_agent_id": to_agent_id,
        "from_agent_id": from_agent_id,
        "text": message,
    }
    _ = emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=session_id,
            event_type="agent.delegate",
            component="sessions",
            actor_type="agent",
            actor_id=from_agent_id,
            payload_json=json.dumps(
                {
                    "session_id": session_id,
                    "to_agent_id": to_agent_id,
                }
            ),
            payload_redacted_json=json.dumps(
                redact_payload(
                    {
                        "session_id": session_id,
                        "to_agent_id": to_agent_id,
                    }
                )
            ),
        ),
    )
    return emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=session_id,
            event_type="agent.message",
            component="sessions",
            actor_type="agent",
            actor_id=from_agent_id,
            payload_json=json.dumps(payload),
            payload_redacted_json=json.dumps(redact_payload(payload)),
        ),
    )
