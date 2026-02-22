import json
import sqlite3

import jarvis.tasks.memory as memory_tasks
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_thread,
    ensure_channel,
    ensure_user,
    now_iso,
    set_thread_agents,
)
from jarvis.tasks.memory import (
    evaluate_consistency,
    extract_thread_state,
    index_event,
    run_memory_maintenance,
    sync_failure_capsules,
)


def test_sync_failure_capsules_dedupes_and_links_to_trace_thread() -> None:
    with get_conn() as conn:
        user_id = ensure_user(conn, "15550010001")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = create_thread(conn, user_id, channel_id)
        trace_id = "trc_failure_sync_1"
        now = now_iso()
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, "
                "payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "evt_failure_sync_1",
                trace_id,
                "spn_failure_sync_1",
                None,
                thread_id,
                "agent.step.end",
                "orchestrator",
                "agent",
                "main",
                "{}",
                "{}",
                now,
            ),
        )
        for failure_id in ("flc_sync_1", "flc_sync_2"):
            conn.execute(
                (
                    "INSERT INTO failure_capsules("
                    "id, trace_id, phase, error_summary, error_details_json, attempt, created_at"
                    ") VALUES(?,?,?,?,?,?,?)"
                ),
                (
                    failure_id,
                    trace_id,
                    "planner",
                    "DNS timeout hitting provider",
                    json.dumps({"error_kind": "timeout", "provider": "gemini", "retryable": True}),
                    1,
                    now,
                ),
            )

    result = sync_failure_capsules()
    assert result["linked"] == 2
    assert result["deduped"] >= 1
    assert result["skipped_invalid"] == 0

    with get_conn() as conn:
        state_rows = conn.execute(
            "SELECT uid, thread_id, refs_json FROM state_items WHERE source='failure_bridge'"
        ).fetchall()
        link_rows = conn.execute(
            "SELECT failure_capsule_id, state_uid, thread_id "
            "FROM failure_state_links ORDER BY failure_capsule_id"
        ).fetchall()
    assert len(state_rows) == 1
    assert str(state_rows[0]["thread_id"]) != trace_id
    refs = json.loads(str(state_rows[0]["refs_json"]))
    assert refs["phase"] == "planner"
    assert refs["provider"] == "gemini"
    assert refs["timeout"] is True
    assert len(link_rows) == 2
    assert str(link_rows[0]["state_uid"]) == str(link_rows[1]["state_uid"])


def test_sync_failure_capsules_skips_unlinked_trace() -> None:
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO failure_capsules("
                "id, trace_id, phase, error_summary, error_details_json, attempt, created_at"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                "flc_unlinked_1",
                "trc_without_thread",
                "planner",
                "provider timeout",
                "{}",
                1,
                now_iso(),
            ),
        )
    result = sync_failure_capsules()
    assert result["linked"] == 0
    assert result["skipped_invalid"] == 1


