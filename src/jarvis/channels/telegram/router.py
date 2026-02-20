"""Telegram webhook routes."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from jarvis.channels.registry import get_channel
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/telegram", tags=["telegram"])


def _safe_send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
    try:
        runner = get_task_runner()
        return bool(runner.send_task(name, kwargs=kwargs, queue=queue))
    except Exception:
        logger.exception("Failed to enqueue task %s", name)
        return False


@router.post("")
async def inbound(request: Request) -> JSONResponse:
    """Handle Telegram Bot API webhook updates."""
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="telegram_not_configured",
        )

    payload: dict[str, Any] = await request.json()

    adapter = get_channel("telegram")
    if adapter is None:
        return JSONResponse(
            status_code=500,
            content={"accepted": False, "error": "adapter_missing"},
        )

    messages = adapter.parse_inbound(payload)
    if not messages:
        return JSONResponse(
            status_code=200,
            content={"accepted": True, "ignored": True},
        )

    # Check allowed chat IDs
    allowed_chats_raw = settings.telegram_allowed_chat_ids.strip()
    allowed_chats: set[str] = set()
    if allowed_chats_raw:
        allowed_chats = {c.strip() for c in allowed_chats_raw.split(",") if c.strip()}

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
                component="channels.telegram",
                actor_type="channel",
                actor_id="telegram",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )

        for msg in messages:
            # Filter by allowed chat IDs if configured
            chat_id = msg.thread_key or ""
            if allowed_chats and chat_id not in allowed_chats:
                logger.info("Telegram message from chat %s ignored (not in allowlist)", chat_id)
                continue

            if not record_external_message(conn, "telegram", msg.external_msg_id, trace_id):
                continue

            user_id = ensure_user(conn, f"tg:{msg.sender_id}")
            channel_id = ensure_channel(conn, user_id, "telegram")
            thread_id = ensure_open_thread(conn, user_id, channel_id)

            text = (msg.text or "").strip()
            if not text and msg.message_type != "text":
                text = f"[{msg.message_type}]"

            message_id = insert_message(conn, thread_id, "user", text)

            event_payload = {
                "text": text,
                "message_type": msg.message_type,
                "mentions": msg.mentions,
                "group_context": msg.group_context,
                "message_id": message_id,
            }
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="channel.inbound",
                    component="channels.telegram",
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
                        "channel": "telegram",
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

    status_code = 202 if degraded else 200
    return JSONResponse(
        status_code=status_code,
        content={"accepted": True, "degraded": degraded},
    )
