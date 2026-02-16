from datetime import UTC, datetime

from jarvis.db.connection import get_conn
from jarvis.ids import new_id
from jarvis.scheduler.service import (
    DueDispatch,
    dispatch_due,
    estimate_schedule_backlog,
    fetch_due_schedules,
    fetch_due_schedules_report,
)


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
