"""Memory/indexing Celery tasks."""
# ruff: noqa: E501

from datetime import UTC, datetime, timedelta

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import now_iso
from jarvis.ids import new_id
from jarvis.memory.service import MemoryService


def index_event(
    trace_id: str,
    thread_id: str,
    text: str,
    metadata: dict[str, object] | None = None,
) -> str:
    del trace_id
    service = MemoryService()
    with get_conn() as conn:
        ids = service.write_chunked(conn, thread_id, text, metadata=metadata)
    return ids[0] if ids else ""


def compact_thread(thread_id: str) -> dict[str, str]:
    service = MemoryService()
    with get_conn() as conn:
        return service.compact_thread(conn, thread_id)


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


def run_memory_maintenance() -> dict[str, object]:
    settings = get_settings()
    retention_days = max(1, int(settings.memory_retention_days))
    stale_before = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
    summary: dict[str, int] = {
        "pruned_memory_items": 0,
        "pruned_state_items": 0,
        "deduped_memory_items": 0,
        "demoted_state_items": 0,
    }

    with get_conn() as conn:
        has_archive = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_items_archive'"
            ).fetchone()
            is not None
        )
        has_state_archive = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='state_items_archive'"
            ).fetchone()
            is not None
        )
        # Prune old memory items plus associated indexes.
        old_memory = conn.execute(
            "SELECT id, thread_id, text, metadata_json, created_at FROM memory_items WHERE created_at<?",
            (stale_before,),
        ).fetchall()
        old_memory_ids = [str(row["id"]) for row in old_memory]
        if old_memory_ids:
            if has_archive:
                archived_at = now_iso()
                for row in old_memory:
                    conn.execute(
                        (
                            "INSERT OR IGNORE INTO memory_items_archive("
                            "id, thread_id, text, metadata_json, created_at, archived_at, archive_reason"
                            ") VALUES(?,?,?,?,?,?,?)"
                        ),
                        (
                            str(row["id"]),
                            str(row["thread_id"]),
                            str(row["text"]),
                            str(row["metadata_json"]),
                            str(row["created_at"]),
                            archived_at,
                            "retention",
                        ),
                    )
            placeholders = ",".join("?" for _ in old_memory_ids)
            conn.execute(
                f"DELETE FROM memory_embeddings WHERE memory_id IN ({placeholders})",
                tuple(old_memory_ids),
            )
            conn.execute(
                f"DELETE FROM memory_vec WHERE memory_id IN ({placeholders})",
                tuple(old_memory_ids),
            )
            conn.execute(
                f"DELETE FROM memory_vec_index_map WHERE memory_id IN ({placeholders})",
                tuple(old_memory_ids),
            )
            conn.execute(
                f"DELETE FROM memory_fts WHERE memory_id IN ({placeholders})",
                tuple(old_memory_ids),
            )
            conn.execute(
                f"DELETE FROM memory_items WHERE id IN ({placeholders})",
                tuple(old_memory_ids),
            )
            summary["pruned_memory_items"] = len(old_memory_ids)

        # Prune stale state entries that are unpinned and already superseded.
        deleted_state = conn.execute(
            (
                "SELECT uid, thread_id, text, status, type_tag, topic_tags_json, refs_json, "
                "confidence, replaced_by, supersession_evidence, conflict, pinned, source, "
                "created_at, last_seen_at, updated_at, tier, importance_score, access_count, "
                "conflict_count, agent_id, last_accessed_at "
                "FROM state_items WHERE pinned=0 AND status='superseded' AND last_seen_at<?"
            ),
            (stale_before,),
        ).fetchall()
        if deleted_state:
            if has_state_archive:
                archived_at = now_iso()
                for row in deleted_state:
                    conn.execute(
                        (
                            "INSERT INTO state_items_archive("
                            "uid, thread_id, text, status, type_tag, topic_tags_json, refs_json, "
                            "confidence, replaced_by, supersession_evidence, conflict, pinned, source, "
                            "created_at, last_seen_at, updated_at, tier, importance_score, access_count, "
                            "conflict_count, agent_id, last_accessed_at, archived_at, archive_reason"
                            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                        ),
                        (
                            str(row["uid"]),
                            str(row["thread_id"]),
                            str(row["text"]),
                            str(row["status"]),
                            str(row["type_tag"]),
                            str(row["topic_tags_json"]),
                            str(row["refs_json"]),
                            str(row["confidence"]),
                            str(row["replaced_by"]) if row["replaced_by"] is not None else None,
                            (
                                str(row["supersession_evidence"])
                                if row["supersession_evidence"] is not None
                                else None
                            ),
                            int(row["conflict"]),
                            int(row["pinned"]),
                            str(row["source"]),
                            str(row["created_at"]),
                            str(row["last_seen_at"]),
                            str(row["updated_at"]),
                            str(row["tier"]),
                            float(row["importance_score"]),
                            int(row["access_count"]),
                            int(row["conflict_count"]),
                            str(row["agent_id"]),
                            (
                                str(row["last_accessed_at"])
                                if row["last_accessed_at"] is not None
                                else None
                            ),
                            archived_at,
                            "superseded_stale",
                        ),
                    )
            conn.execute(
                (
                    "DELETE FROM state_items WHERE pinned=0 AND status='superseded' AND "
                    "last_seen_at<?"
                ),
                (stale_before,),
            )
        summary["pruned_state_items"] = len(deleted_state)

        # Demote stale active/open items by lowering confidence.
        demoted = conn.execute(
            (
                "UPDATE state_items SET confidence='low', updated_at=? "
                "WHERE pinned=0 AND status IN ('active','open') AND confidence!='low' "
                "AND last_seen_at<?"
            ),
            (now_iso(), stale_before),
        ).rowcount
        summary["demoted_state_items"] = int(demoted or 0)

        # Remove duplicate memory rows by (thread_id, text), keeping newest.
        duplicates = conn.execute(
            "SELECT m1.id FROM memory_items m1 "
            "WHERE EXISTS ("
            "SELECT 1 FROM memory_items m2 "
            "WHERE m2.thread_id=m1.thread_id AND m2.text=m1.text "
            "AND (m2.created_at>m1.created_at OR (m2.created_at=m1.created_at AND m2.id>m1.id))"
            ")"
        ).fetchall()
        dup_ids = [str(row["id"]) for row in duplicates]
        if dup_ids:
            placeholders = ",".join("?" for _ in dup_ids)
            conn.execute(
                f"DELETE FROM memory_embeddings WHERE memory_id IN ({placeholders})",
                tuple(dup_ids),
            )
            conn.execute(
                f"DELETE FROM memory_vec WHERE memory_id IN ({placeholders})",
                tuple(dup_ids),
            )
            conn.execute(
                f"DELETE FROM memory_vec_index_map WHERE memory_id IN ({placeholders})",
                tuple(dup_ids),
            )
            conn.execute(
                f"DELETE FROM memory_fts WHERE memory_id IN ({placeholders})",
                tuple(dup_ids),
            )
            conn.execute(
                f"DELETE FROM memory_items WHERE id IN ({placeholders})",
                tuple(dup_ids),
            )
            summary["deduped_memory_items"] = len(dup_ids)

        conn.execute(
            (
                "INSERT INTO state_reconciliation_runs("
                "id, scope, stale_before, updated_count, superseded_count, deduped_count, "
                "pruned_count, detail_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?)"
            ),
            (
                new_id("rec"),
                "global",
                stale_before,
                summary["demoted_state_items"],
                0,
                summary["deduped_memory_items"],
                summary["pruned_memory_items"] + summary["pruned_state_items"],
                "{}",
                now_iso(),
            ),
        )

    return {
        "ok": True,
        "retention_days": retention_days,
        "stale_before": stale_before,
        "summary": summary,
    }


