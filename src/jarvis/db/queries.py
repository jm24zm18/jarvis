"""Core query helpers used by routes/tasks."""

import json
import sqlite3
from datetime import UTC, datetime

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
    row = conn.execute(
        (
            "SELECT id FROM threads "
            "WHERE user_id=? AND channel_id=? AND status='open' "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        (user_id, channel_id),
    ).fetchone()
    if row:
        return str(row["id"])
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


def insert_message(conn: sqlite3.Connection, thread_id: str, role: str, content: str) -> str:
    message_id = new_id("msg")
    conn.execute(
        "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
        (message_id, thread_id, role, content, now_iso()),
    )
    conn.execute("UPDATE threads SET updated_at=? WHERE id=?", (now_iso(), thread_id))
    return message_id


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
    conn: sqlite3.Connection, action: str, actor_id: str, status: str = "approved"
) -> str:
    approval_id = new_id("apr")
    conn.execute(
        (
            "INSERT INTO approvals(id, action, actor_id, status, created_at) "
            "VALUES(?,?,?,?,?)"
        ),
        (approval_id, action, actor_id, status, now_iso()),
    )
    return approval_id


def consume_approval(conn: sqlite3.Connection, action: str) -> bool:
    row = conn.execute(
        (
            "SELECT id FROM approvals "
            "WHERE action=? AND status='approved' "
            "ORDER BY created_at ASC LIMIT 1"
        ),
        (action,),
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE approvals SET status='consumed' WHERE id=?",
        (str(row["id"]),),
    )
    return True


def get_whatsapp_outbound(
    conn: sqlite3.Connection, thread_id: str, message_id: str
) -> dict[str, str] | None:
    return get_channel_outbound(conn, thread_id, message_id, "whatsapp")


def get_channel_outbound(
    conn: sqlite3.Connection, thread_id: str, message_id: str, channel_type: str
) -> dict[str, str] | None:
    row = conn.execute(
        (
            "SELECT u.external_id AS recipient, m.content AS text "
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
    return {"recipient": str(row["recipient"]), "text": str(row["text"])}
