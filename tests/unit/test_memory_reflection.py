"""Ensure the proactive reflection loop behaves as expected."""

from datetime import UTC, datetime, timedelta

from jarvis.db.connection import get_conn
from jarvis.db.queries import create_thread, ensure_channel, ensure_user, insert_message
from jarvis.memory.service import MemoryService
from jarvis.memory.state_items import StateItem
from jarvis.memory.state_store import StateStore
from jarvis.tasks.memory import proactive_reflection


def _create_open_thread(conn):
    user_id = ensure_user(conn, "15550020001")
    channel_id = ensure_channel(conn, user_id, "whatsapp")
    thread_id = create_thread(conn, user_id, channel_id)
    return thread_id


def test_reflection_candidates_honor_watermarks():
    with get_conn() as conn:
        thread_id = _create_open_thread(conn)
        first_msg = insert_message(conn, thread_id, "user", "initial activity")
        past_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        conn.execute(
            "UPDATE messages SET created_at=? WHERE id=?",
            (past_ts, first_msg),
        )
        service = MemoryService()
        rows = service.get_reflection_candidates(conn, limit=5)
        assert any(row["thread_id"] == thread_id for row in rows)
        conn.execute(
            (
                "INSERT INTO memory_reflection_watermarks("
                "thread_id, last_reflected_at, created_at, updated_at"
                ") VALUES(?,?,?,?)"
            ),
            (thread_id, past_ts, past_ts, past_ts),
        )
        next_msg = insert_message(conn, thread_id, "user", "new activity")
        now_ts = datetime.now(UTC).isoformat()
        conn.execute(
            "UPDATE messages SET created_at=? WHERE id=?",
            (now_ts, next_msg),
        )
        rows = service.get_reflection_candidates(conn, limit=5)
        assert any(row["thread_id"] == thread_id for row in rows)


def test_proactive_reflection_generates_worldview_and_auto_prunes():
    with get_conn() as conn:
        thread_id = _create_open_thread(conn)
        message_id = insert_message(conn, thread_id, "user", "context message")
        store = StateStore()
        item = StateItem(
            uid="",
            text="Important decision",
            status="active",
            type_tag="decision",
            topic_tags=["plan"],
            refs=[message_id],
            confidence="high",
        )
        stored = store.upsert_item(conn, thread_id, item)
        # hard-code a stale row that should be pruned by reflection
        stale = StateItem(
            uid="",
            text="Old low importance fact",
            status="active",
            type_tag="decision",
            topic_tags=["history"],
            refs=[message_id],
            confidence="low",
        )
        stale_row = store.upsert_item(conn, thread_id, stale)
        stale_ts = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        conn.execute(
            "UPDATE state_items SET importance_score=0.1, last_seen_at=?, updated_at=? WHERE uid=?",
            (stale_ts, stale_ts, stale_row.uid),
        )
    result = proactive_reflection()
    assert result["ok"]
    with get_conn() as conn:
        worldview = conn.execute(
            "SELECT COUNT(*) AS n FROM state_items WHERE thread_id=? AND type_tag='worldview'",
            (thread_id,),
        ).fetchone()
        assert worldview and worldview["n"] >= 1
        insight = conn.execute(
            "SELECT COUNT(*) AS n FROM state_items WHERE thread_id=? AND type_tag='insight'",
            (thread_id,),
        ).fetchone()
        assert insight and insight["n"] >= 1
        pruned = conn.execute(
            "SELECT COUNT(*) AS n FROM state_items WHERE uid=?", (stale_row.uid,)
        ).fetchone()
        assert pruned and pruned["n"] == 0
        watermark = conn.execute(
            "SELECT last_insight_count, last_pruned_count FROM memory_reflection_watermarks WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
        assert watermark["last_insight_count"] >= 1
        assert watermark["last_pruned_count"] >= 1