def migrate_tiers() -> dict[str, int]:
    settings = get_settings()
    if int(settings.memory_tiers_enabled) != 1:
        return {"moved": 0}
    moved = 0
    now = datetime.now(UTC)
    with get_conn() as conn:
        rows = conn.execute(
            
                "SELECT uid, thread_id, tier, pinned, status, importance_score, last_seen_at, access_count "
                "FROM state_items"
            
        ).fetchall()
        for row in rows:
            current = str(row["tier"])
            pinned = int(row["pinned"]) == 1
            last_seen = datetime.fromisoformat(str(row["last_seen_at"]))
            age_days = (now - last_seen).total_seconds() / 86400.0
            importance = float(row["importance_score"])
            access_count = int(row["access_count"])
            target = current
            if pinned:
                target = "procedural"
            elif importance >= 0.75 or access_count >= 10:
                target = "semantic_longterm"
            elif age_days <= 14:
                target = "working"
            elif age_days <= 60:
                target = "episodic"
            else:
                target = "semantic_longterm"
            if target != current:
                conn.execute(
                    "UPDATE state_items SET tier=?, updated_at=? WHERE uid=? AND thread_id=?",
                    (target, now_iso(), str(row["uid"]), str(row["thread_id"])),
                )
                moved += 1
    return {"moved": moved}


