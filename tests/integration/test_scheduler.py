from datetime import UTC, datetime
from unittest.mock import patch

from jarvis.db.connection import get_conn
from jarvis.ids import new_id
from jarvis.scheduler.service import (
    DueDispatch,
    dispatch_due,
    estimate_schedule_backlog,
    fetch_due_schedules,
    fetch_due_schedules_report,
)
from jarvis.tasks.scheduler import scheduler_tick


def test_scheduler_due_dispatch_idempotent() -> None:
    schedule_id = new_id("sch")
    thread_id = new_id("thr")
    now = datetime(2026, 2, 15, 12, 0, tzinfo=UTC)

    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, created_at"
                ") VALUES(?,?,?,?,?,?)"
            ),
            (schedule_id, thread_id, "@every:60", '{"trace_id":"trc_sched"}', 1, now.isoformat()),
        )

        first = fetch_due_schedules(conn, now=now)
        second = fetch_due_schedules(conn, now=now)

    enqueued: list[str] = []

    def enqueue(item: DueDispatch) -> None:
        enqueued.append(item.schedule_id)

    assert dispatch_due(first, enqueue) == 1
    assert dispatch_due(second, enqueue) == 0
    assert enqueued == [schedule_id]


def test_scheduler_cron_expression_dispatch() -> None:
    schedule_id = new_id("sch")
    now = datetime(2026, 2, 15, 12, 10, tzinfo=UTC)
    not_due = datetime(2026, 2, 15, 12, 11, tzinfo=UTC)

    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, created_at"
                ") VALUES(?,?,?,?,?,?)"
            ),
            (schedule_id, None, "*/5 * * * *", '{"trace_id":"trc_cron"}', 1, now.isoformat()),
        )
        due = fetch_due_schedules(conn, now=now)
        skip = fetch_due_schedules(conn, now=not_due)

    assert len(due) == 1
    assert due[0].schedule_id == schedule_id
    assert skip == []


def test_scheduler_interval_bounded_catchup() -> None:
    schedule_id = new_id("sch")
    base = datetime(2026, 2, 15, 12, 0, tzinfo=UTC)
    now = datetime(2026, 2, 15, 12, 5, tzinfo=UTC)

    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, created_at, last_run_at"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                schedule_id,
                None,
                "@every:60",
                '{"trace_id":"trc_catchup"}',
                1,
                base.isoformat(),
                base.isoformat(),
            ),
        )
        due = fetch_due_schedules(conn, now=now, default_max_catchup=2)
        follow_up = fetch_due_schedules(conn, now=now, default_max_catchup=2)

    assert len(due) == 2
    assert len(follow_up) == 2
    assert due[0].due_at != follow_up[0].due_at


def test_scheduler_report_includes_deferred_count() -> None:
    schedule_id = new_id("sch")
    base = datetime(2026, 2, 15, 12, 0, tzinfo=UTC)
    now = datetime(2026, 2, 15, 12, 10, tzinfo=UTC)

    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, created_at, last_run_at"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                schedule_id,
                None,
                "@every:60",
                '{"trace_id":"trc_metric"}',
                1,
                base.isoformat(),
                base.isoformat(),
            ),
        )
        due, metrics = fetch_due_schedules_report(conn, now=now, default_max_catchup=3)

    assert len(due) == 3
    metric = next(item for item in metrics if item.schedule_id == schedule_id)
    assert metric.dispatched_count == 3
    assert metric.deferred_count == 7


def test_scheduler_per_schedule_max_catchup_override() -> None:
    schedule_id = new_id("sch")
    base = datetime(2026, 2, 15, 12, 0, tzinfo=UTC)
    now = datetime(2026, 2, 15, 12, 5, tzinfo=UTC)

    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, "
                "created_at, last_run_at, max_catchup"
                ") VALUES(?,?,?,?,?,?,?,?)"
            ),
            (
                schedule_id,
                None,
                "@every:60",
                '{"trace_id":"trc_override"}',
                1,
                base.isoformat(),
                base.isoformat(),
                1,
            ),
        )
        due, metrics = fetch_due_schedules_report(conn, now=now, default_max_catchup=4)

    assert len(due) == 1
    metric = next(item for item in metrics if item.schedule_id == schedule_id)
    assert metric.dispatched_count == 1
    assert metric.deferred_count == 4


