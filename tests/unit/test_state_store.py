import json

from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_channel, ensure_open_thread, ensure_system_state, ensure_user
from jarvis.memory.state_items import StateItem
from jarvis.memory.state_store import StateStore


def _seed_thread(conn) -> str:
    ensure_system_state(conn)
    user_id = ensure_user(conn, "15555550140")
    channel_id = ensure_channel(conn, user_id, "whatsapp")
    return ensure_open_thread(conn, user_id, channel_id)


def test_upsert_merge_roundtrip_and_last_seen_derivation() -> None:
    store = StateStore()
    with get_conn() as conn:
        thread_id = _seed_thread(conn)
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            ("msg_1", thread_id, "user", "Use redis", "2026-02-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            ("msg_2", thread_id, "user", "Keep ttl low", "2026-02-02T00:00:00+00:00"),
        )
        item = StateItem(
            uid="d_test1",
            text="Use redis for cache",
            status="active",
            type_tag="decision",
            topic_tags=["cache"],
            refs=["msg_1"],
            confidence="medium",
        )
        store.upsert_item(conn, thread_id, item)
        newer = StateItem(
            uid="d_test1",
            text="Use redis for cache",
            status="active",
            type_tag="decision",
            topic_tags=["cache", "performance"],
            refs=["msg_2"],
            confidence="high",
        )
        updated = store.upsert_item(conn, thread_id, newer)
    assert updated.confidence == "high"
    assert updated.topic_tags == ["cache", "performance"]
    assert "msg_1" in updated.refs and "msg_2" in updated.refs
    assert updated.last_seen_at == "2026-02-02T00:00:00+00:00"


def test_mark_superseded_and_active_filter() -> None:
    store = StateStore()
    with get_conn() as conn:
        thread_id = _seed_thread(conn)
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            ("msg_3", thread_id, "user", "Use postgres", "2026-02-03T00:00:00+00:00"),
        )
        store.upsert_item(
            conn,
            thread_id,
            StateItem(
                uid="d_old",
                text="Use sqlite",
                status="active",
                type_tag="decision",
                refs=["msg_3"],
                confidence="high",
            ),
        )
        store.mark_superseded(
            conn, "d_old", thread_id, "d_new", {"trigger": "instead", "ref_msg_id": "msg_3"}
        )
        active = store.get_active_items(conn, thread_id)
        row = conn.execute(
            "SELECT status, replaced_by, supersession_evidence FROM state_items "
            "WHERE uid='d_old' AND thread_id=?",
            (thread_id,),
        ).fetchone()
    assert active == []
    assert row is not None
    assert row["status"] == "superseded"
    assert row["replaced_by"] == "d_new"
    evidence = json.loads(str(row["supersession_evidence"]))
    assert evidence["trigger"] == "instead"


def test_watermark_tiebreaker_query() -> None:
    store = StateStore()
    with get_conn() as conn:
        thread_id = _seed_thread(conn)
        stamp = "2026-02-04T00:00:00+00:00"
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            ("msg_a", thread_id, "user", "one", stamp),
        )
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            ("msg_b", thread_id, "user", "two", stamp),
        )
        store.set_extraction_watermark(conn, thread_id, stamp, "msg_a")
        rows = store.get_new_messages_since(
            conn,
            thread_id,
            store.get_extraction_watermark(conn, thread_id),
            10,
        )
    assert [row["id"] for row in rows] == ["msg_b"]