def prune_adaptive() -> dict[str, int]:
    settings = get_settings()
    if int(settings.memory_importance_enabled) != 1:
        return {"archived": 0}
    archived = 0
    with get_conn() as conn:
        cutoff = (datetime.now(UTC) - timedelta(days=max(1, int(settings.memory_retention_days)))).isoformat()
        has_archive = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='state_items_archive'"
            ).fetchone()
            is not None
        )
        if not has_archive:
            return {"archived": 0}
        rows = conn.execute(
            (
                "SELECT uid, thread_id, text, status, type_tag, topic_tags_json, refs_json, confidence, "
                "replaced_by, supersession_evidence, conflict, pinned, source, created_at, last_seen_at, "
                "updated_at, tier, importance_score, access_count, conflict_count, agent_id, last_accessed_at "
                "FROM state_items WHERE pinned=0 AND importance_score<0.35 AND last_seen_at<?"
            ),
            (cutoff,),
        ).fetchall()
        for row in rows:
            conn.execute(
                (
                    "INSERT INTO state_items_archive("
                    "uid, thread_id, text, status, type_tag, topic_tags_json, refs_json, confidence, "
                    "replaced_by, supersession_evidence, conflict, pinned, source, created_at, last_seen_at, "
                    "updated_at, tier, importance_score, access_count, conflict_count, agent_id, "
                    "last_accessed_at, archived_at, archive_reason"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                ),
                (
                    str(row["uid"]),
                    str(row["thread_id"]),
                    str(row["text"]),
                    str(row["status"]),
                    str(row["type_tag"]),
                    str(row["topic_tags_json"]),
                    str(row["refs_json"]),
                    str(row["confidence"]),
                    str(row["replaced_by"]) if row["replaced_by"] is not None else None,
                    str(row["supersession_evidence"]) if row["supersession_evidence"] is not None else None,
                    int(row["conflict"]),
                    int(row["pinned"]),
                    str(row["source"]),
                    str(row["created_at"]),
                    str(row["last_seen_at"]),
                    str(row["updated_at"]),
                    str(row["tier"]),
                    float(row["importance_score"]),
                    int(row["access_count"]),
                    int(row["conflict_count"]),
                    str(row["agent_id"]),
                    str(row["last_accessed_at"]) if row["last_accessed_at"] is not None else None,
                    now_iso(),
                    "adaptive_low_importance",
                ),
            )
            conn.execute(
                "DELETE FROM state_items WHERE uid=? AND thread_id=?",
                (str(row["uid"]), str(row["thread_id"])),
            )
            archived += 1
    return {"archived": archived}


def sync_failure_capsules() -> dict[str, int]:
    settings = get_settings()
    if int(settings.memory_failure_bridge_enabled) != 1:
        return {"linked": 0}
    linked = 0
    with get_conn() as conn:
        rows = conn.execute(
            
                "SELECT fc.id, fc.trace_id, fc.phase, fc.error_summary, fc.created_at "
                "FROM failure_capsules fc "
                "LEFT JOIN failure_state_links fsl ON fsl.failure_capsule_id=fc.id "
                "WHERE fsl.failure_capsule_id IS NULL "
                "ORDER BY fc.created_at DESC LIMIT 200"
            
        ).fetchall()
        for row in rows:
            uid = f"f_{str(row['id'])[-12:]}"
            conn.execute(
                (
                    "INSERT INTO state_items("
                    "uid, thread_id, text, status, type_tag, topic_tags_json, refs_json, confidence, "
                    "replaced_by, supersession_evidence, conflict, pinned, source, created_at, "
                    "last_seen_at, updated_at, tier, importance_score, access_count, conflict_count, "
                    "agent_id, last_accessed_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(uid, thread_id) DO NOTHING"
                ),
                (
                    uid,
                    str(row["trace_id"]),
                    str(row["error_summary"]),
                    "open",
                    "failure",
                    '[\"failure\"]',
                    "[]",
                    "medium",
                    None,
                    None,
                    0,
                    0,
                    "failure_bridge",
                    str(row["created_at"]),
                    str(row["created_at"]),
                    now_iso(),
                    "episodic",
                    0.65,
                    0,
                    0,
                    "main",
                    None,
                ),
            )
            conn.execute(
                (
                    "INSERT OR IGNORE INTO failure_state_links("
                    "failure_capsule_id, state_uid, thread_id, agent_id, created_at"
                    ") VALUES(?,?,?,?,?)"
                ),
                (str(row["id"]), uid, str(row["trace_id"]), "main", now_iso()),
            )
            linked += 1
    return {"linked": linked}


def evaluate_consistency() -> dict[str, object]:
    service = MemoryService()
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM threads ORDER BY updated_at DESC LIMIT 50").fetchall()
        reports: list[dict[str, object]] = []
        for row in rows:
            report = service.evaluate_consistency(conn, thread_id=str(row["id"]), sample_size=50)
            reports.append(report)
            conn.execute(
                (
                    "INSERT INTO memory_consistency_reports("
                    "id, thread_id, sample_size, total_items, conflicted_items, consistency_score, "
                    "details_json, created_at"
                    ") VALUES(?,?,?,?,?,?,?,?)"
                ),
                (
                    new_id("mcr"),
                    str(report["thread_id"]),
                    int(report["sample_size"]),
                    int(report["total_items"]),
                    int(report["conflicted_items"]),
                    float(report["consistency_score"]),
                    "{}",
                    now_iso(),
                ),
            )
    if not reports:
        return {"threads": 0, "avg_consistency": 1.0}
    avg = sum(float(item["consistency_score"]) for item in reports) / len(reports)
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                new_id("evt"),
                new_id("trc"),
                new_id("spn"),
                None,
                None,
                "memory.reconcile.summary",
                "memory",
                "system",
                "memory_maintenance",
                f'{{\"threads\": {len(reports)}, \"avg_consistency\": {avg}}}',
                f'{{\"threads\": {len(reports)}, \"avg_consistency\": {avg}}}',
                now_iso(),
            ),
        )
    return {"threads": len(reports), "avg_consistency": avg}
