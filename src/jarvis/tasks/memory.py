"""Memory/indexing Celery tasks."""

from jarvis.celery_app import celery_app
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.memory.service import MemoryService


@celery_app.task(name="jarvis.tasks.memory.index_event")
def index_event(trace_id: str, thread_id: str, text: str) -> str:
    del trace_id
    service = MemoryService()
    with get_conn() as conn:
        return service.write(conn, thread_id, text)


@celery_app.task(name="jarvis.tasks.memory.compact_thread")
def compact_thread(thread_id: str) -> dict[str, str]:
    service = MemoryService()
    with get_conn() as conn:
        return service.compact_thread(conn, thread_id)


@celery_app.task(name="jarvis.tasks.memory.periodic_compaction")
def periodic_compaction() -> dict[str, int]:
    """Compact all threads that have accumulated messages since last compaction."""
    settings = get_settings()
    threshold = settings.compaction_every_n_events
    service = MemoryService()
    compacted = 0
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT t.id AS thread_id, "
            "COUNT(m.id) AS msg_count, "
            "COALESCE(ts.updated_at, '1970-01-01') AS last_compact "
            "FROM threads t "
            "JOIN messages m ON m.thread_id=t.id "
            "LEFT JOIN thread_summaries ts ON ts.thread_id=t.id "
            "WHERE m.created_at > COALESCE(ts.updated_at, '1970-01-01') "
            "GROUP BY t.id "
            "HAVING COUNT(m.id) >= ? "
            "LIMIT 20",
            (threshold,),
        ).fetchall()
        for row in rows:
            service.compact_thread(conn, str(row["thread_id"]))
            compacted += 1
    return {"compacted": compacted}
