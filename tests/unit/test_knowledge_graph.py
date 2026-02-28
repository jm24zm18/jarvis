from jarvis.db.connection import get_conn
from jarvis.memory.knowledge_graph import KnowledgeGraph


def test_knowledge_graph_confidence_gate_and_query() -> None:
    graph = KnowledgeGraph()
    with get_conn() as conn:
        skipped = graph.upsert_triple(
            conn,
            user_id="usr_test_kg",
            subject="Justin",
            predicate="uses",
            object_="TypeScript",
            confidence=0.6,
        )
        assert skipped is None
        kept = graph.upsert_triple(
            conn,
            user_id="usr_test_kg",
            subject="Justin",
            predicate="uses",
            object_="TypeScript",
            confidence=0.9,
            importance=8,
        )
        assert isinstance(kept, str)
        rows = graph.query(conn, user_id="usr_test_kg")
    assert len(rows) == 1
    assert rows[0]["predicate"] == "uses"


def test_knowledge_graph_supersedes_weaker_conflict() -> None:
    graph = KnowledgeGraph()
    with get_conn() as conn:
        old_id = graph.upsert_triple(
            conn,
            user_id="usr_test_kg2",
            subject="justin",
            predicate="uses",
            object_="TypeScript",
            confidence=0.8,
            importance=7,
        )
        assert old_id is not None
        new_id = graph.upsert_triple(
            conn,
            user_id="usr_test_kg2",
            subject="justin",
            predicate="uses",
            object_="Go",
            confidence=0.95,
            importance=8,
        )
        assert new_id is not None
        row = conn.execute(
            "SELECT superseded_by FROM knowledge_graph WHERE id=?",
            (old_id,),
        ).fetchone()
        active = graph.query(conn, user_id="usr_test_kg2", predicate="uses")
    assert row is not None
    assert row["superseded_by"] == new_id
    assert len(active) == 1
    assert active[0]["object"] == "Go"
