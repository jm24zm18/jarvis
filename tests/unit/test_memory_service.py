import json
import os

import pytest

from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_channel, ensure_open_thread, ensure_system_state, ensure_user
from jarvis.memory.service import MemoryService


def test_compact_thread_persists_summaries() -> None:
    service = MemoryService()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        conn.execute(
            (
                "INSERT INTO messages("
                "id, thread_id, role, content, created_at"
                ") VALUES(?,?,?,?,datetime('now'))"
            ),
            ("msg_1", thread_id, "user", "hello"),
        )
        conn.execute(
            (
                "INSERT INTO messages("
                "id, thread_id, role, content, created_at"
                ") VALUES(?,?,?,?,datetime('now'))"
            ),
            ("msg_2", thread_id, "assistant", "world"),
        )
        result = service.compact_thread(conn, thread_id)
        summary = service.thread_summary(conn, thread_id)
    assert result["thread_id"] == thread_id
    assert "hello" in summary["short"] or "world" in summary["short"]


def test_semantic_search_prefers_closest_embedding(monkeypatch) -> None:
    service = MemoryService()

    def fake_embed(text: str) -> list[float]:
        if "alpha" in text:
            return [1.0, 0.0]
        if "beta" in text:
            return [0.0, 1.0]
        return [1.0, 0.0]

    monkeypatch.setattr(service, "_embed_text", fake_embed)

    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550124")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        _ = service.write(conn, thread_id, "alpha memory")
        _ = service.write(conn, thread_id, "beta memory")
        results = service.search(conn, thread_id, limit=2, query="find alpha")
    assert len(results) == 2
    assert results[0]["text"] == "alpha memory"


def test_write_persists_metadata_json() -> None:
    service = MemoryService()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550125")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        memory_id = service.write(
            conn,
            thread_id,
            "assistant found critical info",
            metadata={"role": "assistant", "source": "agent.step.end"},
        )
        row = conn.execute(
            "SELECT metadata_json FROM memory_items WHERE id=?",
            (memory_id,),
        ).fetchone()
    assert row is not None
    assert row["metadata_json"] == '{"role": "assistant", "source": "agent.step.end"}'


def test_write_chunked_splits_large_payload_and_sets_chunk_metadata() -> None:
    service = MemoryService()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550135")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        ids = service.write_chunked(
            conn,
            thread_id,
            "abcdefghij",
            metadata={"source": "tool.call.end"},
            chunk_size=4,
        )
        rows = conn.execute(
            (
                "SELECT id, text, metadata_json FROM memory_items "
                "WHERE thread_id=? ORDER BY created_at ASC"
            ),
            (thread_id,),
        ).fetchall()
    assert len(ids) == 3
    assert len(rows) == 3
    assert "".join(str(row["text"]) for row in rows) == "abcdefghij"
    parsed = [json.loads(str(row["metadata_json"])) for row in rows]
    assert all(item["source"] == "tool.call.end" for item in parsed)
    assert all(item["is_chunked"] is True for item in parsed)
    assert [int(item["chunk_index"]) for item in parsed] == [0, 1, 2]
    assert all(int(item["chunk_total"]) == 3 for item in parsed)


def test_search_stitches_chunked_group_and_deduplicates_results() -> None:
    service = MemoryService()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550136")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        _ = service.write_chunked(
            conn,
            thread_id,
            "chunked-memory-text",
            metadata={"source": "agent.thought"},
            chunk_size=6,
        )
        results = service.search(conn, thread_id=thread_id, limit=10)
    assert results
    assert results[0]["text"] == "chunked-memory-text"


