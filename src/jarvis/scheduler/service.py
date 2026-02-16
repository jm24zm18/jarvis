"""Scheduler due-job evaluation and idempotent dispatch logic."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jarvis.db.queries import now_iso


@dataclass(slots=True)
class DueDispatch:
    schedule_id: str
    thread_id: str | None
    due_at: str
    payload_json: str


@dataclass(slots=True)
class ScheduleMetric:
    schedule_id: str
    dispatched_count: int
    deferred_count: int


def _effective_max_catchup(row_value: object, default_max_catchup: int) -> int:
    if isinstance(row_value, int) and row_value > 0:
        return row_value
    return max(1, default_max_catchup)


def _parse_interval_seconds(cron_expr: str) -> int | None:
    if not cron_expr.startswith("@every:"):
        return None
    value = cron_expr.split(":", 1)[1].strip()
    return max(1, int(value))


def _iter_due_interval(
    last_run_at: str | None, interval_s: int, now: datetime, max_catchup: int
) -> tuple[list[datetime], int]:
    if max_catchup <= 0:
        return [], 0
    if last_run_at is None:
        return [now], 0

    previous = datetime.fromisoformat(last_run_at)
    seconds = int((now - previous).total_seconds())
    if seconds < interval_s:
        return [], 0

    total_due = seconds // interval_s
    emit_count = min(total_due, max_catchup)
    due = [previous + timedelta(seconds=interval_s * idx) for idx in range(1, emit_count + 1)]
    deferred = max(0, total_due - emit_count)
    return due, deferred


def _parse_cron_part(part: str, minimum: int, maximum: int) -> set[int]:
    if part == "*":
        return set(range(minimum, maximum + 1))
    values: set[int] = set()
    for token in part.split(","):
        if token.startswith("*/"):
            step = int(token[2:])
            values.update(range(minimum, maximum + 1, step))
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            values.update(range(int(left), int(right) + 1))
            continue
        values.add(int(token))
    return values


def _cron_matches(slot: datetime, cron_expr: str) -> bool:
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"unsupported cron expression: {cron_expr}")

    minute, hour, dom, month, dow = parts
    minute_set = _parse_cron_part(minute, 0, 59)
    hour_set = _parse_cron_part(hour, 0, 23)
    dom_set = _parse_cron_part(dom, 1, 31)
    month_set = _parse_cron_part(month, 1, 12)
    dow_set = _parse_cron_part(dow, 0, 6)
    current_dow = (slot.weekday() + 1) % 7
    return (
        slot.minute in minute_set
        and slot.hour in hour_set
        and slot.day in dom_set
        and slot.month in month_set
        and current_dow in dow_set
    )


def _iter_due_cron(
    last_run_at: str | None, cron_expr: str, now: datetime, max_catchup: int
) -> tuple[list[datetime], int]:
    if max_catchup <= 0:
        return [], 0
    current_slot = now.replace(second=0, microsecond=0)
    if last_run_at is None:
        if _cron_matches(current_slot, cron_expr):
            return [current_slot], 0
        return [], 0

    start = datetime.fromisoformat(last_run_at).replace(second=0, microsecond=0) + timedelta(
        minutes=1
    )
    due: list[datetime] = []
    total_due = 0
    cursor = start
    while cursor <= current_slot:
        if _cron_matches(cursor, cron_expr):
            total_due += 1
            if len(due) < max_catchup:
                due.append(cursor)
        cursor += timedelta(minutes=1)

    deferred = max(0, total_due - len(due))
    return due, deferred


def fetch_due_schedules_report(
    conn: sqlite3.Connection,
    now: datetime | None = None,
    default_max_catchup: int = 10,
) -> tuple[list[DueDispatch], list[ScheduleMetric]]:
    current = now or datetime.now(UTC)
    rows = conn.execute(
        "SELECT id, thread_id, cron_expr, payload_json, last_run_at, max_catchup "
        "FROM schedules WHERE enabled=1"
    ).fetchall()

    due: list[DueDispatch] = []
    metrics: list[ScheduleMetric] = []
    for row in rows:
        max_catchup = _effective_max_catchup(row["max_catchup"], default_max_catchup)
        cron_expr = str(row["cron_expr"])
        interval_s = _parse_interval_seconds(cron_expr)
        if interval_s is not None:
            due_slots, deferred_count = _iter_due_interval(
                str(row["last_run_at"]) if row["last_run_at"] is not None else None,
                interval_s,
                current,
                max_catchup,
            )
        else:
            due_slots, deferred_count = _iter_due_cron(
                str(row["last_run_at"]) if row["last_run_at"] is not None else None,
                cron_expr,
                current,
                max_catchup,
            )
        if not due_slots and deferred_count == 0:
            metrics.append(
                ScheduleMetric(
                    schedule_id=str(row["id"]),
                    dispatched_count=0,
                    deferred_count=0,
                )
            )
            continue

        dispatched_slots: list[datetime] = []
        for due_at in due_slots:
            due_stamp = due_at.isoformat()
            try:
                conn.execute(
                    (
                        "INSERT INTO schedule_dispatches("
                        "schedule_id, due_at, dispatched_at"
                        ") VALUES(?,?,?)"
                    ),
                    (str(row["id"]), due_stamp, now_iso()),
                )
            except sqlite3.IntegrityError:
                continue
            dispatched_slots.append(due_at)
            due.append(
                DueDispatch(
                    schedule_id=str(row["id"]),
                    thread_id=str(row["thread_id"]) if row["thread_id"] is not None else None,
                    due_at=due_stamp,
                    payload_json=str(row["payload_json"]),
                )
            )

        if dispatched_slots:
            conn.execute(
                "UPDATE schedules SET last_run_at=? WHERE id=?",
                (dispatched_slots[-1].isoformat(), str(row["id"])),
            )

        metrics.append(
            ScheduleMetric(
                schedule_id=str(row["id"]),
                dispatched_count=len(dispatched_slots),
                deferred_count=deferred_count,
            )
        )
    return due, metrics


def fetch_due_schedules(
    conn: sqlite3.Connection,
    now: datetime | None = None,
    default_max_catchup: int = 10,
) -> list[DueDispatch]:
    due, _ = fetch_due_schedules_report(conn, now=now, default_max_catchup=default_max_catchup)
    return due


def estimate_schedule_backlog(
    conn: sqlite3.Connection,
    now: datetime | None = None,
    default_max_catchup: int = 10,
) -> dict[str, object]:
    current = now or datetime.now(UTC)
    rows = conn.execute(
        "SELECT id, cron_expr, last_run_at, max_catchup FROM schedules WHERE enabled=1"
    ).fetchall()
    summary: list[dict[str, int | str]] = []
    total_dispatchable = 0
    total_deferred = 0
    for row in rows:
        max_catchup = _effective_max_catchup(row["max_catchup"], default_max_catchup)
        cron_expr = str(row["cron_expr"])
        last_run_at = str(row["last_run_at"]) if row["last_run_at"] is not None else None
        interval_s = _parse_interval_seconds(cron_expr)
        if interval_s is not None:
            due_slots, deferred_count = _iter_due_interval(
                last_run_at, interval_s, current, max_catchup
            )
        else:
            due_slots, deferred_count = _iter_due_cron(
                last_run_at, cron_expr, current, max_catchup
            )
        dispatchable = len(due_slots)
        total_dispatchable += dispatchable
        total_deferred += deferred_count
        summary.append(
            {
                "schedule_id": str(row["id"]),
                "dispatchable": dispatchable,
                "deferred": deferred_count,
                "max_catchup": max_catchup,
            }
        )
    return {
        "dispatchable_total": total_dispatchable,
        "deferred_total": total_deferred,
        "schedule_count": len(summary),
        "schedules": summary,
    }


def dispatch_due(
    due: list[DueDispatch],
    enqueue: Callable[[DueDispatch], None],
) -> int:
    count = 0
    for item in due:
        enqueue(item)
        count += 1
    return count
