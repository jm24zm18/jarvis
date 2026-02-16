"""Scheduler Celery tasks."""

import json

from kombu.exceptions import OperationalError

from jarvis.celery_app import celery_app
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.scheduler.service import (
    DueDispatch,
    dispatch_due,
    fetch_due_schedules_report,
)


@celery_app.task(name="jarvis.tasks.scheduler.scheduler_tick")
def scheduler_tick() -> dict[str, int | bool]:
    settings = get_settings()
    with get_conn() as conn:
        due, metrics = fetch_due_schedules_report(
            conn, default_max_catchup=settings.scheduler_max_catchup
        )

        def enqueue(item: DueDispatch) -> None:
            payload = json.loads(item.payload_json)
            try:
                celery_app.send_task(
                    "jarvis.tasks.agent.agent_step",
                    kwargs={
                        "trace_id": payload.get("trace_id", new_id("trc")),
                        "thread_id": item.thread_id,
                    },
                    queue="agent_priority",
                )
            except OperationalError:
                pass
            emit_event(
                conn,
                EventInput(
                    trace_id=payload.get("trace_id", new_id("trc")),
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=item.thread_id,
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

        dispatched = dispatch_due(due, enqueue)
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
