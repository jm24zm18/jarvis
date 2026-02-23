from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    ensure_channel,
    ensure_open_thread,
    ensure_user,
    insert_message,
    now_iso,
)
from jarvis.ids import new_id
from jarvis.tasks import followups


def _seed_enabled_followup_thread(channel_type: str = "web") -> str:
    with get_conn() as conn:
        user_id = ensure_user(conn, f"followup_{new_id('usr')}")
        channel_id = ensure_channel(conn, user_id, channel_type)
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "Any update?")
        conn.execute(
            (
                "INSERT INTO thread_followups("
                "thread_id, enabled, last_checked_at, last_sent_at, last_result, "
                "consecutive_no_reply, updated_at, created_at"
                ") VALUES(?,?,?,?,?,?,?,?)"
            ),
            (thread_id, 1, None, None, "no_reply", 0, now_iso(), now_iso()),
        )
    return thread_id


def test_followup_tick_no_reply(monkeypatch) -> None:
    thread_id = _seed_enabled_followup_thread()

    async def fake_eval(*_args, **_kwargs):
        return ("no_reply", "", "nothing_new", "primary")

    monkeypatch.setattr(followups, "_evaluate", fake_eval)
    monkeypatch.setenv("FOLLOWUP_MIN_IDLE_SECONDS", "0")
    monkeypatch.setenv("FOLLOWUP_MAX_THREADS_PER_TICK", "5")
    followups.get_settings.cache_clear()

    result = followups.followup_heartbeat_tick()
    assert result["ok"] is True
    assert result["no_reply"] >= 1

    with get_conn() as conn:
        row = conn.execute(
            (
                "SELECT last_result, consecutive_no_reply FROM thread_followups "
                "WHERE thread_id=?"
            ),
            (thread_id,),
        ).fetchone()
        assert row is not None
        assert str(row["last_result"]) == "no_reply"
        assert int(row["consecutive_no_reply"]) >= 1
        assistant_row = conn.execute(
            (
                "SELECT id FROM messages "
                "WHERE thread_id=? AND role='assistant' ORDER BY created_at DESC LIMIT 1"
            ),
            (thread_id,),
        ).fetchone()
        assert assistant_row is None


def test_followup_tick_reply_writes_message(monkeypatch) -> None:
    thread_id = _seed_enabled_followup_thread(channel_type="web")

    async def fake_eval(*_args, **_kwargs):
        return ("reply", "Here is a status update.", "progress", "fallback")

    monkeypatch.setattr(followups, "_evaluate", fake_eval)
    monkeypatch.setenv("FOLLOWUP_MIN_IDLE_SECONDS", "0")
    monkeypatch.setenv("FOLLOWUP_MAX_THREADS_PER_TICK", "5")
    followups.get_settings.cache_clear()

    result = followups.followup_heartbeat_tick()
    assert result["ok"] is True
    assert result["sent"] >= 1

    with get_conn() as conn:
        msg_row = conn.execute(
            (
                "SELECT role, content FROM messages WHERE thread_id=? AND role='assistant' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            (thread_id,),
        ).fetchone()
        assert msg_row is not None
        assert str(msg_row["role"]) == "assistant"
        assert "status update" in str(msg_row["content"])

        status_row = conn.execute(
            (
                "SELECT last_result, consecutive_no_reply, last_sent_at "
                "FROM thread_followups WHERE thread_id=?"
            ),
            (thread_id,),
        ).fetchone()
        assert status_row is not None
        assert str(status_row["last_result"]) == "reply"
        assert int(status_row["consecutive_no_reply"] or 0) == 0
        assert status_row["last_sent_at"] is not None


def test_followup_tick_skips_provider_when_no_enabled_threads(monkeypatch) -> None:
    async def fail_eval(*_args, **_kwargs):
        raise AssertionError("_evaluate should not be called when no followups are enabled")

    monkeypatch.setattr(followups, "_evaluate", fail_eval)
    monkeypatch.setenv("FOLLOWUP_EMIT_IDLE_TICKS", "0")
    followups.get_settings.cache_clear()

    result = followups.followup_heartbeat_tick()
    assert result["ok"] is True
    assert result["checked"] == 0
    assert result["sent"] == 0
