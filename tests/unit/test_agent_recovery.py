import json
from datetime import UTC, datetime, timedelta

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_feature_build_run,
    ensure_channel,
    ensure_open_thread,
    ensure_system_state,
    ensure_user,
    insert_message,
    now_iso,
    update_feature_build_run,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.tasks.agent import _git_changed_files, agent_step
from jarvis.tasks.agent_attempts import start_attempt
from jarvis.tasks.agent_recovery import reap_stale_agent_runs


class _StubRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], str | None]] = []

    def send_task(
        self,
        name: str,
        kwargs: dict[str, object] | None = None,
        queue: str | None = None,
    ) -> bool:
        self.calls.append((name, kwargs or {}, queue))
        return True


def test_agent_step_retries_and_records_attempt_lifecycle(monkeypatch) -> None:
    calls = {"count": 0}

    async def fake_run_agent_step(*_args, **kwargs) -> str:
        calls["count"] += 1
        notify_fn = kwargs.get("notify_fn")
        progress_fn = kwargs.get("progress_fn")
        if callable(progress_fn):
            progress_fn("phase", {"phase": "model.run", "iteration": calls["count"]})
        if callable(notify_fn):
            notify_fn("model.run.start", {"iteration": calls["count"]})
        if calls["count"] == 1:
            raise TimeoutError("simulated timeout")
        return "msg_recovered"

    monkeypatch.setattr("jarvis.tasks.agent.run_agent_step", fake_run_agent_step)
    monkeypatch.setattr("jarvis.tasks.agent.time.sleep", lambda *_args, **_kwargs: None)

    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550999")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "check retry")

    trace_id = "trc_retry_lifecycle"
    message_id = agent_step(trace_id=trace_id, thread_id=thread_id, actor_id="main")
    assert message_id == "msg_recovered"
    assert calls["count"] == 2

    with get_conn() as conn:
        rows = conn.execute(
            (
                "SELECT attempt, status, failure_kind, final_message_id "
                "FROM agent_run_attempts WHERE trace_id=? ORDER BY attempt"
            ),
            (trace_id,),
        ).fetchall()
        notifications = conn.execute(
            "SELECT event_type FROM web_notifications WHERE thread_id=? ORDER BY id",
            (thread_id,),
        ).fetchall()

    assert [int(row["attempt"]) for row in rows] == [1, 2]
    assert [str(row["status"]) for row in rows] == ["failed", "succeeded"]
    assert str(rows[0]["failure_kind"]) == "timeout"
    assert str(rows[1]["final_message_id"]) == "msg_recovered"

    event_types = {str(row["event_type"]) for row in notifications}
    assert "trace.agent.step.retried" in event_types
    assert "trace.agent.step.end" in event_types


def test_reaper_marks_stale_and_requeues_attempt(monkeypatch) -> None:
    runner = _StubRunner()
    monkeypatch.setattr("jarvis.tasks.get_task_runner", lambda: runner)

    trace_id = "trc_stale_recover"
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550888")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        start_attempt(
            conn,
            trace_id=trace_id,
            thread_id=thread_id,
            actor_id="main",
            attempt=1,
        )
        stale_at = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
        conn.execute(
            (
                "UPDATE agent_run_attempts SET phase='model.run', started_at=?, "
                "last_heartbeat_at=? WHERE trace_id=? AND attempt=1"
            ),
            (stale_at, stale_at, trace_id),
        )

    result = reap_stale_agent_runs()
    assert result["stale"] == 1
    assert result["recovered"] == 1
    assert result["exhausted"] == 0

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, failure_kind FROM agent_run_attempts WHERE trace_id=? AND attempt=1",
            (trace_id,),
        ).fetchone()
        recovered_note = conn.execute(
            (
                "SELECT payload_json FROM web_notifications "
                "WHERE thread_id=? AND event_type='trace.agent.step.recovered' "
                "ORDER BY id DESC LIMIT 1"
            ),
            (thread_id,),
        ).fetchone()

    assert row is not None
    assert str(row["status"]) == "abandoned"
    assert str(row["failure_kind"]) == "stale_timeout"
    assert recovered_note is not None
    payload = json.loads(str(recovered_note["payload_json"]))


def test_git_changed_files_subtracts_baseline(monkeypatch) -> None:
    class FakeProc:
        returncode = 0
        stdout = "foo.txt\nbar.txt\n"
        stderr = ""

    monkeypatch.setattr(
        "jarvis.tasks.agent.subprocess.run",
        lambda *args, **kwargs: FakeProc(),
    )
    files, err = _git_changed_files(baseline={"foo.txt"})
    assert err is None
    assert files == ["bar.txt"]


