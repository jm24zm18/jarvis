import json

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_human_escalation,
    ensure_channel,
    ensure_open_thread,
    ensure_user,
    insert_message,
    now_iso,
)
from jarvis.ids import new_id
from jarvis.tools.thread_logs import summarize_thread_logs


def _seed_thread(conn) -> str:
    user_id = ensure_user(conn, "user_thread_logs")
    channel_id = ensure_channel(conn, user_id, "web")
    thread_id = ensure_open_thread(conn, user_id, channel_id)
    return thread_id


def test_summarize_thread_logs_includes_recent_activity() -> None:
    with get_conn() as conn:
        thread_id = _seed_thread(conn)
        insert_message(conn, thread_id, "user", "first message")
        insert_message(conn, thread_id, "assistant", "assistant reply")
        event_id = new_id("evt")
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, "
                "component, actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                event_id,
                new_id("trc"),
                new_id("spn"),
                None,
                thread_id,
                "agent.test.event",
                "agent",
                "agent",
                "main",
                json.dumps({"reason": "testing"}),
                json.dumps({"reason": "testing"}),
                now_iso(),
            ),
        )
        escalation_id = create_human_escalation(
            conn,
            thread_id=thread_id,
            trace_id=new_id("trc"),
            requested_by_actor_id="main",
            source_agent_id="main",
            reason="test_reason",
            message="human review required",
            channel_type="web",
            target_external_id="usr_admin",
        )
        summary = summarize_thread_logs(conn, thread_id)

    assert summary["thread_id"] == thread_id
    assert summary["message_count"] == 2
    assert summary["recent_messages"][0]["content"].startswith("assistant reply")
    assert summary["recent_events"][0]["event_type"] == "agent.test.event"
    assert summary["human_escalations"][0]["id"] == escalation_id
    assert summary["human_escalation_counts"].get("queued") == 1
