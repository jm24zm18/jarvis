"""WhatsApp webhook routes."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from jarvis.config import get_settings
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
from jarvis.tasks import get_task_runner

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])
_limiter = Limiter(key_func=get_remote_address)


def _safe_send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
    try:
        return bool(get_task_runner().send_task(name, kwargs=kwargs, queue=queue))
    except Exception:
        return False


@router.get("")
async def verify(request: Request) -> Response:
    settings = get_settings()
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.whatsapp_verify_token and challenge:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="verification failed")


def _extract_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                text = msg.get("text", {}).get("body", "")
                sender = msg.get("from", "unknown")
                msg_id = msg.get("id", "")
                if text and msg_id:
                    messages.append({"id": msg_id, "from": sender, "text": text})
    return messages


@router.post("")
async def inbound(payload: dict[str, Any]) -> JSONResponse:
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
                component="channels.whatsapp",
                actor_type="channel",
                actor_id="whatsapp",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )

        for msg in _extract_messages(payload):
            if not record_external_message(conn, "whatsapp", msg["id"], trace_id):
                continue
            user_id = ensure_user(conn, msg["from"])
            channel_id = ensure_channel(conn, user_id, "whatsapp")
            thread_id = ensure_open_thread(conn, user_id, channel_id)
            _ = insert_message(conn, thread_id, "user", msg["text"])

            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="channel.inbound",
                    component="channels.whatsapp",
                    actor_type="user",
                    actor_id=user_id,
                    payload_json=json.dumps({"text": msg["text"]}),
                    payload_redacted_json=json.dumps(redact_payload({"text": msg["text"]})),
                ),
            )

            index_ok = _safe_send_task(
                "jarvis.tasks.memory.index_event",
                {"trace_id": trace_id, "thread_id": thread_id, "text": msg["text"]},
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
                        component="channels.whatsapp",
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