def _insert_feature(conn) -> str:
    feature_id = new_id("bug")
    now = now_iso()
    conn.execute(
        (
            "INSERT INTO bug_reports"
            "(id, kind, title, description, status, priority, "
            "reporter_id, assignee_agent, thread_id, trace_id, "
            "github_issue_number, github_issue_url, github_synced_at, github_sync_error, "
            "created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        (
            feature_id,
            "feature",
            "Feature Build",
            "",
            "open",
            "medium",
            "usr_test",
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
    return feature_id


def test_agent_step_finalizes_feature_build_run_succeeded(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_BUILD_DELIVERABLE_GATE_ENABLED", "0")
    get_settings.cache_clear()

    async def fake_run_agent_step(*, conn, thread_id, **_kwargs) -> str:
        return insert_message(conn, thread_id, "assistant", "Build completed successfully.")

    monkeypatch.setattr("jarvis.tasks.agent.run_agent_step", fake_run_agent_step)

    trace_id = "trc_build_finalize_success"
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550777")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "build it")
        fid = _insert_feature(conn)
        run_id = create_feature_build_run(
            conn,
            feature_id=fid,
            created_by=user_id,
            trace_id=trace_id,
            thread_id=thread_id,
        )
        update_feature_build_run(conn, run_id, status="running")

    agent_step(trace_id=trace_id, thread_id=thread_id, actor_id="main")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, summary FROM feature_request_build_runs WHERE id=?",
            (run_id,),
        ).fetchone()
    get_settings.cache_clear()
    assert row is not None
    assert str(row["status"]) == "succeeded"
    assert "completed successfully" in str(row["summary"]).lower()


def test_agent_step_finalizes_feature_build_run_failed_on_degraded(monkeypatch) -> None:
    async def fake_run_agent_step(*, conn, thread_id, trace_id, **_kwargs) -> str:
        message_id = insert_message(
            conn,
            thread_id,
            "assistant",
            (
                "I hit an internal response issue while processing that request. "
                f"Please try again. (ref: {trace_id})"
            ),
        )
        payload = {"reason": "placeholder_response_after_terminal_synthesis", "actor_id": "main"}
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="agent.response.degraded",
                component="orchestrator",
                actor_type="agent",
                actor_id="main",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )
        return message_id

    monkeypatch.setattr("jarvis.tasks.agent.run_agent_step", fake_run_agent_step)

    trace_id = "trc_build_finalize_failed"
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550778")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "build it")
        fid = _insert_feature(conn)
        run_id = create_feature_build_run(
            conn,
            feature_id=fid,
            created_by=user_id,
            trace_id=trace_id,
            thread_id=thread_id,
        )
        update_feature_build_run(conn, run_id, status="running")

    agent_step(trace_id=trace_id, thread_id=thread_id, actor_id="main")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, summary, attempt_count, retry_state, next_retry_at, "
            "last_failure_reason "
            "FROM feature_request_build_runs WHERE id=?",
            (run_id,),
        ).fetchone()
    assert row is not None
    assert str(row["status"]) == "running"
    assert str(row["retry_state"]) == "scheduled"
    assert int(row["attempt_count"]) == 2
    assert str(row["next_retry_at"]).strip()
    assert (
        str(row["last_failure_reason"]).strip()
        == "placeholder_response_after_terminal_synthesis"
    )
    assert "retry scheduled" in str(row["summary"]).lower()


def test_agent_step_finalizes_feature_build_run_failed_when_retry_disabled(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_BUILD_RETRY_ON_DEGRADED", "0")
    get_settings.cache_clear()

    async def fake_run_agent_step(*, conn, thread_id, trace_id, **_kwargs) -> str:
        return insert_message(
            conn,
            thread_id,
            "assistant",
            (
                "I hit an internal response issue while processing that request. "
                f"Please try again. (ref: {trace_id})"
            ),
        )

    monkeypatch.setattr("jarvis.tasks.agent.run_agent_step", fake_run_agent_step)

    trace_id = "trc_build_finalize_failed_no_retry"
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550779")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "build it")
        fid = _insert_feature(conn)
        run_id = create_feature_build_run(
            conn,
            feature_id=fid,
            created_by=user_id,
            trace_id=trace_id,
            thread_id=thread_id,
        )
        update_feature_build_run(conn, run_id, status="running")

    agent_step(trace_id=trace_id, thread_id=thread_id, actor_id="main")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, summary, retry_state FROM feature_request_build_runs WHERE id=?",
            (run_id,),
        ).fetchone()
    get_settings.cache_clear()
    assert row is not None
    assert str(row["status"]) == "failed"
    assert str(row["retry_state"]) == "none"
    assert "terminal response" in str(row["summary"]).lower()


