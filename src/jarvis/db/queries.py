"""Core query helpers used by routes/tasks."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException

from jarvis.agents.loader import get_all_agent_ids
from jarvis.ids import new_id


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def verify_thread_owner(conn: sqlite3.Connection, thread_id: str, user_id: str) -> None:
    row = conn.execute("SELECT user_id FROM threads WHERE id=? LIMIT 1", (thread_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="thread not found")
    if str(row["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="forbidden")


def ensure_system_state(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO system_state(
          id, lockdown, restarting, updated_at, readyz_fail_streak,
          rollback_count, last_rollback_at, lockdown_reason,
          host_exec_fail_streak, last_host_exec_fail_at
        )
        VALUES ('singleton', 0, 0, ?, 0, 0, NULL, '', 0, NULL)
        """,
        (now_iso(),),
    )


def get_system_state(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        "SELECT lockdown, restarting FROM system_state WHERE id='singleton'"
    ).fetchone()
    if row is None:
        ensure_system_state(conn)
        row = conn.execute(
            "SELECT lockdown, restarting FROM system_state WHERE id='singleton'"
        ).fetchone()
    assert row is not None
    return {
        "lockdown": int(row["lockdown"]),
        "restarting": int(row["restarting"]),
    }


def clear_stale_restarting_flag(conn: sqlite3.Connection) -> bool:
    ensure_system_state(conn)
    row = conn.execute(
        "SELECT restarting FROM system_state WHERE id='singleton'"
    ).fetchone()
    if row is None:
        return False
    restarting = int(row["restarting"])
    if restarting == 0:
        return False
    conn.execute(
        "UPDATE system_state SET restarting=0, updated_at=? WHERE id='singleton'",
        (now_iso(),),
    )
    return True


def record_readyz_result(conn: sqlite3.Connection, ok: bool, threshold: int = 3) -> bool:
    ensure_system_state(conn)
    if ok:
        row = conn.execute(
            "SELECT lockdown, lockdown_reason FROM system_state WHERE id='singleton'"
        ).fetchone()
        lockdown = int(row["lockdown"]) if row is not None else 0
        reason = str(row["lockdown_reason"]) if row is not None else ""
        clear_reason = lockdown == 0 and reason == "readyz_consecutive_failures"
        conn.execute(
            (
                "UPDATE system_state SET readyz_fail_streak=0, lockdown_reason=?, "
                "updated_at=? WHERE id='singleton'"
            ),
            ("" if clear_reason else reason, now_iso()),
        )
        return False

    row = conn.execute(
        "SELECT readyz_fail_streak FROM system_state WHERE id='singleton'"
    ).fetchone()
    streak = int(row["readyz_fail_streak"]) if row is not None else 0
    next_streak = streak + 1
    lockdown = 1 if next_streak >= threshold else 0
    reason = "readyz_consecutive_failures" if lockdown else ""
    conn.execute(
        (
            "UPDATE system_state SET readyz_fail_streak=?, lockdown=?, lockdown_reason=?, "
            "updated_at=? WHERE id='singleton'"
        ),
        (next_streak, lockdown, reason, now_iso()),
    )
    return lockdown == 1


def register_rollback(
    conn: sqlite3.Connection,
    now: datetime | None = None,
    threshold_count: int = 2,
    window_minutes: int = 30,
) -> bool:
    ensure_system_state(conn)
    current = now or datetime.now(UTC)
    row = conn.execute(
        "SELECT rollback_count, last_rollback_at FROM system_state WHERE id='singleton'"
    ).fetchone()
    count = 0
    if row is not None:
        prev_count = int(row["rollback_count"])
        prev_stamp = row["last_rollback_at"]
        if isinstance(prev_stamp, str) and prev_stamp:
            previous = datetime.fromisoformat(prev_stamp)
            within_window = (current - previous).total_seconds() <= window_minutes * 60
            count = prev_count + 1 if within_window else 1
        else:
            count = 1
    lockdown = 1 if count >= threshold_count else 0
    reason = "rollback_burst" if lockdown else ""
    conn.execute(
        (
            "UPDATE system_state SET rollback_count=?, last_rollback_at=?, lockdown=?, "
            "lockdown_reason=?, updated_at=? WHERE id='singleton'"
        ),
        (count, current.isoformat(), lockdown, reason, now_iso()),
    )
    return lockdown == 1


def trigger_lockdown(conn: sqlite3.Connection, reason: str) -> None:
    ensure_system_state(conn)
    conn.execute(
        (
            "UPDATE system_state SET lockdown=1, lockdown_reason=?, updated_at=? "
            "WHERE id='singleton'"
        ),
        (reason, now_iso()),
    )


def record_exec_host_result(
    conn: sqlite3.Connection,
    ok: bool,
    threshold_count: int = 5,
    window_minutes: int = 10,
    now: datetime | None = None,
) -> bool:
    ensure_system_state(conn)
    state_row = conn.execute(
        "SELECT lockdown, lockdown_reason FROM system_state WHERE id='singleton'"
    ).fetchone()
    existing_lockdown = int(state_row["lockdown"]) if state_row is not None else 0
    existing_reason = str(state_row["lockdown_reason"]) if state_row is not None else ""
    if ok:
        conn.execute(
            (
                "UPDATE system_state SET host_exec_fail_streak=0, "
                "last_host_exec_fail_at=NULL, updated_at=? WHERE id='singleton'"
            ),
            (now_iso(),),
        )
        return False

    current = now or datetime.now(UTC)
    query = (
        "SELECT host_exec_fail_streak, last_host_exec_fail_at "
        "FROM system_state WHERE id='singleton'"
    )
    row = conn.execute(
        query
    ).fetchone()
    count = 1
    if row is not None:
        previous_count = int(row["host_exec_fail_streak"])
        previous_stamp = row["last_host_exec_fail_at"]
        if isinstance(previous_stamp, str) and previous_stamp:
            previous = datetime.fromisoformat(previous_stamp)
            within_window = (current - previous).total_seconds() <= window_minutes * 60
            count = previous_count + 1 if within_window else 1

    threshold_lockdown = 1 if count >= threshold_count else 0
    lockdown = 1 if (existing_lockdown == 1 or threshold_lockdown == 1) else 0
    if threshold_lockdown == 1:
        reason = "exec_host_failure_rate"
    elif existing_lockdown == 1:
        reason = existing_reason
    else:
        reason = ""
    conn.execute(
        (
            "UPDATE system_state SET host_exec_fail_streak=?, last_host_exec_fail_at=?, "
            "lockdown=?, lockdown_reason=?, updated_at=? WHERE id='singleton'"
        ),
        (count, current.isoformat(), lockdown, reason, now_iso()),
    )
    return lockdown == 1


def ensure_root_user(conn: sqlite3.Connection) -> str:
    """Ensure a root admin user exists for system/agent operations."""
    external_id = "system:root"
    row = conn.execute(
        "SELECT id, role FROM users WHERE external_id=?", (external_id,)
    ).fetchone()
    if row:
        user_id = str(row["id"])
        if row["role"] != "admin":
            conn.execute("UPDATE users SET role='admin' WHERE id=?", (user_id,))
        return user_id
    user_id = new_id("usr")
    conn.execute(
        "INSERT INTO users(id, external_id, role, created_at) VALUES(?,?,?,?)",
        (user_id, external_id, "admin", now_iso()),
    )
    return user_id


def ensure_user(conn: sqlite3.Connection, external_id: str) -> str:
    row = conn.execute("SELECT id FROM users WHERE external_id=?", (external_id,)).fetchone()
    if row:
        return str(row["id"])
    user_id = new_id("usr")
    conn.execute(
        "INSERT INTO users(id, external_id, role, created_at) VALUES(?,?,?,?)",
        (user_id, external_id, "user", now_iso()),
    )
    return user_id


