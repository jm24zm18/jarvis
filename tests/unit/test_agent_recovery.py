import json
from datetime import UTC, datetime, timedelta

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    ensure_channel,
    ensure_open_thread,
    ensure_system_state,
    ensure_user,
    insert_message,
)
from jarvis.tasks.agent import agent_step
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
    assert payload["trace_id"] == trace_id

    assert len(runner.calls) == 1
    name, kwargs, queue = runner.calls[0]
    assert name == "jarvis.tasks.agent.agent_step"
    assert kwargs["trace_id"] == trace_id
    assert kwargs["actor_id"] == "main"
    assert queue == "agent_priority"