def test_backfill_memory_vec_runtime_from_embeddings() -> None:
    service = MemoryService()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users(id, external_id, created_at) VALUES(?,?,datetime('now'))",
            ("usr_a", "u_a"),
        )
        conn.execute(
            (
                "INSERT INTO channels(id, user_id, channel_type, created_at) "
                "VALUES(?,?,?,datetime('now'))"
            ),
            ("chn_a", "usr_a", "whatsapp"),
        )
        conn.execute(
            (
                "INSERT INTO threads(id, user_id, channel_id, status, created_at, updated_at) "
                "VALUES(?,?,?,'open',datetime('now'),datetime('now'))"
            ),
            ("thr_a", "usr_a", "chn_a"),
        )
        conn.execute(
            (
                "INSERT INTO memory_items(id, thread_id, text, metadata_json, created_at) "
                "VALUES(?,?,?,?,datetime('now'))"
            ),
            ("mem_a", "thr_a", "alpha", "{}",),
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS memory_vec_index(rowid INTEGER PRIMARY KEY, embedding TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS memory_vec_index_map("
            "vec_rowid INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT UNIQUE NOT NULL)"
        )
        conn.execute(
            (
                "INSERT INTO memory_embeddings(memory_id, model, vector_json, created_at) "
                "VALUES(?,?,?,datetime('now'))"
            ),
            ("mem_a", "nomic-embed-text", "[0.1, 0.2]"),
        )
        service._backfill_memory_vec_runtime(conn)
        row = conn.execute(
            "SELECT m.memory_id, idx.embedding "
            "FROM memory_vec_index_map m JOIN memory_vec_index idx ON idx.rowid=m.vec_rowid "
            "WHERE m.memory_id='mem_a'"
        ).fetchone()
    assert row is not None
    assert row["memory_id"] == "mem_a"


def test_backfill_event_vec_runtime_from_legacy_table() -> None:
    service = MemoryService()
    with get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS event_vec_index(rowid INTEGER PRIMARY KEY, embedding TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS event_vec_index_map("
            "vec_rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_id TEXT UNIQUE NOT NULL, thread_id TEXT)"
        )
        conn.execute(
            (
                "INSERT INTO event_vec(id, thread_id, vector_json, created_at) "
                "VALUES(?,?,?,datetime('now'))"
            ),
            ("evt_a", "thr_a", "[0.3, 0.7]"),
        )
        service._backfill_event_vec_runtime(conn)
        row = conn.execute(
            "SELECT m.event_id, m.thread_id, idx.embedding "
            "FROM event_vec_index_map m JOIN event_vec_index idx ON idx.rowid=m.vec_rowid "
            "WHERE m.event_id='evt_a'"
        ).fetchone()
    assert row is not None
    assert row["event_id"] == "evt_a"
    assert row["thread_id"] == "thr_a"


def test_sqlite_vec_round_trip_search_when_runtime_available(monkeypatch) -> None:
    service = MemoryService()
    os.environ["MEMORY_EMBED_DIMS"] = "2"
    from jarvis.config import get_settings

    get_settings.cache_clear()
    try:
        with get_conn() as conn:
            ensure_system_state(conn)
            if not service.ensure_vector_indexes(conn):
                pytest.skip("sqlite-vec runtime unavailable")

            user_id = ensure_user(conn, "15555550999")
            channel_id = ensure_channel(conn, user_id, "whatsapp")
            thread_id = ensure_open_thread(conn, user_id, channel_id)

            def fake_embed(text: str) -> list[float]:
                if "alpha" in text:
                    return [1.0, 0.0]
                return [0.0, 1.0]

            monkeypatch.setattr(service, "_embed_text", fake_embed)
            _ = service.write(conn, thread_id, "alpha memory")
            _ = service.write(conn, thread_id, "beta memory")
            rows = service._search_memory_vec_index(conn, thread_id, [1.0, 0.0], 1)
        assert rows
        assert rows[0]["text"] == "alpha memory"
    finally:
        get_settings.cache_clear()


def test_get_failures_and_consistency_report() -> None:
    service = MemoryService()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550998")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        conn.execute(
            (
                "INSERT INTO failure_capsules("
                "id, trace_id, phase, error_summary, error_details_json, attempt, created_at"
                ") VALUES(?,?,?,?,?,?,datetime('now'))"
            ),
            ("fcp_1", "trc_1", "test", "socket timeout while deploying", "{}", 1),
        )
        conn.execute(
            (
                "INSERT INTO state_items("
                "uid, thread_id, text, status, type_tag, topic_tags_json, refs_json, confidence, "
                "replaced_by, supersession_evidence, conflict, pinned, source, created_at, "
                "last_seen_at, updated_at, tier, importance_score, access_count, conflict_count, "
                "agent_id, last_accessed_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "d_consistency",
                thread_id,
                "Use redis",
                "active",
                "decision",
                "[]",
                "[]",
                "high",
                None,
                None,
                1,
                0,
                "test",
                "2026-02-01T00:00:00+00:00",
                "2026-02-01T00:00:00+00:00",
                "2026-02-01T00:00:00+00:00",
                "working",
                0.5,
                0,
                1,
                "main",
                None,
            ),
        )
        failures = service.get_failures(conn, similar_to="timeout", k=5)
        report = service.evaluate_consistency(conn, thread_id=thread_id, sample_size=10)
    assert failures
    assert failures[0]["id"] == "fcp_1"
    assert report["thread_id"] == thread_id
    assert report["conflicted_items"] == 1


def test_graph_traverse_returns_edges() -> None:
    service = MemoryService()
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO state_relations("
                "id, source_uid, target_uid, thread_id, agent_id, relation_type, confidence, "
                "evidence_json, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))"
            ),
            ("rel_1", "d_a", "d_b", "thr_1", "main", "enables", 0.8, "{}"),
        )
        conn.execute(
            (
                "INSERT INTO state_relations("
                "id, source_uid, target_uid, thread_id, agent_id, relation_type, confidence, "
                "evidence_json, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))"
            ),
            ("rel_2", "d_b", "d_c", "thr_1", "main", "constrains", 0.8, "{}"),
        )
        graph = service.graph_traverse(conn, uid="d_a", depth=2)
    assert graph["root_uid"] == "d_a"
    assert len(graph["edges"]) >= 2
