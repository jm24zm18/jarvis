"""Generic webhook route that dispatches to any registered channel adapter."""

import json
import logging
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from kombu.exceptions import OperationalError

from jarvis.celery_app import celery_app
from jarvis.channels.registry import get_channel
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    ensure_channel,
    ensure_open_thread,
    ensure_user,
    get_system_state,
    insert_message,
    record_external_message,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _safe_send_task(name: str, kwargs: dict[str, str], queue: str) -> bool:
    try:
        celery_app.send_task(name, kwargs=kwargs, queue=queue)
        return True
    except OperationalError:
        return False


@router.post("/{channel_type}")
async def generic_inbound(channel_type: str, payload: dict[str, Any]) -> JSONResponse:
    adapter = get_channel(channel_type)
    if adapter is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": f"unknown channel: {channel_type}"},
        )

    trace_id = new_id("trc")
    degraded = False

    with get_conn() as conn:
        state = get_system_state(conn)
        if state["restarting"] == 1:
            return JSONResponse(status_code=200, content={"accepted": False})

        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=None,
                event_type="channel.inbound.batch",
                component=f"channels.{channel_type}",
                actor_type="channel",
                actor_id=channel_type,
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )

        for msg in adapter.parse_inbound(payload):
            if not record_external_message(conn, channel_type, msg.external_msg_id, trace_id):
                continue
            user_id = ensure_user(conn, msg.sender_id)
            channel_id = ensure_channel(conn, user_id, channel_type)
            thread_id = ensure_open_thread(conn, user_id, channel_id)
            _ = insert_message(conn, thread_id, "user", msg.text)

            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="channel.inbound",
                    component=f"channels.{channel_type}",
                    actor_type="user",
                    actor_id=user_id,
                    payload_json=json.dumps({"text": msg.text}),
                    payload_redacted_json=json.dumps(redact_payload({"text": msg.text})),
                ),
            )

            index_ok = _safe_send_task(
                "jarvis.tasks.memory.index_event",
                {"trace_id": trace_id, "thread_id": thread_id, "text": msg.text},
                "tools_io",
            )
            step_ok = _safe_send_task(
                "jarvis.tasks.agent.agent_step",
                {"trace_id": trace_id, "thread_id": thread_id},
                "agent_priority",
            )
            if not index_ok or not step_ok:
                degraded = True
                emit_event(
                    conn,
                    EventInput(
                        trace_id=trace_id,
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=thread_id,
                        event_type="channel.inbound.degraded",
                        component=f"channels.{channel_type}",
                        actor_type="system",
                        actor_id="broker",
                        payload_json=json.dumps(
                            {
                                "index_enqueued": index_ok,
                                "agent_step_enqueued": step_ok,
                            }
                        ),
                        payload_redacted_json=json.dumps(
                            redact_payload(
                                {
                                    "index_enqueued": index_ok,
                                    "agent_step_enqueued": step_ok,
                                }
                            )
                        ),
                    ),
                )

    status_code = 202 if degraded else 200
    return JSONResponse(status_code=status_code, content={"accepted": True, "degraded": degraded})
