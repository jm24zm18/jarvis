from datetime import UTC, datetime, timedelta

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_feature_build_run,
    ensure_system_state,
    ensure_user,
    update_feature_build_run,
)
from jarvis.tasks.feature_build import (
    _build_attempt_capsule,
    _capsule_stable_hash,
    dispatch_due_feature_build_retries,
    get_previous_capsule,
    run_feature_build,
    save_capsule,
)


def test_run_feature_build_uses_current_thread_channel_schema(monkeypatch) -> None:
    queued: list[tuple[str, dict[str, object], str]] = []

    class _Runner:
        def send_task(self, name: str, kwargs: dict[str, object], queue: str) -> bool:
            queued.append((name, kwargs, queue))
            return True

    monkeypatch.setattr("jarvis.tasks.get_task_runner", lambda: _Runner())

    with get_conn() as conn:
        ensure_system_state(conn)
        actor_id = ensure_user(conn, "web_admin_feature_build")
        run_id = create_feature_build_run(conn, feature_id="bug_feature_build", created_by=actor_id)

    result = run_feature_build(
        run_id=run_id,
        feature_id="bug_feature_build",
        trace_id="trc_feature_build_1",
        title="Feature Build Thread Schema",
        actor_id=actor_id,
    )

    assert result["status"] == "running"
    assert queued
    assert queued[0][0] == "jarvis.tasks.agent.agent_step"

    with get_conn() as conn:
        row = conn.execute(
            "SELECT thread_id, status FROM feature_request_build_runs WHERE id=? LIMIT 1",
            (run_id,),
        ).fetchone()
        assert row is not None
        assert str(row["thread_id"])
        assert str(row["status"]) == "running"


def test_run_feature_build_marks_failed_on_internal_exception(monkeypatch) -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        actor_id = ensure_user(conn, "web_admin_feature_build_fail")
        run_id = create_feature_build_run(
            conn,
            feature_id="bug_feature_build_fail",
            created_by=actor_id,
        )

    def _explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("jarvis.tasks.feature_build.ensure_channel", _explode)

    result = run_feature_build(
        run_id=run_id,
        feature_id="bug_feature_build_fail",
        trace_id="trc_feature_build_fail",
        title="Feature Build Failure",
        actor_id=actor_id,
    )

    assert result["status"] == "failed"
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, summary FROM feature_request_build_runs WHERE id=? LIMIT 1",
            (run_id,),
        ).fetchone()
        assert row is not None
        assert str(row["status"]) == "failed"
        assert "RuntimeError: boom" in str(row["summary"])


def test_dispatch_due_feature_build_retries_enqueues_due_run(monkeypatch) -> None:
    queued: list[tuple[str, dict[str, object], str]] = []

    class _Runner:
        def send_task(self, name: str, kwargs: dict[str, object], queue: str) -> bool:
            queued.append((name, kwargs, queue))
            return True

    monkeypatch.setattr("jarvis.tasks.get_task_runner", lambda: _Runner())

    with get_conn() as conn:
        ensure_system_state(conn)
        actor_id = ensure_user(conn, "web_admin_feature_build_retry")
        now = datetime.now(UTC).isoformat()
        feature_id = "bug_feature_build_retry"
        conn.execute(
            (
                "INSERT INTO bug_reports"
                "(id, kind, title, description, status, priority, reporter_id, assignee_agent, "
                "thread_id, trace_id, github_issue_number, github_issue_url, github_synced_at, "
                "github_sync_error, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                feature_id,
                "feature",
                "Retry Feature",
                "",
                "open",
                "medium",
                actor_id,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                now,
                now,
            ),
        )
        run_id = create_feature_build_run(conn, feature_id=feature_id, created_by=actor_id)
        due_at = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
        update_feature_build_run(
            conn,
            run_id,
            status="running",
            retry_state="scheduled",
            next_retry_at=due_at,
            attempt_count=2,
            max_attempts=5,
            trace_id="trc_retry_dispatch_old",
        )

    result = dispatch_due_feature_build_retries(limit=20)
    assert int(result["attempted"]) >= 1
    assert int(result["dispatched"]) >= 1
    assert queued
    task_name, kwargs, queue = queued[0]
    assert task_name == "jarvis.tasks.feature_build.run_feature_build"
    assert str(kwargs["run_id"]) == run_id
    assert str(kwargs["feature_id"]) == feature_id
    assert str(kwargs["trace_id"]).startswith("trc_")
    assert queue == "default"


def test_capsule_saved_on_gate_failure_and_loaded_on_retry(monkeypatch) -> None:
    """Capsule is saved after a failed gate and loaded as context on the next attempt."""
    queued: list = []

    class _Runner:
        def send_task(self, name: str, kwargs: dict, queue: str) -> bool:
            queued.append((name, kwargs, queue))
            return True

    monkeypatch.setattr("jarvis.tasks.get_task_runner", lambda: _Runner())

    with get_conn() as conn:
        ensure_system_state(conn)
        actor_id = ensure_user(conn, "web_admin_capsule_saved")
        run_id = create_feature_build_run(
            conn, feature_id="bug_capsule_saved", created_by=actor_id
        )

        # Manually save a capsule on the run (simulating a prior gate failure).
        cap = _build_attempt_capsule(
            run_id=run_id,
            trace_id="trc_capsule_saved_1",
            attempt=1,
            reason="insufficient_deliverable_evidence",
            changed_files=[],
            tools_used=["exec_host"],
            top_errors=["test failed"],
            blockers_summary="Missing dep",
            next_action="retry",
        )
        save_capsule(conn, run_id, cap, _capsule_stable_hash(cap))

        # Bump attempt_count to 2 to simulate a retry scenario.
        update_feature_build_run(conn, run_id, attempt_count=2, max_attempts=5)

    # run_feature_build on attempt 2 should detect the capsule and inject a system message.
    result = run_feature_build(
        run_id=run_id,
        feature_id="bug_capsule_saved",
        trace_id="trc_capsule_saved_2",
        title="Capsule Saved Feature",
        actor_id=actor_id,
    )

    assert result["status"] == "running"

    # Verify the capsule still survives in the DB.
    with get_conn() as conn:
        loaded = get_previous_capsule(conn, run_id)
    assert loaded is not None
    assert loaded["reason"] == "insufficient_deliverable_evidence"