def test_scheduler_tick_creates_isolated_thread() -> None:
    """scheduler_tick() creates a new thread, session, and session_participant for each dispatch."""
    # Set up a user, channel, and parent thread for the schedule.
    with get_conn() as conn:
        from jarvis.db.queries import ensure_channel, ensure_open_thread, ensure_user

        user_id = ensure_user(conn, f"sched_user_{new_id('usr')}")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        parent_thread_id = ensure_open_thread(conn, user_id, channel_id)

    # Insert a due schedule referencing the parent thread.
    schedule_id = new_id("sch")
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, created_at, last_run_at"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                schedule_id,
                parent_thread_id,
                "@every:60",
                '{"trace_id":"trc_isolation"}',
                1,
                base.isoformat(),
                base.isoformat(),
            ),
        )

    # Patch _send_task so it doesn't actually enqueue.
    with patch("jarvis.tasks.scheduler._send_task", return_value=True):
        result = scheduler_tick()

    assert result["dispatched"] >= 1

    # Verify a new isolated thread was created (different from parent).
    with get_conn() as conn:
        # There should be at least 2 threads now: the parent + the isolated one.
        rows = conn.execute(
            "SELECT id FROM threads WHERE user_id=? ORDER BY created_at",
            (user_id,),
        ).fetchall()
        thread_ids = [str(r["id"]) for r in rows]
        assert len(thread_ids) >= 2, "Expected parent thread + at least one isolated thread"

        # The isolated thread must have a corresponding session record.
        for tid in thread_ids:
            if tid == parent_thread_id:
                continue
            session_row = conn.execute(
                "SELECT id FROM sessions WHERE id=?", (tid,)
            ).fetchone()
            assert session_row is not None, f"No session record for isolated thread {tid}"

            participant_row = conn.execute(
                "SELECT session_id FROM session_participants WHERE session_id=? AND actor_id=?",
                (tid, user_id),
            ).fetchone()
            assert participant_row is not None, (
                f"No session_participant for isolated thread {tid}"
            )


def test_scheduler_tick_null_thread_id_skips_gracefully() -> None:
    """scheduler_tick() skips schedules with thread_id=NULL and emits schedule.error event."""
    schedule_id = new_id("sch")
    base = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, created_at, last_run_at"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                schedule_id,
                None,  # NULL thread_id
                "@every:60",
                '{"trace_id":"trc_null_thread"}',
                1,
                base.isoformat(),
                base.isoformat(),
            ),
        )

    with patch("jarvis.tasks.scheduler._send_task", return_value=True) as mock_send:
        result = scheduler_tick()

    # Should NOT dispatch to agent_step (thread doesn't exist).
    assert mock_send.call_count == 0
    # dispatched count should be 0 for this schedule.
    assert result["dispatched"] == 0

    # A schedule.error event should have been emitted.
    with get_conn() as conn:
        error_event = conn.execute(
            "SELECT id FROM events WHERE event_type='schedule.error' "
            "AND payload_json LIKE ?",
            (f'%{schedule_id}%',),
        ).fetchone()
        assert error_event is not None, "Expected a schedule.error event for NULL thread_id"


def test_scheduler_backlog_estimation() -> None:
    schedule_id = new_id("sch")
    base = datetime(2026, 2, 15, 12, 0, tzinfo=UTC)
    now = datetime(2026, 2, 15, 12, 4, tzinfo=UTC)

    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, "
                "created_at, last_run_at, max_catchup"
                ") VALUES(?,?,?,?,?,?,?,?)"
            ),
            (
                schedule_id,
                None,
                "@every:60",
                '{"trace_id":"trc_estimate"}',
                1,
                base.isoformat(),
                base.isoformat(),
                2,
            ),
        )
        report = estimate_schedule_backlog(conn, now=now, default_max_catchup=10)

    assert report["dispatchable_total"] == 2
    assert report["deferred_total"] == 2
