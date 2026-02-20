"""Channel outbound Celery tasks."""

import asyncio
import json
import logging
import random
import time

import httpx

from jarvis.channels.registry import get_channel
from jarvis.db.connection import get_conn
from jarvis.db.queries import get_channel_outbound, get_system_state
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id

logger = logging.getLogger(__name__)


def _emit(
    trace_id: str,
    thread_id: str,
    event_type: str,
    payload: dict[str, object],
    channel_type: str = "whatsapp",
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
                component=f"channels.{channel_type}",
                actor_type="channel",
                actor_id=channel_type,
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )


def send_channel_message(
    thread_id: str, message_id: str, channel_type: str
) -> dict[str, str]:
    """Generic outbound task — dispatches through the channel registry."""
    adapter = get_channel(channel_type)
    if adapter is None:
        if channel_type != "cli":
            logger.warning("No adapter registered for channel_type=%s", channel_type)
        return {"thread_id": thread_id, "message_id": message_id, "status": "skipped"}

    trace_id = new_id("trc")
    with get_conn() as conn:
        state = get_system_state(conn)
        if state["lockdown"] == 1:
            _emit(
                trace_id, thread_id,
                "channel.outbound.blocked",
                {"message_id": message_id, "reason": "lockdown"},
                channel_type=channel_type,
            )
            return {"thread_id": thread_id, "message_id": message_id, "status": "blocked"}
        outbound = get_channel_outbound(conn, thread_id, message_id, channel_type)

    if outbound is None:
        return {"thread_id": thread_id, "message_id": message_id, "status": "skipped"}

    _emit(
        trace_id, thread_id,
        "channel.outbound",
        {"message_id": message_id, "status": "start"},
        channel_type=channel_type,
    )

    base_delays = [2.0, 8.0, 32.0]
    attempts = 0
    for delay in base_delays:
        attempts += 1
        try:
            status = asyncio.run(adapter.send_text(outbound["recipient"], outbound["text"]))
        except httpx.HTTPError as exc:
            if attempts >= len(base_delays):
                _emit(
                    trace_id, thread_id,
                    "task.dead_letter",
                    {"message_id": message_id, "reason": str(exc), "attempts": attempts},
                    channel_type=channel_type,
                )
                return {"thread_id": thread_id, "message_id": message_id, "status": "failed"}
            jitter = random.uniform(0.0, 1.0)
            time.sleep(delay + jitter)
            continue

        if status in {429, 500, 502, 503, 504}:
            if attempts >= len(base_delays):
                _emit(
                    trace_id, thread_id,
                    "task.dead_letter",
                    {"message_id": message_id, "reason": f"http {status}", "attempts": attempts},
                    channel_type=channel_type,
                )
                return {"thread_id": thread_id, "message_id": message_id, "status": "failed"}
            jitter = random.uniform(0.0, 1.0)
            time.sleep(delay + jitter)
            continue

        if status >= 400:
            _emit(
                trace_id, thread_id,
                "task.dead_letter",
                {"message_id": message_id, "reason": f"http {status}", "attempts": attempts},
                channel_type=channel_type,
            )
            return {"thread_id": thread_id, "message_id": message_id, "status": "failed"}

        _emit(
            trace_id, thread_id,
            "channel.outbound",
            {"message_id": message_id, "status": "sent", "attempts": attempts},
            channel_type=channel_type,
        )

        # Stop typing indicator after sending the message
        if channel_type == "whatsapp" and hasattr(adapter, "send_presence"):
            try:
                asyncio.run(adapter.send_presence(outbound["recipient"], "paused"))
            except Exception:
                pass  # Best-effort, don't fail the task

        return {"thread_id": thread_id, "message_id": message_id, "status": "sent"}

    _emit(
        trace_id, thread_id,
        "task.dead_letter",
        {"message_id": message_id, "reason": "retry exhausted", "attempts": attempts},
        channel_type=channel_type,
    )
    return {"thread_id": thread_id, "message_id": message_id, "status": "failed"}


def send_whatsapp_message(thread_id: str, message_id: str) -> dict[str, str]:
    """Legacy WhatsApp-specific task — delegates to generic send_channel_message."""
    return send_channel_message(thread_id, message_id, "whatsapp")
