"""Agent run stale-attempt recovery task."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import now_iso
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.tasks.agent_attempts import (
    finish_attempt,
    is_attempt_stale,
    next_attempt_number,
    resolve_existing_trace_message_id,
)


def _notify_trace_event(
    *,
    conn,
    thread_id: str,
    trace_id: str,
    event_type: str,
    payload: dict[str, object],
) -> None:
    created_at = now_iso()
    enriched = dict(payload)
    enriched["trace_id"] = trace_id
    enriched["created_at"] = created_at
    conn.execute(
        (
            "INSERT INTO web_notifications("
            "thread_id, event_type, payload_json, created_at"
            ") VALUES(?,?,?,?)"
        ),
        (thread_id, f"trace.{event_type}", json.dumps(enriched), created_at),
    )
    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id,
            event_type=event_type,
            component="agent.recovery",
            actor_type="system",
            actor_id="agent_recovery",
            payload_json=json.dumps(payload),
            payload_redacted_json=json.dumps(redact_payload(payload)),
        ),
    )


def reap_stale_agent_runs() -> dict[str, int]:
    from jarvis.tasks import get_task_runner

    settings = get_settings()
    now = datetime.now(UTC)
    max_attempts = max(1, int(settings.agent_step_max_attempts))

    scanned = 0
    stale = 0
    recovered = 0
    exhausted = 0
    duplicate_skipped = 0

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT trace_id, thread_id, actor_id, attempt, phase, started_at, "
            "last_heartbeat_at FROM agent_run_attempts "
            "WHERE status='running' ORDER BY started_at ASC"
        ).fetchall()
        scanned = len(rows)

        for row in rows:
            if not is_attempt_stale(row, now=now, settings=settings):
                continue
            stale += 1
            trace_id = str(row["trace_id"])
            thread_id = str(row["thread_id"])
            actor_id = str(row["actor_id"])
            attempt = int(row["attempt"])

            existing_message_id = resolve_existing_trace_message_id(
                conn, trace_id=trace_id, thread_id=thread_id
            )
            if existing_message_id:
                duplicate_skipped += 1
                finish_attempt(
                    conn,
                    trace_id=trace_id,
                    attempt=attempt,
                    status="succeeded",
                    final_message_id=existing_message_id,
                )
                _notify_trace_event(
                    conn=conn,
                    thread_id=thread_id,
                    trace_id=trace_id,
                    event_type="agent.step.recovery_skipped_duplicate",
                    payload={
                        "stale_attempt": attempt,
                        "resolved_message_id": existing_message_id,
                        "failure_kind": "stale_timeout",
                        "reason": "response_already_emitted",
                    },
                )
                continue

            finish_attempt(
                conn,
                trace_id=trace_id,
                attempt=attempt,
                status="abandoned",
                failure_kind="stale_timeout",
                failure_message=(
                    f"stale run detected in phase={str(row['phase'])} "
                    f"last_heartbeat_at={str(row['last_heartbeat_at'])}"
                ),
            )

            used_attempts = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM agent_run_attempts WHERE trace_id=?",
                    (trace_id,),
                ).fetchone()["c"]
            )
            if used_attempts >= max_attempts:
                exhausted += 1
                _notify_trace_event(
                    conn=conn,
                    thread_id=thread_id,
                    trace_id=trace_id,
                    event_type="agent.step.retry_exhausted",
                    payload={
                        "attempt": attempt,
                        "failure_kind": "stale_timeout",
                        "error": "stale run exceeded max attempts",
                    },
                )
                continue

            next_attempt = next_attempt_number(conn, trace_id=trace_id)
            ok = get_task_runner().send_task(
                "jarvis.tasks.agent.agent_step",
                kwargs={"trace_id": trace_id, "thread_id": thread_id, "actor_id": actor_id},
                queue="agent_priority",
            )
            if ok:
                recovered += 1
                _notify_trace_event(
                    conn=conn,
                    thread_id=thread_id,
                    trace_id=trace_id,
                    event_type="agent.step.recovered",
                    payload={
                        "stale_attempt": attempt,
                        "recovery_attempt": next_attempt,
                        "failure_kind": "stale_timeout",
                    },
                )

    return {
        "scanned": scanned,
        "stale": stale,
        "recovered": recovered,
        "exhausted": exhausted,
        "duplicate_skipped": duplicate_skipped,
    }
