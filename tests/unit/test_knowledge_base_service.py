from jarvis.db.connection import get_conn
from jarvis.memory.knowledge import KnowledgeBaseService


def test_kb_put_list_search_and_get() -> None:
    kb = KnowledgeBaseService()
    with get_conn() as conn:
        first = kb.put(conn, title="spec", content="Use queue drain before restart")
        second = kb.put(conn, title="notes", content="Store snippets in the KB")
        listed = kb.list_docs(conn, limit=10)
        searched = kb.search(conn, query="queue restart", limit=5)
        got = kb.get(conn, first["id"])

    assert first["id"]
    assert second["id"]
    assert len(listed) >= 2
    assert searched
    assert got is not None
    assert got["title"] == "spec"


def test_kb_put_updates_existing_title() -> None:
    kb = KnowledgeBaseService()
    with get_conn() as conn:
        first = kb.put(conn, title="runbook", content="old")
        second = kb.put(conn, title="runbook", content="new")
        got = kb.get(conn, "runbook")

    assert first["id"] == second["id"]
    assert got is not None
    assert got["content"] == "new"
