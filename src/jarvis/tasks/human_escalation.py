"""Human escalation task helpers."""

from __future__ import annotations

import json
import logging

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_human_escalation,
    ensure_channel,
    ensure_open_thread,
    ensure_user,
    insert_message,
    list_due_human_escalations,
    now_iso,
    update_human_escalation,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.tasks import get_task_runner

logger = logging.getLogger(__name__)


def _emit(
    *,
    trace_id: str,
    thread_id: str | None,
    event_type: str,
    payload: dict[str, object],
) -> None:
    with get_conn() as conn:
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type=event_type,
                component="human_escalation",
                actor_type="system",
                actor_id="human_escalation",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )


def request_human_escalation(
    *,
    thread_id: str,
    trace_id: str,
    requested_by_actor_id: str,
    source_agent_id: str,
    reason: str,
    message: str,
    priority: str = "normal",
) -> dict[str, object]:
    settings = get_settings()
    channel_type = str(settings.human_escalation_channel_type).strip().lower() or "whatsapp"
    targets = [
        item.strip()
        for item in str(settings.human_escalation_targets).split(",")
        if item.strip()
    ]
    if not targets:
        _emit(
            trace_id=trace_id,
            thread_id=thread_id,
            event_type="human.escalation.misconfigured",
            payload={"reason": "no_targets", "channel_type": channel_type},
        )
        return {"ok": False, "error": "human escalation targets are not configured"}

    effective_priority = str(priority).strip().lower() or str(
        settings.human_escalation_default_priority
    ).strip().lower() or "normal"
    created: list[str] = []
    with get_conn() as conn:
        for target_external_id in targets:
            escalation_id = create_human_escalation(
                conn,
                thread_id=thread_id,
                trace_id=trace_id,
                requested_by_actor_id=requested_by_actor_id,
                source_agent_id=source_agent_id,
                reason=reason,
                message=message,
                channel_type=channel_type,
                target_external_id=target_external_id,
                priority=effective_priority,
            )
            created.append(escalation_id)
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="human.escalation.requested",
                    component="human_escalation",
                    actor_type="agent",
                    actor_id=source_agent_id,
                    payload_json=json.dumps(
                        {
                            "escalation_id": escalation_id,
                            "target_external_id": target_external_id,
                            "channel_type": channel_type,
                            "priority": effective_priority,
                            "reason": reason[:500],
                        }
                    ),
                    payload_redacted_json=json.dumps(
                        redact_payload(
                            {
                                "escalation_id": escalation_id,
                                "target_external_id": target_external_id,
                                "channel_type": channel_type,
                                "priority": effective_priority,
                                "reason": reason[:500],
                            }
                        )
                    ),
                ),
            )

    dispatched = dispatch_pending_human_escalations(limit=max(1, len(created)))
    return {
        "ok": True,
        "count": len(created),
        "escalation_ids": created,
        "dispatch": dispatched,
    }


def _dispatch_one(item: dict[str, object]) -> tuple[bool, str]:
    escalation_id = str(item["id"])
    trace_id = str(item["trace_id"])
    source_thread_id = str(item["thread_id"])
    channel_type = str(item["channel_type"])
    target_external_id = str(item["target_external_id"])
    message = str(item["message"])
    reason = str(item["reason"])
    source_agent_id = str(item["source_agent_id"])

    escalation_text = (
        "[Human Escalation Request]\n"
        f"Time: {now_iso()}\n"
        f"Source thread: {source_thread_id}\n"
        f"Source agent: {source_agent_id}\n"
        f"Trace: {trace_id}\n"
        f"Reason: {reason}\n\n"
        f"{message}"
    )

    with get_conn() as conn:
        target_user_id = ensure_user(conn, target_external_id)
        target_channel_id = ensure_channel(conn, target_user_id, channel_type)
        target_thread_id = ensure_open_thread(conn, target_user_id, target_channel_id)

        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=target_thread_id,
                event_type="human.escalation.dispatch.start",
                component="human_escalation",
                actor_type="system",
                actor_id="human_escalation",
                payload_json=json.dumps(
                    {
                        "escalation_id": escalation_id,
                        "target_external_id": target_external_id,
                        "channel_type": channel_type,
                    }
                ),
                payload_redacted_json=json.dumps(
                    redact_payload(
                        {
                            "escalation_id": escalation_id,
                            "target_external_id": target_external_id,
                            "channel_type": channel_type,
                        }
                    )
                ),
            ),
        )

        message_id = insert_message(conn, target_thread_id, "assistant", escalation_text)
        if channel_type != "web":
            ok = get_task_runner().send_task(
                "jarvis.tasks.channel.send_channel_message",
                kwargs={
                    "thread_id": target_thread_id,
                    "message_id": message_id,
                    "channel_type": channel_type,
                },
                queue="tools_io",
            )
            if not ok:
                update_human_escalation(
                    conn,
                    escalation_id,
                    status="failed",
                    dispatched_message_id=message_id,
                    error="failed to enqueue outbound channel task",
                )
                emit_event(
                    conn,
                    EventInput(
                        trace_id=trace_id,
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=target_thread_id,
                        event_type="human.escalation.dispatch.failed",
                        component="human_escalation",
                        actor_type="system",
                        actor_id="human_escalation",
                        payload_json=json.dumps(
                            {
                                "escalation_id": escalation_id,
                                "message_id": message_id,
                                "reason": "enqueue_failed",
                            }
                        ),
                        payload_redacted_json=json.dumps(
                            redact_payload(
                                {
                                    "escalation_id": escalation_id,
                                    "message_id": message_id,
                                    "reason": "enqueue_failed",
                                }
                            )
                        ),
                    ),
                )
                return False, "enqueue_failed"

        update_human_escalation(
            conn,
            escalation_id,
            status="dispatched",
            dispatched_message_id=message_id,
            error="",
        )
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=target_thread_id,
                event_type="human.escalation.dispatch.end",
                component="human_escalation",
                actor_type="system",
                actor_id="human_escalation",
                payload_json=json.dumps(
                    {
                        "escalation_id": escalation_id,
                        "message_id": message_id,
                        "channel_type": channel_type,
                    }
                ),
                payload_redacted_json=json.dumps(
                    redact_payload(
                        {
                            "escalation_id": escalation_id,
                            "message_id": message_id,
                            "channel_type": channel_type,
                        }
                    )
                ),
            ),
        )
    return True, "dispatched"


def dispatch_pending_human_escalations(limit: int = 50) -> dict[str, object]:
    attempted = 0
    dispatched = 0
    failed = 0
    with get_conn() as conn:
        rows = list_due_human_escalations(conn, limit=limit)
    for item in rows:
        attempted += 1
        try:
            ok, _reason = _dispatch_one(item)
        except Exception as exc:  # pragma: no cover - defensive eventing path
            failed += 1
            logger.exception("human escalation dispatch crashed id=%s", item.get("id"))
            with get_conn() as conn:
                update_human_escalation(
                    conn,
                    str(item.get("id")),
                    status="failed",
                    error=str(exc),
                )
            continue
        if ok:
            dispatched += 1
        else:
            failed += 1
    return {"attempted": attempted, "dispatched": dispatched, "failed": failed}
