"""Event retention/maintenance task."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id


def run_event_maintenance() -> dict[str, object]:
    """Delete events older than EVENT_RETENTION_DAYS and prune orphaned index records."""
    settings = get_settings()
    retention_days = max(1, int(settings.event_retention_days))
    cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()

    with get_conn() as conn:
        # Fetch event IDs to be deleted (for index cleanup).
        old_event_rows = conn.execute(
            "SELECT id FROM events WHERE created_at < ? LIMIT 10000",
            (cutoff,),
        ).fetchall()
        old_ids = [str(row["id"]) for row in old_event_rows]

        deleted_events = 0
        deleted_text = 0
        deleted_vec = 0

        if old_ids:
            placeholders = ",".join("?" * len(old_ids))
            # Prune FTS and vector index rows before deleting base events.
            conn.execute(
                f"DELETE FROM event_fts WHERE rowid IN "
                f"(SELECT rowid FROM event_fts WHERE memory_id IN ({placeholders}))",
                old_ids,
            )
            result = conn.execute(
                f"DELETE FROM event_text WHERE event_id IN ({placeholders})",
                old_ids,
            )
            deleted_text = result.rowcount if result.rowcount >= 0 else 0
            result = conn.execute(
                f"DELETE FROM event_vec WHERE id IN ({placeholders})",
                old_ids,
            )
            deleted_vec = result.rowcount if result.rowcount >= 0 else 0
            result = conn.execute(
                f"DELETE FROM events WHERE id IN ({placeholders})",
                old_ids,
            )
            deleted_events = result.rowcount if result.rowcount >= 0 else 0

        trace_id = new_id("trc")
        payload = {
            "retention_days": retention_days,
            "cutoff": cutoff,
            "deleted_events": deleted_events,
            "deleted_text_rows": deleted_text,
            "deleted_vec_rows": deleted_vec,
        }
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=None,
                event_type="maintenance.events.pruned",
                component="tasks.events",
                actor_type="system",
                actor_id="maintenance",
                payload_json=__import__("json").dumps(payload),
                payload_redacted_json=__import__("json").dumps(redact_payload(payload)),
            ),
        )

    return {"ok": True, **payload}
