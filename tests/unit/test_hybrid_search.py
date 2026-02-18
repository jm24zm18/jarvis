"""Tests for hybrid search (RRF fusion)."""

import time

from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_channel, ensure_open_thread, ensure_user
from jarvis.memory.service import MemoryService


def _make_thread(conn, suffix="1"):
    user_id = ensure_user(conn, f"test_hybrid_{suffix}")
    channel_id = ensure_channel(conn, user_id, "web")
    return ensure_open_thread(conn, user_id, channel_id)


def test_search_empty_returns_empty() -> None:
    svc = MemoryService()
    with get_conn() as conn:
        results = svc.search(conn, "nonexistent_thread", limit=5, query="test")
    assert results == []


def test_search_with_items_returns_results() -> None:
    svc = MemoryService()
    with get_conn() as conn:
        tid = _make_thread(conn, "items")
        svc.write(conn, tid, "Python is a great programming language")
        svc.write(conn, tid, "SQLite supports full-text search via FTS5")
        svc.write(conn, tid, "Vector databases enable semantic search")

        results = svc.search(conn, tid, limit=3, query="search")
    assert len(results) > 0
    assert all("id" in r and "text" in r for r in results)


def test_search_recency_only() -> None:
    svc = MemoryService()
    with get_conn() as conn:
        tid = _make_thread(conn, "recency")
        svc.write(conn, tid, "First item")
        svc.write(conn, tid, "Second item")

        # No query = recency only
        results = svc.search(conn, tid, limit=2)
    assert len(results) > 0


def test_search_custom_weights() -> None:
    svc = MemoryService()
    with get_conn() as conn:
        tid = _make_thread(conn, "weights")
        svc.write(conn, tid, "Custom weight test item")

        results = svc.search(
            conn, tid, limit=2, query="custom weight",
            vector_weight=0.0, bm25_weight=0.5, recency_weight=0.5,
        )
    assert len(results) > 0


def _seed_state_item(
    conn,
    *,
    uid: str,
    thread_id: str,
    text: str,
    tier: str,
    seen_at: str,
) -> None:
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
            uid,
            thread_id,
            text,
            "active",
            "decision",
            "[]",
            "[]",
            "high",
            None,
            None,
            0,
            0,
            "extraction",
            seen_at,
            seen_at,
            seen_at,
            tier,
            0.7,
            0,
            0,
            "main",
            seen_at,
        ),
    )


def test_search_state_tier_prior_changes_rrf_order(monkeypatch) -> None:
    svc = MemoryService()
    with get_conn() as conn:
        tid = _make_thread(conn, "state_tier")
        _seed_state_item(
            conn,
            uid="st_sem",
            thread_id=tid,
            text="alpha query semantic",
            tier="semantic_longterm",
            seen_at="2026-02-10T00:00:03+00:00",
        )
        _seed_state_item(
            conn,
            uid="st_epi",
            thread_id=tid,
            text="alpha query episodic",
            tier="episodic",
            seen_at="2026-02-10T00:00:02+00:00",
        )
        _seed_state_item(
            conn,
            uid="st_work",
            thread_id=tid,
            text="alpha query working",
            tier="working",
            seen_at="2026-02-10T00:00:01+00:00",
        )

        monkeypatch.setattr(MemoryService, "_embed_text_cached", lambda *args, **kwargs: [0.1, 0.2])
        monkeypatch.setattr(
            "jarvis.memory.state_store.StateStore.search_similar_items",
            lambda *args, **kwargs: [
                {
                    "uid": "st_sem",
                    "text": "alpha query semantic",
                    "status": "active",
                    "type_tag": "decision",
                    "topic_tags": [],
                    "score": 0.9,
                    "tier": "semantic_longterm",
                    "importance_score": 0.7,
                    "last_seen_at": "2026-02-10T00:00:03+00:00",
                    "confidence": "high",
                },
                {
                    "uid": "st_epi",
                    "text": "alpha query episodic",
                    "status": "active",
                    "type_tag": "decision",
                    "topic_tags": [],
                    "score": 0.8,
                    "tier": "episodic",
                    "importance_score": 0.7,
                    "last_seen_at": "2026-02-10T00:00:02+00:00",
                    "confidence": "high",
                },
                {
                    "uid": "st_work",
                    "text": "alpha query working",
                    "status": "active",
                    "type_tag": "decision",
                    "topic_tags": [],
                    "score": 0.7,
                    "tier": "working",
                    "importance_score": 0.7,
                    "last_seen_at": "2026-02-10T00:00:01+00:00",
                    "confidence": "high",
                },
            ],
        )

        results = svc.search_state(conn, tid, "alpha", k=3, min_score=0.0)
    assert [item["uid"] for item in results] == ["st_work", "st_epi", "st_sem"]


def test_search_state_order_is_stable_across_runs(monkeypatch) -> None:
    svc = MemoryService()
    with get_conn() as conn:
        tid = _make_thread(conn, "state_stable")
        for uid in ("st_work_a", "st_work_b"):
            _seed_state_item(
                conn,
                uid=uid,
                thread_id=tid,
                text="stable query item",
                tier="working",
                seen_at="2026-02-10T00:00:05+00:00",
            )
        monkeypatch.setattr(MemoryService, "_embed_text_cached", lambda *args, **kwargs: [0.1, 0.2])
        monkeypatch.setattr(
            "jarvis.memory.state_store.StateStore.search_similar_items",
            lambda *args, **kwargs: [
                {
                    "uid": "st_work_a",
                    "text": "stable query item",
                    "status": "active",
                    "type_tag": "decision",
                    "topic_tags": [],
                    "score": 0.9,
                    "tier": "working",
                    "importance_score": 0.7,
                    "last_seen_at": "2026-02-10T00:00:05+00:00",
                    "confidence": "high",
                },
                {
                    "uid": "st_work_b",
                    "text": "stable query item",
                    "status": "active",
                    "type_tag": "decision",
                    "topic_tags": [],
                    "score": 0.9,
                    "tier": "working",
                    "importance_score": 0.7,
                    "last_seen_at": "2026-02-10T00:00:05+00:00",
                    "confidence": "high",
                },
            ],
        )
        first = [item["uid"] for item in svc.search_state(conn, tid, "stable", k=2, min_score=0.0)]
        second = [item["uid"] for item in svc.search_state(conn, tid, "stable", k=2, min_score=0.0)]
    assert first == second
    assert first == ["st_work_a", "st_work_b"]


def test_search_state_retrieval_benchmark_smoke(monkeypatch) -> None:
    svc = MemoryService()
    with get_conn() as conn:
        tid = _make_thread(conn, "state_bench")
        for idx in range(50):
            _seed_state_item(
                conn,
                uid=f"st_bench_{idx:03d}",
                thread_id=tid,
                text=f"benchmark query item {idx}",
                tier="working" if idx % 2 == 0 else "episodic",
                seen_at=f"2026-02-10T00:00:{idx % 60:02d}+00:00",
            )
        monkeypatch.setattr(MemoryService, "_embed_text_cached", lambda *args, **kwargs: [0.1, 0.2])
        monkeypatch.setattr(
            "jarvis.memory.state_store.StateStore.search_similar_items",
            lambda *args, **kwargs: [],
        )

        t0 = time.perf_counter()
        result = svc.search_state(conn, tid, "benchmark", k=20, min_score=0.0)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert len(result) == 20
    assert elapsed_ms < 2000.0
