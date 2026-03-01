"""Scheduler task handlers."""

import json
from datetime import UTC, datetime

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.scheduler.service import fetch_due_schedules_report
from jarvis.tasks import get_task_runner


def _send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
    try:
        return get_task_runner().send_task(name, kwargs=kwargs, queue=queue)
    except Exception:
        return False


def scheduler_tick() -> dict[str, int | bool]:
    settings = get_settings()
    with get_conn() as conn:
        due, metrics = fetch_due_schedules_report(
            conn, default_max_catchup=settings.scheduler_max_catchup
        )

        dispatched = 0
        now = datetime.now(UTC).isoformat()
        
        for item in due:
            try:
                payload = json.loads(item.payload_json)
            except (json.JSONDecodeError, ValueError):
                emit_event(
                    conn,
                    EventInput(
                        trace_id=new_id("trc"),
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=item.thread_id,
                        event_type="schedule.error",
                        component="scheduler",
                        actor_type="system",
                        actor_id="scheduler",
                        payload_json=json.dumps(
                            {"schedule_id": item.schedule_id, "reason": "malformed_payload"}
                        ),
                        payload_redacted_json=json.dumps(
                            {"schedule_id": item.schedule_id, "reason": "malformed_payload"}
                        ),
                    ),
                )
                continue

            try:
                # Retrieve the user_id associated with the original thread.
                user_row = conn.execute(
                    "SELECT user_id, channel_id FROM threads WHERE id=? LIMIT 1",
                    (item.thread_id,),
                ).fetchone() if item.thread_id else None

                if user_row is None:
                    # No parent thread found — cannot create an isolated execution context.
                    # Emit a schedule.error event and skip this dispatch.
                    emit_event(
                        conn,
                        EventInput(
                            trace_id=new_id("trc"),
                            span_id=new_id("spn"),
                            parent_span_id=None,
                            thread_id=None,
                            event_type="schedule.error",
                            component="scheduler",
                            actor_type="system",
                            actor_id="scheduler",
                            payload_json=json.dumps(
                                {
                                    "schedule_id": item.schedule_id,
                                    "reason": "missing_thread",
                                    "thread_id": item.thread_id,
                                }
                            ),
                            payload_redacted_json=json.dumps(
                                {"schedule_id": item.schedule_id, "reason": "missing_thread"}
                            ),
                        ),
                    )
                    continue

                # Create a dedicated isolated thread for this scheduled execution.
                schedule_thread_id = new_id("thr")
                user_id = user_row["user_id"]
                channel_id = user_row["channel_id"]
                # Wrap the 3 INSERTs in a transaction to prevent orphaned records.
                conn.execute("BEGIN")
                try:
                    conn.execute(
                        (
                            "INSERT INTO threads"
                            "(id, user_id, channel_id, status, created_at, updated_at) "
                            "VALUES(?,?,?,?,?,?)"
                        ),
                        (schedule_thread_id, user_id, channel_id, "open", now, now),
                    )
                    conn.execute(
                        (
                            "INSERT OR IGNORE INTO sessions"
                            "(id, kind, status, created_at, updated_at) "
                            "VALUES(?,?,?,?,?)"
                        ),
                        (schedule_thread_id, "thread", "open", now, now),
                    )
                    conn.execute(
                        (
                            "INSERT OR IGNORE INTO session_participants("
                            "session_id, actor_type, actor_id, role"
                            ") VALUES(?,?,?,?)"
                        ),
                        (schedule_thread_id, "user", user_id, "user"),
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

                trace_id = payload.get("trace_id", new_id("trc"))
                _send_task(
                    "jarvis.tasks.agent.agent_step",
                    kwargs={
                        "trace_id": trace_id,
                        "thread_id": schedule_thread_id,
                    },
                    queue="agent_priority",
                )
                emit_event(
                    conn,
                    EventInput(
                        trace_id=trace_id,
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=schedule_thread_id,
                        event_type="schedule.trigger",
                        component="scheduler",
                        actor_type="system",
                        actor_id="scheduler",
                        payload_json=json.dumps(
                            {"schedule_id": item.schedule_id, "due_at": item.due_at}
                        ),
                        payload_redacted_json=json.dumps(
                            redact_payload({"schedule_id": item.schedule_id, "due_at": item.due_at})
                        ),
                    ),
                )
                dispatched += 1
            except Exception as exc:
                emit_event(
                    conn,
                    EventInput(
                        trace_id=new_id("trc"),
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=item.thread_id,
                        event_type="schedule.error",
                        component="scheduler",
                        actor_type="system",
                        actor_id="scheduler",
                        payload_json=json.dumps(
                            {"schedule_id": item.schedule_id, "reason": str(exc)[:300]}
                        ),
                        payload_redacted_json=json.dumps(
                            {"schedule_id": item.schedule_id, "reason": "dispatch_error"}
                        ),
                    ),
                )
        deferred_total = 0
        for metric in metrics:
            if metric.deferred_count <= 0 and metric.dispatched_count <= 0:
                continue
            deferred_total += metric.deferred_count
            emit_event(
                conn,
                EventInput(
                    trace_id=new_id("trc"),
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=None,
                    event_type="schedule.catchup",
                    component="scheduler",
                    actor_type="system",
                    actor_id="scheduler",
                    payload_json=json.dumps(
                        {
                            "schedule_id": metric.schedule_id,
                            "dispatched_count": metric.dispatched_count,
                            "deferred_count": metric.deferred_count,
                        }
                    ),
                    payload_redacted_json=json.dumps(
                        redact_payload(
                            {
                                "schedule_id": metric.schedule_id,
                                "dispatched_count": metric.dispatched_count,
                                "deferred_count": metric.deferred_count,
                            }
                        )
                    ),
                ),
            )
        return {"ok": True, "dispatched": dispatched, "deferred": deferred_total}
