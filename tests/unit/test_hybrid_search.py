"""Tests for hybrid search (RRF fusion)."""

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
