from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_channel, ensure_open_thread, ensure_system_state, ensure_user
from jarvis.tools.session import session_history, session_list, session_send


def test_session_send_and_history_roundtrip() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550125")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        session_id = ensure_open_thread(conn, user_id, channel_id)
        event_id = session_send(
            conn,
            session_id=session_id,
            to_agent_id="researcher",
            message="find references",
            trace_id="trc_session_1",
            from_agent_id="main",
        )
        sessions = session_list(conn, agent_id="researcher")
        history = session_history(conn, session_id, limit=20)
        delegate = conn.execute(
            "SELECT event_type FROM events WHERE id=?",
            (event_id,),
        ).fetchone()

    assert any(item["session_id"] == session_id for item in sessions)
    assert len(history) >= 1
    assert any("find references" in item["content"] for item in history)
    assert delegate is not None
    assert delegate["event_type"] == "agent.message"
