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


def test_knowledge_graph_extraction_type_filter_and_user_scope() -> None:
    graph = KnowledgeGraph()
    with get_conn() as conn:
        profile_id = graph.upsert_triple(
            conn,
            user_id="usr_test_kg3",
            subject="next.js app router",
            predicate="uses",
            object_="server actions",
            confidence=0.9,
            extraction_type="profile",
        )
        task_id = graph.upsert_triple(
            conn,
            user_id="usr_test_kg3",
            subject="next.js app router",
            predicate="best_practice_for",
            object_="wrap server action mutations in try/catch",
            confidence=0.92,
            extraction_type="task_lesson",
            source_trace_id="trc_kg_scope_1",
        )
        other_user_id = graph.upsert_triple(
            conn,
            user_id="usr_test_kg4",
            subject="next.js app router",
            predicate="best_practice_for",
            object_="wrap server action mutations in try/catch",
            confidence=0.91,
            extraction_type="task_lesson",
            source_trace_id="trc_kg_scope_2",
        )
        task_rows = graph.query(
            conn,
            user_id="usr_test_kg3",
            extraction_type="task_lesson",
        )
        profile_rows = graph.query(
            conn,
            user_id="usr_test_kg3",
            extraction_type="profile",
        )
    assert profile_id is not None
    assert task_id is not None
    assert other_user_id is not None
    assert task_id != other_user_id
    assert len(task_rows) == 1
    assert task_rows[0]["extraction_type"] == "task_lesson"
    assert task_rows[0]["source_trace_id"] == "trc_kg_scope_1"
    assert task_rows[0]["extracted_at"] is not None
    assert len(profile_rows) == 1
    assert profile_rows[0]["extraction_type"] == "profile"