def test_agent_step_feature_build_deliverable_gate_fails_without_diff(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_BUILD_RETRY_ON_DEGRADED", "0")
    monkeypatch.setenv("FEATURE_BUILD_DELIVERABLE_GATE_ENABLED", "1")
    get_settings.cache_clear()
    def fake_capture_dirty_files_snapshot() -> tuple[set[str], str | None]:
        return {"existing/file.txt"}, None

    def fake_git_changed_files(baseline: set[str] | None = None) -> tuple[list[str], str | None]:
        assert baseline == {"existing/file.txt"}
        return [], None

    monkeypatch.setattr(
        "jarvis.tasks.agent._capture_dirty_files_snapshot",
        fake_capture_dirty_files_snapshot,
    )
    monkeypatch.setattr("jarvis.tasks.agent._git_changed_files", fake_git_changed_files)

    async def fake_run_agent_step(*, conn, thread_id, **_kwargs) -> str:
        return insert_message(conn, thread_id, "assistant", "Implemented all requested changes.")

    monkeypatch.setattr("jarvis.tasks.agent.run_agent_step", fake_run_agent_step)

    trace_id = "trc_build_deliverable_gate_fail"
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550780")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "build it")
        fid = _insert_feature(conn)
        run_id = create_feature_build_run(
            conn,
            feature_id=fid,
            created_by=user_id,
            trace_id=trace_id,
            thread_id=thread_id,
        )
        update_feature_build_run(conn, run_id, status="running")

    agent_step(trace_id=trace_id, thread_id=thread_id, actor_id="main")

    with get_conn() as conn:
        row = conn.execute(
            (
                "SELECT status, summary, retry_state, terminal_reason "
                "FROM feature_request_build_runs WHERE id=?"
            ),
            (run_id,),
        ).fetchone()
        gate_evt = conn.execute(
            (
                "SELECT payload_json FROM events WHERE trace_id=? "
                "AND event_type='feature.build.deliverable_gate.failed' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            (trace_id,),
        ).fetchone()
        synthesis_evt = conn.execute(
            (
                "SELECT payload_json FROM events WHERE trace_id=? "
                "AND event_type='feature.build.terminal_synthesis' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            (trace_id,),
        ).fetchone()
        attempt_row = conn.execute(
            (
                "SELECT initial_dirty_files FROM agent_run_attempts "
                "WHERE trace_id=? ORDER BY attempt DESC LIMIT 1"
            ),
            (trace_id,),
        ).fetchone()
    get_settings.cache_clear()

    assert row is not None
    assert str(row["status"]) == "failed"
    assert str(row["retry_state"]) == "none"
    assert str(row["terminal_reason"]) == "insufficient_deliverable_evidence"
    assert "insufficient_deliverable_evidence" in str(row["summary"])
    assert gate_evt is not None
    gate_payload = json.loads(str(gate_evt["payload_json"]))
    assert gate_payload["reason"] == "insufficient_deliverable_evidence"
    assert synthesis_evt is not None
    synthesis_payload = json.loads(str(synthesis_evt["payload_json"]))
    assert synthesis_payload["reason"] == "insufficient_deliverable_evidence"
    assert synthesis_payload["deliverable_passed"] is False
    assert attempt_row is not None
    assert json.loads(str(attempt_row["initial_dirty_files"])) == ["existing/file.txt"]


def test_agent_step_feature_build_fail_fast_on_repeated_placeholder_reason(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_BUILD_RETRY_ON_DEGRADED", "1")
    monkeypatch.setenv("FEATURE_BUILD_FAIL_FAST_PLACEHOLDER_REPEAT", "1")
    get_settings.cache_clear()

    async def fake_run_agent_step(*, conn, thread_id, trace_id, **_kwargs) -> str:
        message_id = insert_message(
            conn,
            thread_id,
            "assistant",
            (
                "I completed tool execution but could not synthesize a final summary. "
                f"Trace: {trace_id}. Review /admin/events for details and retry."
            ),
        )
        payload = {"reason": "placeholder_response_after_tool_loop", "actor_id": "main"}
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="agent.response.degraded",
                component="orchestrator",
                actor_type="agent",
                actor_id="main",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )
        return message_id

    monkeypatch.setattr("jarvis.tasks.agent.run_agent_step", fake_run_agent_step)

    trace_id = "trc_build_fail_fast_placeholder"
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550781")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "build it")
        fid = _insert_feature(conn)
        run_id = create_feature_build_run(
            conn,
            feature_id=fid,
            created_by=user_id,
            trace_id=trace_id,
            thread_id=thread_id,
        )
        update_feature_build_run(
            conn,
            run_id,
            status="running",
            attempt_count=2,
            max_attempts=5,
            last_failure_reason="placeholder_response_after_tool_loop",
        )

    agent_step(trace_id=trace_id, thread_id=thread_id, actor_id="main")

    with get_conn() as conn:
        row = conn.execute(
            (
                "SELECT status, retry_state, terminal_reason, last_failure_reason "
                "FROM feature_request_build_runs WHERE id=?"
            ),
            (run_id,),
        ).fetchone()
        denied_evt = conn.execute(
            (
                "SELECT payload_json FROM events WHERE trace_id=? "
                "AND event_type='feature.build.retry.denied' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            (trace_id,),
        ).fetchone()
    get_settings.cache_clear()

    assert row is not None
    assert str(row["status"]) == "failed"
    assert str(row["retry_state"]) == "exhausted"
    assert str(row["terminal_reason"]) == "placeholder_response_after_tool_loop"
    assert str(row["last_failure_reason"]) == "placeholder_response_after_tool_loop"
    assert denied_evt is not None
    denied_payload = json.loads(str(denied_evt["payload_json"]))
    assert denied_payload["policy_action"] == "fail_fast"
