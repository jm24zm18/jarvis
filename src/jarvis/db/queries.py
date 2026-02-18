"""Core query helpers used by routes/tasks."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

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


def get_thread_by_whatsapp_remote(
    conn: sqlite3.Connection, instance: str, remote_jid: str
) -> str | None:
    row = conn.execute(
        "SELECT thread_id FROM whatsapp_thread_map WHERE instance=? AND remote_jid=? LIMIT 1",
        (instance, remote_jid),
    ).fetchone()
    return str(row["thread_id"]) if row is not None else None


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


def upsert_whatsapp_instance(
    conn: sqlite3.Connection,
    *,
    instance: str,
    status: str,
    metadata: dict[str, object] | None = None,
) -> None:
    now = now_iso()
    conn.execute(
        (
            "INSERT INTO whatsapp_instances("
            "instance, status, last_seen_at, metadata_json, created_at, updated_at"
            ") VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(instance) DO UPDATE SET "
            "status=excluded.status, last_seen_at=excluded.last_seen_at, "
            "metadata_json=excluded.metadata_json, updated_at=excluded.updated_at"
        ),
        (instance, status, now, json.dumps(metadata or {}, sort_keys=True), now, now),
    )


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