def ensure_channel(conn: sqlite3.Connection, user_id: str, channel_type: str) -> str:
    row = conn.execute(
        "SELECT id FROM channels WHERE user_id=? AND channel_type=?", (user_id, channel_type)
    ).fetchone()
    if row:
        return str(row["id"])
    channel_id = new_id("chn")
    conn.execute(
        "INSERT INTO channels(id, user_id, channel_type, created_at) VALUES(?,?,?,?)",
        (channel_id, user_id, channel_type, now_iso()),
    )
    return channel_id


def ensure_open_thread(conn: sqlite3.Connection, user_id: str, channel_id: str) -> str:
    # First, try to find ANY open thread for this user, regardless of channel.
    # This enforces the "one global chat thread per user" rule.
    row = conn.execute(
        (
            "SELECT id FROM threads "
            "WHERE user_id=? AND status='open' "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        (user_id,),
    ).fetchone()
    if row:
        return str(row["id"])
    
    # If no thread exists, create a new one.
    thread_id = new_id("thr")
    conn.execute(
        (
            "INSERT INTO threads(id, user_id, channel_id, status, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)"
        ),
        (thread_id, user_id, channel_id, "open", now_iso(), now_iso()),
    )
    conn.execute(
        (
            "INSERT OR IGNORE INTO sessions(id, kind, status, created_at, updated_at) "
            "VALUES(?,?,?,?,?)"
        ),
        (thread_id, "thread", "open", now_iso(), now_iso()),
    )
    conn.execute(
        (
            "INSERT OR IGNORE INTO session_participants("
            "session_id, actor_type, actor_id, role"
            ") VALUES(?,?,?,?)"
        ),
        (thread_id, "user", user_id, "user"),
    )
    return thread_id


def get_thread_by_whatsapp_remote(
    conn: sqlite3.Connection, instance: str, remote_jid: str
) -> str | None:
    row = conn.execute(
        "SELECT thread_id FROM whatsapp_thread_map WHERE instance=? AND remote_jid=? LIMIT 1",
        (instance, remote_jid),
    ).fetchone()
    return str(row["thread_id"]) if row is not None else None


def thread_exists(conn: sqlite3.Connection, thread_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM threads WHERE id=? LIMIT 1", (thread_id,)).fetchone()
    return row is not None


def upsert_whatsapp_thread_map(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    instance: str,
    remote_jid: str,
    participant_jid: str | None = None,
) -> None:
    now = now_iso()
    conn.execute(
        (
            "INSERT INTO whatsapp_thread_map("
            "thread_id, instance, remote_jid, participant_jid, created_at, updated_at"
            ") VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(thread_id) DO UPDATE SET "
            "instance=excluded.instance, remote_jid=excluded.remote_jid, "
            "participant_jid=excluded.participant_jid, updated_at=excluded.updated_at"
        ),
        (thread_id, instance, remote_jid, participant_jid, now, now),
    )


def prune_whatsapp_thread_map_orphans(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "DELETE FROM whatsapp_thread_map "
        "WHERE thread_id NOT IN (SELECT id FROM threads)"
    )
    return int(cursor.rowcount or 0)


def upsert_whatsapp_instance(
    conn: sqlite3.Connection,
    *,
    instance: str,
    status: str,
    metadata: dict[str, object] | None = None,
    callback_url: str = "",
    callback_by_events: bool = False,
    callback_events: list[str] | None = None,
    callback_configured: bool = False,
    callback_last_error: str = "",
) -> None:
    now = now_iso()
    callback_events_json = json.dumps(callback_events or [], sort_keys=True)
    conn.execute(
        (
            "INSERT INTO whatsapp_instances("
            "instance, status, last_seen_at, metadata_json, "
            "callback_url, callback_by_events, callback_events_json, "
            "callback_configured, callback_last_error, created_at, updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(instance) DO UPDATE SET "
            "status=excluded.status, last_seen_at=excluded.last_seen_at, "
            "metadata_json=excluded.metadata_json, "
            "callback_url=excluded.callback_url, "
            "callback_by_events=excluded.callback_by_events, "
            "callback_events_json=excluded.callback_events_json, "
            "callback_configured=excluded.callback_configured, "
            "callback_last_error=excluded.callback_last_error, "
            "updated_at=excluded.updated_at"
        ),
        (
            instance,
            status,
            now,
            json.dumps(metadata or {}, sort_keys=True),
            callback_url.strip(),
            1 if callback_by_events else 0,
            callback_events_json,
            1 if callback_configured else 0,
            callback_last_error[:400],
            now,
            now,
        ),
    )


def get_whatsapp_instance(conn: sqlite3.Connection, instance: str) -> dict[str, object] | None:
    row = conn.execute(
        (
            "SELECT instance, status, last_seen_at, metadata_json, callback_url, "
            "callback_by_events, callback_events_json, callback_configured, "
            "callback_last_error, created_at, updated_at "
            "FROM whatsapp_instances WHERE instance=? LIMIT 1"
        ),
        (instance,),
    ).fetchone()
    if row is None:
        return None
    try:
        metadata = json.loads(str(row["metadata_json"]))
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    try:
        callback_events = json.loads(str(row["callback_events_json"]))
    except json.JSONDecodeError:
        callback_events = []
    if not isinstance(callback_events, list):
        callback_events = []
    return {
        "instance": str(row["instance"]),
        "status": str(row["status"]),
        "last_seen_at": str(row["last_seen_at"]) if row["last_seen_at"] is not None else "",
        "metadata": metadata,
        "callback_url": str(row["callback_url"]),
        "callback_by_events": int(row["callback_by_events"]) == 1,
        "callback_events": [str(item) for item in callback_events if isinstance(item, str)],
        "callback_configured": int(row["callback_configured"]) == 1,
        "callback_last_error": str(row["callback_last_error"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def get_whatsapp_sender_review_open(
    conn: sqlite3.Connection,
    *,
    instance: str,
    sender_jid: str,
) -> dict[str, object] | None:
    row = conn.execute(
        (
            "SELECT id, instance, sender_jid, remote_jid, participant_jid, thread_id, "
            "external_msg_id, reason, status, reviewer_id, resolution_note, created_at, updated_at "
            "FROM whatsapp_sender_review_queue "
            "WHERE instance=? AND sender_jid=? AND status='open' "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        (instance, sender_jid),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "instance": str(row["instance"]),
        "sender_jid": str(row["sender_jid"]),
        "remote_jid": str(row["remote_jid"]) if row["remote_jid"] is not None else "",
        "participant_jid": (
            str(row["participant_jid"]) if row["participant_jid"] is not None else ""
        ),
        "thread_id": str(row["thread_id"]) if row["thread_id"] is not None else "",
        "external_msg_id": (
            str(row["external_msg_id"]) if row["external_msg_id"] is not None else ""
        ),
        "reason": str(row["reason"]),
        "status": str(row["status"]),
        "reviewer_id": str(row["reviewer_id"]) if row["reviewer_id"] is not None else "",
        "resolution_note": (
            str(row["resolution_note"]) if row["resolution_note"] is not None else ""
        ),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def get_whatsapp_sender_review_latest_decision(
    conn: sqlite3.Connection,
    *,
    instance: str,
    sender_jid: str,
) -> str | None:
    row = conn.execute(
        (
            "SELECT status FROM whatsapp_sender_review_queue "
            "WHERE instance=? AND sender_jid=? AND status IN ('allowed', 'denied') "
            "ORDER BY updated_at DESC LIMIT 1"
        ),
        (instance, sender_jid),
    ).fetchone()
    if row is None:
        return None
    status_value = str(row["status"]).strip().lower()
    if status_value in {"allowed", "denied"}:
        return status_value
    return None


def create_whatsapp_sender_review(
    conn: sqlite3.Connection,
    *,
    instance: str,
    sender_jid: str,
    remote_jid: str,
    participant_jid: str,
    thread_id: str,
    external_msg_id: str,
    reason: str,
) -> str:
    review_id = new_id("sch")
    now = now_iso()
    conn.execute(
        (
            "INSERT INTO whatsapp_sender_review_queue("
            "id, instance, sender_jid, remote_jid, participant_jid, thread_id, external_msg_id, "
            "reason, status, reviewer_id, resolution_note, created_at, updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        (
            review_id,
            instance,
            sender_jid,
            remote_jid,
            participant_jid,
            thread_id,
            external_msg_id,
            reason,
            "open",
            None,
            None,
            now,
            now,
        ),
    )
    return review_id


def list_whatsapp_sender_reviews(
    conn: sqlite3.Connection,
    *,
    status: str = "open",
    limit: int = 50,
) -> list[dict[str, object]]:
    rows = conn.execute(
        (
            "SELECT id, instance, sender_jid, remote_jid, participant_jid, thread_id, "
            "external_msg_id, reason, status, reviewer_id, resolution_note, created_at, updated_at "
            "FROM whatsapp_sender_review_queue WHERE status=? "
            "ORDER BY created_at DESC LIMIT ?"
        ),
        (status, max(1, min(500, int(limit)))),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "instance": str(row["instance"]),
            "sender_jid": str(row["sender_jid"]),
            "remote_jid": str(row["remote_jid"]) if row["remote_jid"] is not None else "",
            "participant_jid": (
                str(row["participant_jid"]) if row["participant_jid"] is not None else ""
            ),
            "thread_id": str(row["thread_id"]) if row["thread_id"] is not None else "",
            "external_msg_id": (
                str(row["external_msg_id"]) if row["external_msg_id"] is not None else ""
            ),
            "reason": str(row["reason"]),
            "status": str(row["status"]),
            "reviewer_id": str(row["reviewer_id"]) if row["reviewer_id"] is not None else "",
            "resolution_note": (
                str(row["resolution_note"]) if row["resolution_note"] is not None else ""
            ),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]


def resolve_whatsapp_sender_review(
    conn: sqlite3.Connection,
    *,
    review_id: str,
    decision: Literal["allow", "deny"],
    reviewer_id: str,
    resolution_note: str = "",
) -> dict[str, object] | None:
    row = conn.execute(
        (
            "SELECT id, instance, sender_jid, status FROM whatsapp_sender_review_queue "
            "WHERE id=? LIMIT 1"
        ),
        (review_id,),
    ).fetchone()
    if row is None:
        return None
    if str(row["status"]) != "open":
        return {
            "id": str(row["id"]),
            "instance": str(row["instance"]),
            "sender_jid": str(row["sender_jid"]),
            "status": str(row["status"]),
            "closed": True,
        }
    status = "allowed" if decision == "allow" else "denied"
    now = now_iso()
    conn.execute(
        (
            "UPDATE whatsapp_sender_review_queue "
            "SET status=?, reviewer_id=?, resolution_note=?, updated_at=? "
            "WHERE instance=? AND sender_jid=? AND status='open'"
        ),
        (
            status,
            reviewer_id,
            resolution_note[:500],
            now,
            str(row["instance"]),
            str(row["sender_jid"]),
        ),
    )
    return {
        "id": str(row["id"]),
        "instance": str(row["instance"]),
        "sender_jid": str(row["sender_jid"]),
        "status": status,
        "closed": False,
    }


def create_thread(conn: sqlite3.Connection, user_id: str, channel_id: str) -> str:
    thread_id = new_id("thr")
    conn.execute(
        (
            "INSERT INTO threads(id, user_id, channel_id, status, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)"
        ),
        (thread_id, user_id, channel_id, "open", now_iso(), now_iso()),
    )
    conn.execute(
        (
            "INSERT OR IGNORE INTO sessions(id, kind, status, created_at, updated_at) "
            "VALUES(?,?,?,?,?)"
        ),
        (thread_id, "thread", "open", now_iso(), now_iso()),
    )
    conn.execute(
        (
            "INSERT OR IGNORE INTO session_participants("
            "session_id, actor_type, actor_id, role"
            ") VALUES(?,?,?,?)"
        ),
        (thread_id, "user", user_id, "user"),
    )
    return thread_id


def insert_message(
    conn: sqlite3.Connection,
    thread_id: str,
    role: str,
    content: str,
    *,
    media_path: str | None = None,
    mime_type: str | None = None,
) -> str:
    message_id = new_id("msg")
    conn.execute(
        (
            "INSERT INTO messages("
            "id, thread_id, role, content, media_path, mime_type, created_at"
            ") VALUES(?,?,?,?,?,?,?)"
        ),
        (message_id, thread_id, role, content, media_path, mime_type, now_iso()),
    )
    conn.execute("UPDATE threads SET updated_at=? WHERE id=?", (now_iso(), thread_id))
    return message_id


def create_human_escalation(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    trace_id: str,
    requested_by_actor_id: str,
    source_agent_id: str,
    reason: str,
    message: str,
    channel_type: str,
    target_external_id: str,
    priority: str = "normal",
) -> str:
    escalation_id = new_id("mda")
    now = now_iso()
    conn.execute(
        (
            "INSERT INTO human_escalations("
            "id, thread_id, trace_id, requested_by_actor_id, source_agent_id, "
            "reason, message, status, channel_type, target_external_id, priority, "
            "dispatched_message_id, error, created_at, updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        (
            escalation_id,
            thread_id,
            trace_id,
            requested_by_actor_id,
            source_agent_id,
            reason[:500],
            message[:4000],
            "queued",
            channel_type[:40],
            target_external_id[:200],
            priority[:20],
            "",
            "",
            now,
            now,
        ),
    )
    return escalation_id


def has_pending_human_escalation(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    reason: str | None = None,
) -> bool:
    query = (
        "SELECT 1 FROM human_escalations "
        "WHERE thread_id=? AND status IN ('queued','dispatched')"
    )
    params: list[object] = [thread_id]
    if reason:
        query += " AND reason=?"
        params.append(reason)
    query += " LIMIT 1"
    row = conn.execute(query, tuple(params)).fetchone()
    return row is not None


def list_due_human_escalations(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    rows = conn.execute(
        (
            "SELECT id, thread_id, trace_id, requested_by_actor_id, source_agent_id, "
            "reason, message, status, channel_type, target_external_id, priority, "
            "dispatched_message_id, error, created_at, updated_at "
            "FROM human_escalations "
            "WHERE status='queued' "
            "ORDER BY created_at ASC LIMIT ?"
        ),
        (max(1, min(500, int(limit))),),
    ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        items.append(
            {
                "id": str(row["id"]),
                "thread_id": str(row["thread_id"]),
                "trace_id": str(row["trace_id"]),
                "requested_by_actor_id": str(row["requested_by_actor_id"]),
                "source_agent_id": str(row["source_agent_id"]),
                "reason": str(row["reason"]),
                "message": str(row["message"]),
                "status": str(row["status"]),
                "channel_type": str(row["channel_type"]),
                "target_external_id": str(row["target_external_id"]),
                "priority": str(row["priority"]),
                "dispatched_message_id": str(row["dispatched_message_id"]),
                "error": str(row["error"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
        )
    return items


def update_human_escalation(
    conn: sqlite3.Connection,
    escalation_id: str,
    *,
    status: str,
    dispatched_message_id: str | None = None,
    error: str | None = None,
) -> None:
    updates = ["status=?", "updated_at=?"]
    params: list[object] = [status, now_iso()]
    if dispatched_message_id is not None:
        updates.append("dispatched_message_id=?")
        params.append(dispatched_message_id)
    if error is not None:
        updates.append("error=?")
        params.append(error[:1000])
    params.append(escalation_id)
    conn.execute(
        f"UPDATE human_escalations SET {', '.join(updates)} WHERE id=?",
        tuple(params),
    )


def record_external_message(
    conn: sqlite3.Connection,
    channel_type: str,
    external_msg_id: str,
    trace_id: str,
) -> bool:
    try:
        conn.execute(
            (
                "INSERT INTO external_messages("
                "id, channel_type, external_msg_id, trace_id, created_at"
                ") VALUES(?,?,?,?,?)"
            ),
            (new_id("ext"), channel_type, external_msg_id, trace_id, now_iso()),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def get_whatsapp_media_by_message(
    conn: sqlite3.Connection, *, thread_id: str, message_id: str
) -> dict[str, object] | None:
    row = conn.execute(
        (
            "SELECT id, thread_id, message_id, media_type, local_path, "
            "mime_type, bytes, created_at "
            "FROM whatsapp_media WHERE thread_id=? AND message_id=? LIMIT 1"
        ),
        (thread_id, message_id),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "thread_id": str(row["thread_id"]),
        "message_id": str(row["message_id"]) if row["message_id"] is not None else "",
        "media_type": str(row["media_type"]),
        "local_path": str(row["local_path"]),
        "mime_type": str(row["mime_type"]) if row["mime_type"] is not None else "",
        "bytes": int(row["bytes"]),
        "created_at": str(row["created_at"]),
    }


def insert_whatsapp_media(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    message_id: str,
    media_type: str,
    local_path: str,
    mime_type: str,
    num_bytes: int,
) -> str:
    existing = get_whatsapp_media_by_message(conn, thread_id=thread_id, message_id=message_id)
    if existing is not None:
        return str(existing["id"])
    media_id = new_id("wmd")
    conn.execute(
        (
            "INSERT INTO whatsapp_media("
            "id, thread_id, message_id, media_type, local_path, mime_type, bytes, created_at"
            ") VALUES(?,?,?,?,?,?,?,?)"
        ),
        (
            media_id,
            thread_id,
            message_id,
            media_type,
            local_path,
            mime_type,
            int(num_bytes),
            now_iso(),
        ),
    )
    return media_id


def set_thread_verbose(conn: sqlite3.Connection, thread_id: str, verbose: bool) -> None:
    conn.execute(
        """
        INSERT INTO thread_settings(thread_id, verbose, active_agent_ids_json, updated_at)
        VALUES(?,?,?,?)
        ON CONFLICT(thread_id) DO UPDATE SET
          verbose=excluded.verbose,
          updated_at=excluded.updated_at
        """,
        (
            thread_id,
            int(verbose),
            json.dumps(sorted(get_all_agent_ids())),
            now_iso(),
        ),
    )


def set_thread_agents(conn: sqlite3.Connection, thread_id: str, agents: list[str]) -> None:
    conn.execute(
        """
        INSERT INTO thread_settings(thread_id, verbose, active_agent_ids_json, updated_at)
        VALUES(?,?,?,?)
        ON CONFLICT(thread_id) DO UPDATE SET
          active_agent_ids_json=excluded.active_agent_ids_json,
          updated_at=excluded.updated_at
        """,
        (thread_id, 0, json.dumps(agents), now_iso()),
    )


def create_approval(
    conn: sqlite3.Connection,
    action: str,
    actor_id: str,
    status: str = "approved",
    target_ref: str = "",
    ttl_minutes: int | None = None,
) -> str:
    approval_id = new_id("apr")
    expires_at = None
    if ttl_minutes is not None:
        ttl = max(1, int(ttl_minutes))
        expires_at = (datetime.now(UTC) + timedelta(minutes=ttl)).isoformat()
    conn.execute(
        (
            "INSERT INTO approvals("
            "id, action, actor_id, status, target_ref, expires_at, consumed_by_trace_id, created_at"
            ") VALUES(?,?,?,?,?,?,?,?)"
        ),
        (approval_id, action, actor_id, status, target_ref, expires_at, "", now_iso()),
    )
    return approval_id


def consume_approval(
    conn: sqlite3.Connection,
    action: str,
    *,
    target_ref: str = "",
    trace_id: str = "",
) -> bool:
    now = now_iso()
    if target_ref:
        row = conn.execute(
            (
                "SELECT id FROM approvals "
                "WHERE action=? AND status='approved' AND target_ref=? "
                "AND (expires_at IS NULL OR expires_at > ?) "
                "ORDER BY created_at ASC LIMIT 1"
            ),
            (action, target_ref, now),
        ).fetchone()
    else:
        row = conn.execute(
            (
                "SELECT id FROM approvals "
                "WHERE action=? AND status='approved' "
                "AND (target_ref='' OR target_ref IS NULL) "
                "AND (expires_at IS NULL OR expires_at > ?) "
                "ORDER BY created_at ASC LIMIT 1"
            ),
            (action, now),
        ).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE approvals SET status='consumed', consumed_by_trace_id=? WHERE id=?",
        (trace_id, str(row["id"])),
    )
    return True


def get_agent_governance(
    conn: sqlite3.Connection, principal_id: str
) -> dict[str, object] | None:
    row = conn.execute(
        (
            "SELECT principal_id, risk_tier, max_actions_per_step, allowed_paths_json, "
            "can_request_privileged_change, updated_at "
            "FROM agent_governance WHERE principal_id=? LIMIT 1"
        ),
        (principal_id,),
    ).fetchone()
    if row is None:
        return None
    paths_raw = row["allowed_paths_json"]
    try:
        parsed_paths = json.loads(str(paths_raw)) if paths_raw is not None else []
    except json.JSONDecodeError:
        parsed_paths = []
    allowed_paths = [str(v) for v in parsed_paths if isinstance(v, str)]
    return {
        "principal_id": str(row["principal_id"]),
        "risk_tier": str(row["risk_tier"]),
        "max_actions_per_step": int(row["max_actions_per_step"]),
        "allowed_paths": allowed_paths,
        "can_request_privileged_change": int(row["can_request_privileged_change"]) == 1,
        "updated_at": str(row["updated_at"]),
    }


def get_whatsapp_outbound(
    conn: sqlite3.Connection, thread_id: str, message_id: str
) -> dict[str, str | None] | None:
    return get_channel_outbound(conn, thread_id, message_id, "whatsapp")


def get_channel_outbound(
    conn: sqlite3.Connection, thread_id: str, message_id: str, channel_type: str
) -> dict[str, str | None] | None:
    row = conn.execute(
        (
            "SELECT u.external_id AS recipient, m.content AS text, m.media_path, m.mime_type "
            "FROM messages m "
            "JOIN threads t ON t.id=m.thread_id "
            "JOIN users u ON u.id=t.user_id "
            "JOIN channels c ON c.id=t.channel_id "
            "WHERE m.id=? AND m.thread_id=? AND m.role='assistant' AND c.channel_type=? "
            "LIMIT 1"
        ),
        (message_id, thread_id, channel_type),
    ).fetchone()
    if row is None:
        return None
    return {
        "recipient": str(row["recipient"]),
        "text": str(row["text"]),
        "media_path": str(row["media_path"]) if row["media_path"] else None,
        "mime_type": str(row["mime_type"]) if row["mime_type"] else None,
    }


def store_consistency_report(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    sample_size: int,
    total_items: int,
    conflicted_items: int,
    consistency_score: float,
    details: dict[str, object] | None = None,
) -> str:
    report_id = new_id("csr")
    conn.execute(
        (
            "INSERT INTO memory_consistency_reports("
            "id, thread_id, sample_size, total_items, conflicted_items, "
            "consistency_score, details_json, created_at"
            ") VALUES(?,?,?,?,?,?,?,?)"
        ),
        (
            report_id,
            thread_id,
            int(sample_size),
            int(total_items),
            int(conflicted_items),
            float(consistency_score),
            json.dumps(details or {}, sort_keys=True),
            now_iso(),
        ),
    )
    return report_id


def upsert_selfupdate_run(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    state: str,
    baseline_ref: str,
    repo_path: str,
    rationale: str,
    changed_files: list[str] | None = None,
) -> None:
    files_json = json.dumps(changed_files or [], sort_keys=True)
    now = now_iso()
    conn.execute(
        (
            "INSERT INTO selfupdate_runs("
            "trace_id, state, baseline_ref, repo_path, rationale, changed_files_json, "
            "created_at, updated_at"
            ") VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(trace_id) DO UPDATE SET "
            "state=excluded.state, baseline_ref=excluded.baseline_ref, "
            "repo_path=excluded.repo_path, rationale=excluded.rationale, "
            "changed_files_json=excluded.changed_files_json, updated_at=excluded.updated_at"
        ),
        (trace_id, state, baseline_ref, repo_path, rationale, files_json, now, now),
    )


def update_selfupdate_run_state(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    state: str,
) -> None:
    conn.execute(
        "UPDATE selfupdate_runs SET state=?, updated_at=? WHERE trace_id=?",
        (state, now_iso(), trace_id),
    )


def insert_selfupdate_check(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    check_type: str,
    status: str,
    detail: str,
    payload: dict[str, object],
) -> str:
    check_id = new_id("suc")
    conn.execute(
        (
            "INSERT INTO selfupdate_checks("
            "id, trace_id, check_type, status, detail, payload_json, created_at"
            ") VALUES(?,?,?,?,?,?,?)"
        ),
        (check_id, trace_id, check_type, status, detail, json.dumps(payload), now_iso()),
    )
    return check_id


def insert_selfupdate_transition(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    from_state: str,
    to_state: str,
    reason: str,
) -> str:
    transition_id = new_id("sut")
    conn.execute(
        (
            "INSERT INTO selfupdate_transitions("
            "id, trace_id, from_state, to_state, reason, created_at"
            ") VALUES(?,?,?,?,?,?)"
        ),
        (transition_id, trace_id, from_state, to_state, reason, now_iso()),
    )
    return transition_id


def list_selfupdate_checks(conn: sqlite3.Connection, trace_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        (
            "SELECT id, trace_id, check_type, status, detail, payload_json, created_at "
            "FROM selfupdate_checks WHERE trace_id=? "
            "ORDER BY created_at DESC, id DESC"
        ),
        (trace_id,),
    ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        payload_raw = str(row["payload_json"])
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = {"raw": payload_raw}
        items.append(
            {
                "id": str(row["id"]),
                "trace_id": str(row["trace_id"]),
                "check_type": str(row["check_type"]),
                "status": str(row["status"]),
                "detail": str(row["detail"]),
                "payload": payload if isinstance(payload, dict) else {"raw": payload_raw},
                "created_at": str(row["created_at"]),
            }
        )
    return items


def list_selfupdate_transitions(
    conn: sqlite3.Connection, trace_id: str
) -> list[dict[str, object]]:
    rows = conn.execute(
        (
            "SELECT id, trace_id, from_state, to_state, reason, created_at "
            "FROM selfupdate_transitions WHERE trace_id=? "
            "ORDER BY created_at ASC, id ASC"
        ),
        (trace_id,),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "trace_id": str(row["trace_id"]),
            "from_state": str(row["from_state"]),
            "to_state": str(row["to_state"]),
            "reason": str(row["reason"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def insert_system_fitness_snapshot(
    conn: sqlite3.Connection,
    *,
    period_start: str,
    period_end: str,
    metrics: dict[str, object],
) -> str:
    snapshot_id = new_id("fit")
    conn.execute(
        (
            "INSERT INTO system_fitness_snapshots("
            "id, period_start, period_end, metrics_json, created_at"
            ") VALUES(?,?,?,?,?)"
        ),
        (snapshot_id, period_start, period_end, json.dumps(metrics, sort_keys=True), now_iso()),
    )
    return snapshot_id


def latest_system_fitness_snapshot(conn: sqlite3.Connection) -> dict[str, object] | None:
    row = conn.execute(
        "SELECT id, period_start, period_end, metrics_json, created_at "
        "FROM system_fitness_snapshots ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    raw_metrics = str(row["metrics_json"])
    try:
        metrics = json.loads(raw_metrics)
    except json.JSONDecodeError:
        metrics = {}
    return {
        "id": str(row["id"]),
        "period_start": str(row["period_start"]),
        "period_end": str(row["period_end"]),
        "metrics": metrics if isinstance(metrics, dict) else {},
        "created_at": str(row["created_at"]),
    }


def list_system_fitness_snapshots(
    conn: sqlite3.Connection, *, limit: int = 12
) -> list[dict[str, object]]:
    rows = conn.execute(
        (
            "SELECT id, period_start, period_end, metrics_json, created_at "
            "FROM system_fitness_snapshots ORDER BY created_at DESC LIMIT ?"
        ),
        (max(1, min(200, int(limit))),),
    ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        raw_metrics = str(row["metrics_json"])
        try:
            metrics = json.loads(raw_metrics)
        except json.JSONDecodeError:
            metrics = {}
        items.append(
            {
                "id": str(row["id"]),
                "period_start": str(row["period_start"]),
                "period_end": str(row["period_end"]),
                "metrics": metrics if isinstance(metrics, dict) else {},
                "created_at": str(row["created_at"]),
            }
        )
    return items


def ensure_selfupdate_fitness_gate_config(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            (
                "INSERT OR IGNORE INTO selfupdate_fitness_gate_config("
                "id, max_snapshot_age_minutes, min_build_success_rate, "
                "max_regression_frequency, max_rollback_frequency, updated_at"
                ") VALUES('singleton', 180, 0.80, 0.40, 3, ?)"
            ),
            (now_iso(),),
        )
    except sqlite3.OperationalError:
        # Table may not exist before migration is applied.
        return


def get_selfupdate_fitness_gate_config(conn: sqlite3.Connection) -> dict[str, object] | None:
    ensure_selfupdate_fitness_gate_config(conn)
    try:
        row = conn.execute(
            "SELECT max_snapshot_age_minutes, min_build_success_rate, "
            "max_regression_frequency, max_rollback_frequency, updated_at "
            "FROM selfupdate_fitness_gate_config WHERE id='singleton' LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return {
        "max_snapshot_age_minutes": int(row["max_snapshot_age_minutes"]),
        "min_build_success_rate": float(row["min_build_success_rate"]),
        "max_regression_frequency": float(row["max_regression_frequency"]),
        "max_rollback_frequency": int(row["max_rollback_frequency"]),
        "updated_at": str(row["updated_at"]),
    }


def insert_governance_agent_run(
    conn: sqlite3.Connection,
    *,
    run_type: str,
    status: str,
    summary: str,
    payload: dict[str, object],
    trace_id: str = "",
) -> str:
    run_id = new_id("gov")
    conn.execute(
        (
            "INSERT INTO governance_agent_runs("
            "id, run_type, status, summary, payload_json, trace_id, created_at"
            ") VALUES(?,?,?,?,?,?,?)"
        ),
        (
            run_id,
            run_type,
            status,
            summary[:500],
            json.dumps(payload, sort_keys=True),
            trace_id,
            now_iso(),
        ),
    )
    return run_id


def ensure_system_guardrails(conn: sqlite3.Connection) -> None:
    conn.execute(
        (
            "INSERT OR IGNORE INTO system_guardrails("
            "id, max_patch_attempts_per_day, max_prs_per_day, max_files_per_patch, "
            "max_risk_score, updated_at"
            ") VALUES('singleton', 20, 10, 60, 8, ?)"
        ),
        (now_iso(),),
    )


def get_system_guardrails(conn: sqlite3.Connection) -> dict[str, int]:
    ensure_system_guardrails(conn)
    row = conn.execute(
        "SELECT max_patch_attempts_per_day, max_prs_per_day, max_files_per_patch, "
        "max_risk_score FROM system_guardrails WHERE id='singleton'"
    ).fetchone()
    assert row is not None
    return {
        "max_patch_attempts_per_day": int(row["max_patch_attempts_per_day"]),
        "max_prs_per_day": int(row["max_prs_per_day"]),
        "max_files_per_patch": int(row["max_files_per_patch"]),
        "max_risk_score": int(row["max_risk_score"]),
    }


def insert_guardrail_trip(
    conn: sqlite3.Connection,
    *,
    guardrail_key: str,
    actual_value: int,
    threshold_value: int,
    trace_id: str = "",
    detail: dict[str, object] | None = None,
) -> str:
    trip_id = new_id("grd")
    conn.execute(
        (
            "INSERT INTO guardrail_trips("
            "id, guardrail_key, actual_value, threshold_value, trace_id, detail_json, created_at"
            ") VALUES(?,?,?,?,?,?,?)"
        ),
        (
            trip_id,
            guardrail_key,
            int(actual_value),
            int(threshold_value),
            trace_id,
            json.dumps(detail or {}, sort_keys=True),
            now_iso(),
        ),
    )
    return trip_id


def list_failure_remediations(
    conn: sqlite3.Connection, pattern_id: str, *, limit: int = 5
) -> list[dict[str, object]]:
    rows = conn.execute(
        (
            "SELECT id, pattern_id, remediation, verification_test, confidence, created_at "
            "FROM failure_pattern_remediations WHERE pattern_id=? "
            "ORDER BY created_at DESC LIMIT ?"
        ),
        (pattern_id, max(1, min(20, int(limit)))),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "pattern_id": str(row["pattern_id"]),
            "remediation": str(row["remediation"]),
            "verification_test": str(row["verification_test"]),
            "confidence": str(row["confidence"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def create_failure_remediation_feedback(
    conn: sqlite3.Connection,
    *,
    remediation_id: str,
    actor_id: str,
    feedback: str,
) -> str:
    entry_id = new_id("frf")
    conn.execute(
        (
            "INSERT INTO failure_remediation_feedback("
            "id, remediation_id, actor_id, feedback, created_at"
            ") VALUES(?,?,?,?,?)"
        ),
        (entry_id, remediation_id, actor_id, feedback, now_iso()),
    )
    return entry_id


def remediation_feedback_stats(
    conn: sqlite3.Connection, remediation_id: str
) -> dict[str, int]:
    rows = conn.execute(
        (
            "SELECT feedback, COUNT(*) AS n FROM failure_remediation_feedback "
            "WHERE remediation_id=? GROUP BY feedback"
        ),
        (remediation_id,),
    ).fetchall()
    stats = {"accepted": 0, "rejected": 0}
    for row in rows:
        key = str(row["feedback"]).strip().lower()
        if key in stats:
            stats[key] = int(row["n"])
    return stats


def update_remediation_confidence(
    conn: sqlite3.Connection, remediation_id: str, confidence: str
) -> None:
    conn.execute(
        "UPDATE failure_pattern_remediations SET confidence=? WHERE id=?",
        (confidence, remediation_id),
    )


def get_evolution_item(conn: sqlite3.Connection, item_id: str) -> dict[str, object] | None:
    row = conn.execute(
        (
            "SELECT id, trace_id, "
            "(SELECT e.span_id FROM events e "
            " WHERE e.trace_id=evolution_items.trace_id "
            "   AND e.event_type LIKE 'evolution.item.%' "
            " ORDER BY e.created_at DESC LIMIT 1) AS span_id, "
            "thread_id, status, evidence_refs_json, result_json, "
            "updated_by, created_at, updated_at "
            "FROM evolution_items WHERE id=? LIMIT 1"
        ),
        (item_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        evidence_refs = json.loads(str(row["evidence_refs_json"]))
    except json.JSONDecodeError:
        evidence_refs = []
    if not isinstance(evidence_refs, list):
        evidence_refs = []
    try:
        result = json.loads(str(row["result_json"]))
    except json.JSONDecodeError:
        result = {}
    if not isinstance(result, dict):
        result = {}
    return {
        "id": str(row["id"]),
        "item_id": str(row["id"]),
        "trace_id": str(row["trace_id"]),
        "span_id": str(row["span_id"]) if row["span_id"] is not None else "",
        "thread_id": str(row["thread_id"]) if row["thread_id"] is not None else "",
        "status": str(row["status"]),
        "evidence_refs": [str(item) for item in evidence_refs if isinstance(item, str)],
        "result": result,
        "updated_by": str(row["updated_by"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def upsert_evolution_item(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    trace_id: str,
    thread_id: str | None,
    status: str,
    evidence_refs: list[str],
    result: dict[str, object],
    updated_by: str,
) -> None:
    now = now_iso()
    conn.execute(
        (
            "INSERT INTO evolution_items("
            "id, trace_id, thread_id, status, evidence_refs_json, result_json, "
            "updated_by, created_at, updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "trace_id=excluded.trace_id, thread_id=excluded.thread_id, status=excluded.status, "
            "evidence_refs_json=excluded.evidence_refs_json, result_json=excluded.result_json, "
            "updated_by=excluded.updated_by, updated_at=excluded.updated_at"
        ),
        (
            item_id,
            trace_id,
            thread_id,
            status,
            json.dumps(evidence_refs, sort_keys=True),
            json.dumps(result, sort_keys=True),
            updated_by,
            now,
            now,
        ),
    )


def list_evolution_items(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    trace_id: str | None = None,
    thread_id: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    filters: list[str] = []
    params: list[object] = []
    if status:
        filters.append("status=?")
        params.append(status)
    if trace_id:
        filters.append("trace_id=?")
        params.append(trace_id)
    if thread_id:
        filters.append("thread_id=?")
        params.append(thread_id)
    if from_ts:
        filters.append("updated_at>=?")
        params.append(from_ts)
    if to_ts:
        filters.append("updated_at<=?")
        params.append(to_ts)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = conn.execute(
        (
            "SELECT id, trace_id, "
            "(SELECT e.span_id FROM events e "
            " WHERE e.trace_id=evolution_items.trace_id "
            "   AND e.event_type LIKE 'evolution.item.%' "
            " ORDER BY e.created_at DESC LIMIT 1) AS span_id, "
            "thread_id, status, evidence_refs_json, result_json, "
            "updated_by, created_at, updated_at "
            f"FROM evolution_items {where} ORDER BY updated_at DESC LIMIT ?"
        ),
        (*params, max(1, min(1000, int(limit)))),
    ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        try:
            evidence_refs = json.loads(str(row["evidence_refs_json"]))
        except json.JSONDecodeError:
            evidence_refs = []
        if not isinstance(evidence_refs, list):
            evidence_refs = []
        try:
            result = json.loads(str(row["result_json"]))
        except json.JSONDecodeError:
            result = {}
        if not isinstance(result, dict):
            result = {}
        items.append(
            {
                "id": str(row["id"]),
                "item_id": str(row["id"]),
                "trace_id": str(row["trace_id"]),
                "span_id": str(row["span_id"]) if row["span_id"] is not None else "",
                "thread_id": str(row["thread_id"]) if row["thread_id"] is not None else "",
                "status": str(row["status"]),
                "evidence_refs": [str(item) for item in evidence_refs if isinstance(item, str)],
                "result": result,
                "updated_by": str(row["updated_by"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
        )
    return items


def set_typing_state(
    conn: sqlite3.Connection,
    thread_id: str,
    recipient: str,
    channel_type: str,
) -> None:
    now = now_iso()
    conn.execute(
        (
            "INSERT INTO channel_typing_state(thread_id, recipient, channel_type, set_at) "
            "VALUES(?,?,?,?) "
            "ON CONFLICT(thread_id, recipient) DO UPDATE "
            "SET set_at=excluded.set_at, channel_type=excluded.channel_type"
        ),
        (thread_id, recipient, channel_type, now),
    )


def clear_typing_state(
    conn: sqlite3.Connection,
    thread_id: str,
    recipient: str,
) -> None:
    conn.execute(
        "DELETE FROM channel_typing_state WHERE thread_id=? AND recipient=?",
        (thread_id, recipient),
    )


def get_stale_typing_states(
    conn: sqlite3.Connection,
    cutoff_iso: str,
) -> list[dict[str, str]]:
    rows = conn.execute(
        (
            "SELECT thread_id, recipient, channel_type, set_at "
            "FROM channel_typing_state WHERE set_at < ?"
        ),
        (cutoff_iso,),
    ).fetchall()
    return [
        {
            "thread_id": str(row["thread_id"]),
            "recipient": str(row["recipient"]),
            "channel_type": str(row["channel_type"]),
            "set_at": str(row["set_at"]),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Feature request approval helpers
# ---------------------------------------------------------------------------

VALID_APPROVAL_STATUSES = {"pending", "approved", "rejected"}
VALID_BUG_PRIORITIES = {"low", "medium", "high", "critical"}


def create_feature_request(
    conn: sqlite3.Connection,
    *,
    title: str,
    description: str,
    priority: str,
    reporter_id: str,
    thread_id: str | None,
    trace_id: str | None,
) -> tuple[str, bool]:
    """Insert a feature request row; dedupe by trace/thread/reporter/title when trace is set.

    Returns (feature_id, created) where created=False indicates an idempotent hit.
    """
    normalized_priority = priority.strip().lower()
    if normalized_priority not in VALID_BUG_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {priority}")
    normalized_title = title.strip()
    if not normalized_title:
        raise HTTPException(status_code=400, detail="title is required")
    normalized_description = description.strip()
    normalized_thread_id = thread_id.strip() if isinstance(thread_id, str) else ""
    normalized_trace_id = trace_id.strip() if isinstance(trace_id, str) else ""
    if normalized_trace_id:
        existing = conn.execute(
            (
                "SELECT id FROM bug_reports "
                "WHERE kind='feature' AND reporter_id=? AND "
                "COALESCE(thread_id,'')=? AND COALESCE(trace_id,'')=? AND title=? "
                "ORDER BY created_at ASC LIMIT 1"
            ),
            (
                reporter_id,
                normalized_thread_id,
                normalized_trace_id,
                normalized_title,
            ),
        ).fetchone()
        if existing is not None:
            return str(existing["id"]), False

    feature_id = new_id("bug")
    ts = now_iso()
    conn.execute(
        (
            "INSERT INTO bug_reports(id, kind, title, description, status, priority, "
            "reporter_id, assignee_agent, thread_id, trace_id, "
            "github_issue_number, github_issue_url, github_synced_at, github_sync_error, "
            "created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        (
            feature_id,
            "feature",
            normalized_title,
            normalized_description,
            "open",
            normalized_priority,
            reporter_id,
            None,
            normalized_thread_id or None,
            normalized_trace_id or None,
            None,
            None,
            None,
            None,
            ts,
            ts,
        ),
    )
    return feature_id, True


def set_feature_request_approval(
    conn: sqlite3.Connection,
    feature_id: str,
    *,
    decision: str,
    actor_id: str,
    note: str = "",
) -> None:
    """Update approval_status for a feature request (kind='feature')."""
    if decision not in ("approved", "rejected"):
        raise ValueError(f"Invalid decision: {decision}")
    row = conn.execute(
        "SELECT id, kind FROM bug_reports WHERE id=? LIMIT 1",
        (feature_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Feature request not found")
    if str(row["kind"]) != "feature":
        raise HTTPException(status_code=400, detail="Record is not a feature request")
    ts = now_iso()
    if decision == "approved":
        conn.execute(
            (
                "UPDATE bug_reports SET approval_status=?, approval_note=?, "
                "approved_by=?, approved_at=?, rejected_by=NULL, rejected_at=NULL, "
                "updated_at=? WHERE id=?"
            ),
            (decision, note, actor_id, ts, ts, feature_id),
        )
    else:
        conn.execute(
            (
                "UPDATE bug_reports SET approval_status=?, approval_note=?, "
                "rejected_by=?, rejected_at=?, approved_by=NULL, approved_at=NULL, "
                "updated_at=? WHERE id=?"
            ),
            (decision, note, actor_id, ts, ts, feature_id),
        )


# ---------------------------------------------------------------------------
# Feature request build run helpers
# ---------------------------------------------------------------------------

BUILD_RUN_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    "decomposed",
}
BUILD_RUN_RETRY_STATES = {"none", "scheduled", "running", "exhausted"}


def create_feature_build_run(
    conn: sqlite3.Connection,
    *,
    feature_id: str,
    created_by: str,
    trace_id: str = "",
    thread_id: str = "",
) -> str:
    """Insert a new build run row in 'queued' state and return its id."""
    run_id = new_id("fbr")
    ts = now_iso()
    conn.execute(
        (
            "INSERT INTO feature_request_build_runs"
            "(id, feature_id, trace_id, thread_id, status, summary, attempt_count, max_attempts, "
            "retry_state, next_retry_at, last_failure_reason, active_attempt, last_progress_at, "
            "last_event_type, last_trace_id, terminal_reason, created_by, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        (
            run_id,
            feature_id,
            trace_id,
            thread_id,
            "queued",
            "",
            1,
            5,
            "none",
            "",
            "",
            1,
            "",
            "",
            "",
            "",
            created_by,
            ts,
            ts,
        ),
    )
    return run_id


def update_feature_build_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str | None = None,
    trace_id: str | None = None,
    thread_id: str | None = None,
    summary: str | None = None,
    attempt_count: int | None = None,
    max_attempts: int | None = None,
    retry_state: str | None = None,
    next_retry_at: str | None = None,
    last_failure_reason: str | None = None,
    active_attempt: int | None = None,
    last_progress_at: str | None = None,
    last_event_type: str | None = None,
    last_trace_id: str | None = None,
    terminal_reason: str | None = None,
) -> None:
    """Partial update for a feature build run row."""
    updates: list[str] = []
    params: list[object] = []
    if status is not None:
        if status not in BUILD_RUN_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        updates.append("status=?")
        params.append(status)
    if trace_id is not None:
        updates.append("trace_id=?")
        params.append(trace_id)
    if thread_id is not None:
        updates.append("thread_id=?")
        params.append(thread_id)
    if summary is not None:
        updates.append("summary=?")
        params.append(summary)
    if attempt_count is not None:
        updates.append("attempt_count=?")
        params.append(max(1, int(attempt_count)))
    if max_attempts is not None:
        updates.append("max_attempts=?")
        params.append(max(1, int(max_attempts)))
    if retry_state is not None:
        state = str(retry_state).strip()
        if state not in BUILD_RUN_RETRY_STATES:
            raise ValueError(f"Invalid retry_state: {retry_state}")
        updates.append("retry_state=?")
        params.append(state)
    if next_retry_at is not None:
        updates.append("next_retry_at=?")
        params.append(str(next_retry_at))
    if last_failure_reason is not None:
        updates.append("last_failure_reason=?")
        params.append(str(last_failure_reason)[:500])
    if active_attempt is not None:
        updates.append("active_attempt=?")
        params.append(max(1, int(active_attempt)))
    if last_progress_at is not None:
        updates.append("last_progress_at=?")
        params.append(str(last_progress_at))
    if last_event_type is not None:
        updates.append("last_event_type=?")
        params.append(str(last_event_type)[:120])
    if last_trace_id is not None:
        updates.append("last_trace_id=?")
        params.append(str(last_trace_id)[:80])
    if terminal_reason is not None:
        updates.append("terminal_reason=?")
        params.append(str(terminal_reason)[:160])
    if not updates:
        return
    updates.append("updated_at=?")
    params.append(now_iso())
    params.append(run_id)
    conn.execute(
        f"UPDATE feature_request_build_runs SET {', '.join(updates)} WHERE id=?",
        tuple(params),
    )


def finalize_feature_build_run_by_trace(
    conn: sqlite3.Connection,
    trace_id: str,
    *,
    status: str,
    summary: str,
) -> str | None:
    """Finalize latest queued/running build run for a trace.

    Returns run_id when a row was updated, else None.
    """
    trace = str(trace_id or "").strip()
    if not trace:
        return None
    row = conn.execute(
        (
            "SELECT id FROM feature_request_build_runs "
            "WHERE trace_id=? AND status IN ('queued','running') "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        (trace,),
    ).fetchone()
    if row is None:
        return None
    run_id = str(row["id"])
    update_feature_build_run(
        conn,
        run_id,
        status=status,
        summary=str(summary or "").strip()[:500],
        retry_state="none",
        next_retry_at="",
    )
    return run_id


def get_feature_build_run_by_trace(
    conn: sqlite3.Connection,
    trace_id: str,
) -> dict[str, object] | None:
    trace = str(trace_id or "").strip()
    if not trace:
        return None
    row = conn.execute(
        (
            "SELECT * FROM feature_request_build_runs "
            "WHERE trace_id=? ORDER BY created_at DESC LIMIT 1"
        ),
        (trace,),
    ).fetchone()
    return dict(row) if row is not None else None


def get_attempt_initial_dirty_files(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
) -> list[str] | None:
    try:
        row = conn.execute(
            (
                "SELECT initial_dirty_files FROM agent_run_attempts "
                "WHERE trace_id=? ORDER BY attempt DESC LIMIT 1"
            ),
            (trace_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    raw = str(row["initial_dirty_files"] or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    filtered: list[str] = []
    for item in payload:
        if not isinstance(item, str):
            continue
        candidate = item.strip()
        if not candidate or candidate in filtered:
            continue
        filtered.append(candidate)
    return filtered or None


def get_feature_build_run(
    conn: sqlite3.Connection,
    run_id: str,
) -> dict[str, object] | None:
    row = conn.execute(
        "SELECT * FROM feature_request_build_runs WHERE id=? LIMIT 1",
        (run_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def list_due_feature_build_retries(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    now_dt = now or datetime.now(UTC)
    max_rows = max(1, int(limit))
    rows = conn.execute(
        (
            "SELECT id, feature_id, trace_id, thread_id, created_by, attempt_count, max_attempts, "
            "retry_state, next_retry_at, status "
            "FROM feature_request_build_runs "
            "WHERE status='running' AND retry_state='scheduled' AND next_retry_at!='' "
            "ORDER BY next_retry_at ASC LIMIT ?"
        ),
        (max_rows,),
    ).fetchall()
    due: list[dict[str, object]] = []
    for row in rows:
        stamp = str(row["next_retry_at"] or "").strip()
        if not stamp:
            continue
        try:
            at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        if at.astimezone(UTC) > now_dt:
            continue
        due.append(dict(row))
    return due


def list_feature_build_runs(
    conn: sqlite3.Connection,
    feature_id: str,
    limit: int = 20,
) -> list[dict[str, object]]:
    rows = conn.execute(
        (
            "SELECT id, feature_id, trace_id, thread_id, status, summary, "
            "attempt_count, max_attempts, retry_state, next_retry_at, last_failure_reason, "
            "active_attempt, last_progress_at, last_event_type, last_trace_id, terminal_reason, "
            "created_by, created_at, updated_at "
            "FROM feature_request_build_runs WHERE feature_id=? "
            "ORDER BY created_at DESC LIMIT ?"
        ),
        (feature_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest_feature_build_run_for_thread(
    conn: sqlite3.Connection,
    thread_id: str,
) -> dict[str, object] | None:
    row = conn.execute(
        (
            "SELECT r.id, r.feature_id, r.trace_id, r.thread_id, r.status, r.summary, "
            "r.attempt_count, r.max_attempts, r.retry_state, r.next_retry_at, "
            "r.last_failure_reason, r.active_attempt, r.last_progress_at, "
            "r.last_event_type, r.last_trace_id, r.terminal_reason, r.created_by, "
            "r.created_at, r.updated_at, b.title AS feature_title, b.approval_status "
            "FROM feature_request_build_runs r "
            "JOIN bug_reports b ON b.id=r.feature_id "
            "WHERE r.thread_id=? AND b.kind='feature' "
            "ORDER BY r.updated_at DESC LIMIT 1"
        ),
        (thread_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def reconcile_stale_feature_build_runs(
    conn: sqlite3.Connection,
    *,
    stale_after_seconds: int = 900,
    limit: int = 200,
    now: datetime | None = None,
) -> dict[str, object]:
    """Mark stale running feature-build runs as failed.

    A run is stale if its `updated_at` timestamp is older than `stale_after_seconds`.
    """
    threshold = max(1, int(stale_after_seconds))
    max_rows = max(1, int(limit))
    now_dt = now or datetime.now(UTC)
    cutoff = now_dt - timedelta(seconds=threshold)
    rows = conn.execute(
        (
            "SELECT id, updated_at, summary FROM feature_request_build_runs "
            "WHERE status='running' ORDER BY updated_at ASC LIMIT ?"
        ),
        (max_rows,),
    ).fetchall()

    reconciled_ids: list[str] = []
    for row in rows:
        stamp = str(row["updated_at"] or "")
        if not stamp:
            continue
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if dt.astimezone(UTC) > cutoff:
            continue
        run_id = str(row["id"])
        summary = str(row["summary"] or "").strip()
        if not summary:
            summary = (
                "Build run reconciled as failed after stale running timeout "
                f"({threshold}s)"
            )
        update_feature_build_run(conn, run_id, status="failed", summary=summary)
        reconciled_ids.append(run_id)

    return {
        "reconciled": len(reconciled_ids),
        "ids": reconciled_ids,
        "stale_after_seconds": threshold,
        "cutoff": cutoff.isoformat(),
    }


# ---------------------------------------------------------------------------
# Approval list / revoke helpers
# ---------------------------------------------------------------------------

def list_approvals(
    conn: sqlite3.Connection,
    *,
    action: str | None = None,
    status: str | None = None,
    target_ref: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, object]]:
    filters: list[str] = []
    params: list[object] = []
    if action:
        filters.append("action=?")
        params.append(action)
    if status:
        filters.append("status=?")
        params.append(status)
    if target_ref is not None:
        filters.append("target_ref=?")
        params.append(target_ref)
    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    rows = conn.execute(
        f"SELECT * FROM approvals{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def revoke_approval(conn: sqlite3.Connection, approval_id: str, *, actor_id: str) -> bool:
    """Mark an active approval as revoked. Returns True if updated."""
    row = conn.execute(
        "SELECT id, status FROM approvals WHERE id=? LIMIT 1",
        (approval_id,),
    ).fetchone()
    if row is None:
        return False
    if str(row["status"]) != "approved":
        return False
    conn.execute(
        "UPDATE approvals SET status='revoked', consumed_by_trace_id=? WHERE id=?",
        (f"revoked_by:{actor_id}", approval_id),
    )
    return True
