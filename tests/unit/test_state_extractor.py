import asyncio

from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_channel, ensure_open_thread, ensure_system_state, ensure_user
from jarvis.memory.state_extractor import extract_state_items
from jarvis.memory.state_items import StateItem
from jarvis.memory.state_store import StateStore
from jarvis.providers.base import ModelResponse


class _Router:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def generate(self, *_args, **_kwargs):
        self.calls += 1
        return ModelResponse(text=self.text, tool_calls=[]), "primary", None


class _Memory:
    def embed_text(self, text: str) -> list[float]:
        lowered = text.lower()
        if "memcached" in lowered:
            return [0.86, 0.5]
        if "redis" in lowered:
            return [1.0, 0.0]
        if "postgres" in lowered:
            return [0.0, 1.0]
        return [0.1, 0.1]


def _seed_thread(conn, external_id: str) -> str:
    ensure_system_state(conn)
    user_id = ensure_user(conn, external_id)
    channel_id = ensure_channel(conn, user_id, "whatsapp")
    return ensure_open_thread(conn, user_id, channel_id)


def test_extractor_skips_without_new_messages() -> None:
    with get_conn() as conn:
        thread_id = _seed_thread(conn, "15555550150")
        store = StateStore()
        store.set_extraction_watermark(conn, thread_id, "2026-02-01T00:00:00+00:00", "msg_x")
        result = asyncio.run(
            extract_state_items(conn, thread_id=thread_id, router=_Router("[]"), memory=_Memory())
        )
    assert result.skipped_reason == "no_new_messages"


def test_extractor_validates_refs_and_advances_watermark() -> None:
    router = _Router(
        '[{"type_tag":"decision","text":"Use Redis","status":"active","confidence":"high",'
        '"topic_tags":["cache"],"refs":["msg_missing"],"supersedes":null,"conflict":false}]'
    )
    with get_conn() as conn:
        thread_id = _seed_thread(conn, "15555550151")
        store = StateStore()
        base_stamp = "2026-02-01T00:00:00+00:00"
        store.set_extraction_watermark(conn, thread_id, base_stamp, "msg_0")
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            ("msg_1", thread_id, "user", "Use Redis", "2026-02-02T00:00:00+00:00"),
        )
        result = asyncio.run(
            extract_state_items(conn, thread_id=thread_id, router=router, memory=_Memory())
        )
        watermark = store.get_extraction_watermark(conn, thread_id)
        rows = conn.execute(
            "SELECT uid FROM state_items WHERE thread_id=?",
            (thread_id,),
        ).fetchall()
    assert result.items_dropped == 1
    assert rows == []
    assert watermark == ("2026-02-02T00:00:00+00:00", "msg_1")


def test_extractor_merges_on_high_similarity() -> None:
    router = _Router(
        '[{"type_tag":"decision","text":"Use Redis for caching","status":"active",'
        '"confidence":"high","topic_tags":["cache"],"refs":["msg_2"],'
        '"supersedes":null,"conflict":false}]'
    )
    with get_conn() as conn:
        thread_id = _seed_thread(conn, "15555550152")
        store = StateStore()
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            ("msg_1", thread_id, "user", "Use Redis", "2026-02-01T00:00:00+00:00"),
        )
        store.upsert_item(
            conn,
            thread_id,
            StateItem(
                uid="d_old",
                text="Use Redis for caching",
                status="active",
                type_tag="decision",
                topic_tags=["cache"],
                refs=["msg_1"],
                confidence="medium",
            ),
        )
        store.upsert_item_embedding(conn, "d_old", thread_id, [1.0, 0.0])
        store.set_extraction_watermark(conn, thread_id, "2026-02-01T00:00:00+00:00", "msg_1")
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            ("msg_2", thread_id, "user", "Use Redis for caching", "2026-02-02T00:00:00+00:00"),
        )
        result = asyncio.run(
            extract_state_items(conn, thread_id=thread_id, router=router, memory=_Memory())
        )
        items = store.get_active_items(conn, thread_id, limit=10)
    assert result.items_merged == 1
    assert len(items) == 1
    assert items[0].uid == "d_old"
    assert "msg_2" in items[0].refs


def test_extractor_supersedes_with_guardrails() -> None:
    router = _Router(
        '[{"type_tag":"decision","text":"Switch to Memcached instead of Redis","status":"active",'
        '"confidence":"high","topic_tags":["cache"],"refs":["msg_3"],'
        '"supersedes":"d_old","conflict":false}]'
    )
    with get_conn() as conn:
        thread_id = _seed_thread(conn, "15555550153")
        store = StateStore()
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            ("msg_1", thread_id, "user", "Use Redis", "2026-02-01T00:00:00+00:00"),
        )
        store.upsert_item(
            conn,
            thread_id,
            StateItem(
                uid="d_old",
                text="Use Redis for caching",
                status="active",
                type_tag="decision",
                topic_tags=["cache"],
                refs=["msg_1"],
                confidence="high",
            ),
        )
        store.upsert_item_embedding(conn, "d_old", thread_id, [1.0, 0.0])
        store.set_extraction_watermark(conn, thread_id, "2026-02-01T00:00:00+00:00", "msg_1")
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            (
                "msg_3",
                thread_id,
                "user",
                "Switch to Memcached instead",
                "2026-02-02T00:00:00+00:00",
            ),
        )
        _ = asyncio.run(
            extract_state_items(conn, thread_id=thread_id, router=router, memory=_Memory())
        )
        old_row = conn.execute(
            "SELECT status, replaced_by, supersession_evidence FROM state_items "
            "WHERE thread_id=? AND uid='d_old'",
            (thread_id,),
        ).fetchone()
    assert old_row is not None
    assert old_row["status"] == "superseded"
    assert old_row["replaced_by"] is not None
    assert "instead" in str(old_row["supersession_evidence"])
