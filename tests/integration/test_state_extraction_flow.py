import asyncio

from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_channel, ensure_open_thread, ensure_system_state, ensure_user
from jarvis.memory.state_extractor import extract_state_items
from jarvis.memory.state_store import StateStore
from jarvis.providers.base import ModelResponse


class _Router:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *_args, **_kwargs):
        self.calls += 1
        return (
            ModelResponse(
                text=(
                    '[{"type_tag":"decision","text":"Use PostgreSQL for analytics",'
                    '"status":"active",'
                    '"confidence":"high","topic_tags":["analytics"],"refs":["msg_2"],'
                    '"supersedes":null,"conflict":false}]'
                ),
                tool_calls=[],
            ),
            "primary",
            None,
        )


class _Memory:
    def embed_text(self, _text: str) -> list[float]:
        return [0.2, 0.8]


def test_state_extraction_flow_watermark_and_tiebreaker() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550160")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        store = StateStore()
        router = _Router()

        same_stamp = "2026-02-06T00:00:00+00:00"
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            ("msg_1", thread_id, "user", "Hello", same_stamp),
        )
        first = asyncio.run(
            extract_state_items(conn, thread_id=thread_id, router=router, memory=_Memory())
        )
        assert first.skipped_reason == "bootstrap"
        assert router.calls == 0

        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            ("msg_2", thread_id, "user", "Use PostgreSQL for analytics", same_stamp),
        )
        second = asyncio.run(
            extract_state_items(conn, thread_id=thread_id, router=router, memory=_Memory())
        )
        assert second.items_extracted == 1
        assert router.calls == 1

        third = asyncio.run(
            extract_state_items(conn, thread_id=thread_id, router=router, memory=_Memory())
        )
        assert third.skipped_reason == "no_new_messages"
        assert router.calls == 1

        watermark = store.get_extraction_watermark(conn, thread_id)
        row = conn.execute(
            "SELECT uid, thread_id FROM state_items WHERE thread_id=? LIMIT 1",
            (thread_id,),
        ).fetchone()
    assert watermark == (same_stamp, "msg_2")
    assert row is not None