def test_sync_failure_capsules_malformed_details_and_summary_payload() -> None:
    with get_conn() as conn:
        user_id = ensure_user(conn, "15550010003")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = create_thread(conn, user_id, channel_id)
        trace_id = "trc_failure_sync_bad_details"
        now = now_iso()
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "evt_failure_sync_bad_details",
                trace_id,
                "spn_failure_sync_bad_details",
                None,
                thread_id,
                "agent.step.end",
                "orchestrator",
                "agent",
                "main",
                "{}",
                "{}",
                now,
            ),
        )
        conn.execute(
            (
                "INSERT INTO failure_capsules("
                "id, trace_id, phase, error_summary, error_details_json, attempt, created_at"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                "flc_bad_details_1",
                trace_id,
                "executor",
                "dns timeout contacting provider",
                "{broken json",
                1,
                now,
            ),
        )

    result = sync_failure_capsules()
    assert result["linked"] == 1
    assert result["deduped"] == 0
    assert result["scanned"] >= 1

    with get_conn() as conn:
        state_row = conn.execute(
            "SELECT topic_tags_json FROM state_items WHERE source='failure_bridge' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        event_row = conn.execute(
            "SELECT payload_json FROM events WHERE event_type='memory.failure_bridge.sync' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert state_row is not None
    tags = json.loads(str(state_row["topic_tags_json"]))
    assert "timeout" in tags
    assert "dns_failure" in tags
    assert event_row is not None
    payload = json.loads(str(event_row["payload_json"]))
    assert int(payload["linked"]) == int(result["linked"])
    assert int(payload["linkage_count"]) == int(result["linked"])
    assert int(payload["scanned"]) >= int(result["linked"])


def test_sync_failure_capsules_skips_trace_thread_mismatch() -> None:
    with get_conn() as conn:
        user_id = ensure_user(conn, "15550010004")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_a = create_thread(conn, user_id, channel_id)
        thread_b = create_thread(conn, user_id, channel_id)
        trace_id = "trc_failure_sync_mismatch"
        now = now_iso()
        for event_id, thread_id in (
            ("evt_failure_sync_mm_1", thread_a),
            ("evt_failure_sync_mm_2", thread_b),
        ):
            conn.execute(
                (
                    "INSERT INTO events("
                    "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                    "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
                ),
                (
                    event_id,
                    trace_id,
                    f"spn_{event_id}",
                    None,
                    thread_id,
                    "agent.step.end",
                    "orchestrator",
                    "agent",
                    "main",
                    "{}",
                    "{}",
                    now,
                ),
            )
        conn.execute(
            (
                "INSERT INTO failure_capsules("
                "id, trace_id, phase, error_summary, error_details_json, attempt, created_at"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                "flc_sync_mismatch_1",
                trace_id,
                "planner",
                "provider timeout",
                "{}",
                1,
                now,
            ),
        )
    result = sync_failure_capsules()
    assert result["linked"] == 0
    assert result["skipped_invalid"] >= 1


def test_run_memory_maintenance_idempotent_summary_fields() -> None:
    # First run can clean historical rows; compare deterministic reruns after cleanup.
    _ = run_memory_maintenance()
    first = run_memory_maintenance()
    second = run_memory_maintenance()
    assert first["summary"] == second["summary"]
    for key in (
        "scanned",
        "promoted",
        "archived",
        "deduped",
        "skipped_invalid",
        "conflicts_detected",
    ):
        assert key in first["summary"]
        assert int(first["summary"][key]) >= 0

    with get_conn() as conn:
        run_row = conn.execute(
            "SELECT detail_json FROM state_reconciliation_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert run_row is not None
    details = json.loads(str(run_row["detail_json"]))
    assert set(details.keys()) == {
        "archived",
        "conflicts_detected",
        "deduped",
        "promoted",
        "scanned",
        "skipped_invalid",
    }


def test_extract_thread_state_emits_complete_event_and_trace_notification(monkeypatch) -> None:
    class _Result:
        items_extracted = 1
        items_merged = 0
        items_conflicted = 0
        items_dropped = 0
        duration_ms = 42
        skipped_reason = None

    async def _fake_extract_state_items(*_args, **_kwargs):
        return _Result()

    monkeypatch.setattr("jarvis.tasks.memory.extract_state_items", _fake_extract_state_items)

    with get_conn() as conn:
        user_id = ensure_user(conn, "15550010005")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = create_thread(conn, user_id, channel_id)

    payload = extract_thread_state(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_mem_extract_1",
    )
    assert int(payload["items_extracted"]) == 1

    with get_conn() as conn:
        event_row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE trace_id=? AND event_type='state.extraction.complete' "
            "ORDER BY created_at DESC LIMIT 1",
            ("trc_mem_extract_1",),
        ).fetchone()
        notif_row = conn.execute(
            "SELECT payload_json FROM web_notifications WHERE thread_id=? "
            "AND event_type='trace.state.extraction.complete' ORDER BY created_at DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
    assert event_row is not None
    assert notif_row is not None


def test_extract_thread_state_quota_cooldown_sets_skipped_reason(monkeypatch) -> None:
    async def _fake_extract_state_items(*_args, **_kwargs):
        raise RuntimeError(
            "gemini quota exceeded; skipping primary until 2026-02-22T14:38:35.570594+00:00 UTC"
        )

    monkeypatch.setattr("jarvis.tasks.memory.extract_state_items", _fake_extract_state_items)

    with get_conn() as conn:
        user_id = ensure_user(conn, "15550010006")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = create_thread(conn, user_id, channel_id)

    payload = extract_thread_state(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_mem_extract_2",
    )
    assert payload["primary_failure_kind"] == "quota_retryable"
    assert payload["skipped_reason"] == "provider_quota_cooldown"

    with get_conn() as conn:
        event_row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE trace_id=? AND event_type='state.extraction.failed' "
            "ORDER BY created_at DESC LIMIT 1",
            ("trc_mem_extract_2",),
        ).fetchone()
        notif_row = conn.execute(
            "SELECT payload_json FROM web_notifications WHERE thread_id=? "
            "AND event_type='trace.state.extraction.failed' ORDER BY created_at DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
    assert event_row is not None
    assert notif_row is not None


def test_extract_thread_state_backoff_skips_repeated_failures(monkeypatch) -> None:
    memory_tasks._STATE_EXTRACTION_BACKOFF.clear()

    async def _timeout_extract_state_items(*_args, **_kwargs):
        raise TimeoutError("state extractor timed out")

    monkeypatch.setattr("jarvis.tasks.memory.extract_state_items", _timeout_extract_state_items)

    with get_conn() as conn:
        user_id = ensure_user(conn, "15550010016")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = create_thread(conn, user_id, channel_id)

    first = extract_thread_state(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_mem_backoff_1",
    )
    second = extract_thread_state(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_mem_backoff_2",
    )
    assert first["primary_failure_kind"] == "timeout"
    assert int(first["retry_in_seconds"]) >= 1
    assert second["skipped_reason"] == "backoff_active"
    assert int(second["retry_in_seconds"]) >= 1

    with get_conn() as conn:
        skipped_row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE trace_id=? AND event_type='state.extraction.skipped' "
            "ORDER BY created_at DESC LIMIT 1",
            ("trc_mem_backoff_2",),
        ).fetchone()
    assert skipped_row is not None


def test_evaluate_consistency_persists_details_payload() -> None:
    with get_conn() as conn:
        user_id = ensure_user(conn, "15550010002")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = create_thread(conn, user_id, channel_id)
        now = now_iso()
        conn.execute(
            (
                "INSERT INTO state_items("
                "uid, thread_id, text, status, type_tag, topic_tags_json, refs_json, confidence, "
                "replaced_by, supersession_evidence, conflict, pinned, source, created_at, "
                "last_seen_at, updated_at, tier, "
                "importance_score, access_count, conflict_count, agent_id, last_accessed_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "st_consistency_1",
                thread_id,
                "conflicted state",
                "active",
                "decision",
                "[]",
                "[]",
                "medium",
                None,
                None,
                1,
                0,
                "extraction",
                now,
                now,
                now,
                "working",
                0.7,
                0,
                1,
                "main",
                now,
            ),
        )

    result = evaluate_consistency()
    assert int(result["threads"]) >= 1

    with get_conn() as conn:
        row = conn.execute(
            "SELECT details_json FROM memory_consistency_reports ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    details = json.loads(str(row["details_json"]))
    assert "conflict_ratio" in details
    assert details["computed_by"] == "tasks.memory.evaluate_consistency"


def test_index_event_denies_write_when_actor_scope_not_active() -> None:
    with get_conn() as conn:
        user_id = ensure_user(conn, "15550010009")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = create_thread(conn, user_id, channel_id)
        set_thread_agents(conn, thread_id, ["main"])

    memory_id = index_event(
        trace_id="trc_scope_denied",
        thread_id=thread_id,
        text="scoped note",
        metadata={"actor_id": "researcher", "source": "agent.step.end", "message_id": "msg_demo"},
    )
    assert memory_id == ""

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM memory_items WHERE thread_id=? ORDER BY created_at DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        audit = conn.execute(
            (
                "SELECT decision, reason FROM memory_governance_audit "
                "WHERE thread_id=? ORDER BY created_at DESC LIMIT 1"
            ),
            (thread_id,),
        ).fetchone()
    assert row is None
    assert audit is not None
    assert str(audit["decision"]) == "deny"
    assert str(audit["reason"]) == "agent_scope_denied"


def test_index_event_suppresses_vector_map_integrity_conflict(
    monkeypatch,
) -> None:
    with get_conn() as conn:
        user_id = ensure_user(conn, "15550010010")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = create_thread(conn, user_id, channel_id)

    def _raise_integrity(*_args, **_kwargs):
        raise sqlite3.IntegrityError(
            "UNIQUE constraint failed: memory_vec_index_map.memory_id"
        )

    monkeypatch.setattr(memory_tasks.MemoryService, "write_chunked", _raise_integrity)

    memory_id = index_event(
        trace_id="trc_vec_integrity_conflict",
        thread_id=thread_id,
        text="non-fatal conflict",
        metadata={"actor_id": "main", "source": "agent.thought"},
    )
    assert memory_id == ""
