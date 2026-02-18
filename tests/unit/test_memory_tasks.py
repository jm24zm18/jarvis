import json

from jarvis.db.connection import get_conn
from jarvis.db.queries import create_thread, ensure_channel, ensure_user, now_iso
from jarvis.tasks.memory import evaluate_consistency, run_memory_maintenance, sync_failure_capsules


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
