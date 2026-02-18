"""WhatsApp webhook routes."""

from __future__ import annotations

import hmac
import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from jarvis.channels.registry import get_channel
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    ensure_channel,
    ensure_open_thread,
    ensure_user,
    get_system_state,
    get_thread_by_whatsapp_remote,
    insert_message,
    record_external_message,
    upsert_whatsapp_thread_map,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.tasks import get_task_runner

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


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


@router.post("")
async def inbound(
    payload: dict[str, Any],
    x_whatsapp_secret: str | None = Header(default=None),
) -> JSONResponse:
    settings = get_settings()
    required_secret = settings.whatsapp_webhook_secret.strip()
    provided_secret = str(x_whatsapp_secret or "").strip()
    if required_secret and (
        not provided_secret or not hmac.compare_digest(provided_secret, required_secret)
    ):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"accepted": False, "error": "invalid_webhook_secret"},
        )

    adapter = get_channel("whatsapp")
    if adapter is None:
        return JSONResponse(
            status_code=500,
            content={"accepted": False, "error": "adapter_missing"},
        )
    messages = adapter.parse_inbound(payload)
    if not messages:
        return JSONResponse(
            status_code=200,
            content={"accepted": True, "degraded": False, "ignored": True},
        )

    trace_id = new_id("trc")
    degraded = False
    instance = settings.whatsapp_instance.strip() or "personal"

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

        for msg in messages:
            if not record_external_message(conn, "whatsapp", msg.external_msg_id, trace_id):
                continue

            user_id = ensure_user(conn, msg.sender_id)
            channel_id = ensure_channel(conn, user_id, "whatsapp")

            thread_id: str
            remote_jid = str(msg.thread_key or "").strip()
            if remote_jid:
                mapped = get_thread_by_whatsapp_remote(conn, instance, remote_jid)
                if mapped:
                    thread_id = mapped
                else:
                    thread_id = ensure_open_thread(conn, user_id, channel_id)
                    upsert_whatsapp_thread_map(
                        conn,
                        thread_id=thread_id,
                        instance=instance,
                        remote_jid=remote_jid,
                        participant_jid=str(msg.group_context.get("participant") or "") or None,
                    )
            else:
                thread_id = ensure_open_thread(conn, user_id, channel_id)

            text = (msg.text or "").strip()
            if msg.message_type == "reaction":
                emoji = str(msg.reaction.get("emoji") or "")
                target = ""
                reaction_key = msg.reaction.get("key")
                if isinstance(reaction_key, dict):
                    target = str(reaction_key.get("id") or "")
                text = f"[reaction] {emoji} {target}".strip()
            elif msg.message_type in {"image", "video", "document", "audio", "sticker"}:
                prefix = f"[{msg.message_type}]"
                text = f"{prefix} {text}".strip() if text else prefix
            elif msg.message_type == "unknown" and not text:
                text = "[unsupported message]"

            _ = insert_message(conn, thread_id, "user", text)

            event_payload = {
                "text": text,
                "message_type": msg.message_type,
                "mentions": msg.mentions,
                "group_context": msg.group_context,
            }
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
                    payload_json=json.dumps(event_payload),
                    payload_redacted_json=json.dumps(redact_payload(event_payload)),
                ),
            )

            index_ok = _safe_send_task(
                "jarvis.tasks.memory.index_event",
                {
                    "trace_id": trace_id,
                    "thread_id": thread_id,
                    "text": text,
                    "metadata": {
                        "channel": "whatsapp",
                        "message_type": msg.message_type,
                        "mentions": msg.mentions,
                        "group_context": msg.group_context,
                    },
                },
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
