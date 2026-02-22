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
    reason = "sent"

    try:
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
                    reason = "failed"
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
                    reason = "failed"
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
                reason = "failed"
                return {"thread_id": thread_id, "message_id": message_id, "status": "failed"}

            _emit(
                trace_id, thread_id,
                "channel.outbound",
                {"message_id": message_id, "status": "sent", "attempts": attempts},
                channel_type=channel_type,
            )

            return {"thread_id": thread_id, "message_id": message_id, "status": "sent"}

        _emit(
            trace_id, thread_id,
            "task.dead_letter",
            {"message_id": message_id, "reason": "retry exhausted", "attempts": attempts},
            channel_type=channel_type,
        )
        reason = "retry_exhausted"
        return {"thread_id": thread_id, "message_id": message_id, "status": "failed"}
    except Exception:
        reason = "error"
        raise
    finally:
        if channel_type == "whatsapp":
            if hasattr(adapter, "send_presence"):
                try:
                    asyncio.run(adapter.send_presence(outbound["recipient"], "paused"))
                except Exception:
                    pass  # Best-effort, don't fail the task

            from jarvis.db.queries import clear_typing_state
            from jarvis.routes.health import increment_metric
            with get_conn() as conn:
                clear_typing_state(conn, thread_id, outbound["recipient"])
                increment_metric("whatsapp_typing_active_threads_clear")
                if reason in ("failed", "retry_exhausted", "error"):
                    increment_metric("channel_messages_failed")
                _emit(
                    trace_id, thread_id,
                    "channel.typing.clear",
                    {"reason": reason, "recipient": outbound["recipient"]},
                    channel_type=channel_type,
                )


def send_whatsapp_message(thread_id: str, message_id: str) -> dict[str, str]:
    """Legacy WhatsApp-specific task — delegates to generic send_channel_message."""
    return send_channel_message(thread_id, message_id, "whatsapp")


def cleanup_stale_typing() -> dict[str, object]:
    """TTL cleanup task for stale channel typing markers."""
    from jarvis.config import get_settings
    from jarvis.db.queries import get_stale_typing_states, clear_typing_state
    from datetime import datetime, UTC, timedelta

    settings = get_settings()
    ttl_seconds = int(getattr(settings, "whatsapp_typing_ttl_seconds", 20))
    cutoff = (datetime.now(UTC) - timedelta(seconds=ttl_seconds)).isoformat()
    trace_id = new_id("trc")
    cleared = 0

    with get_conn() as conn:
        stale_states = get_stale_typing_states(conn, cutoff)
        for state in stale_states:
            thread_id = state["thread_id"]
            recipient = state["recipient"]
            channel_type = state["channel_type"]
            
            if channel_type == "whatsapp":
                adapter = get_channel("whatsapp")
                if adapter and hasattr(adapter, "send_presence"):
                    try:
                        asyncio.run(adapter.send_presence(recipient, "paused"))
                    except Exception:
                        pass
            
            clear_typing_state(conn, thread_id, recipient)
            from jarvis.routes.health import increment_metric
            increment_metric("whatsapp_typing_active_threads_clear")
            _emit(
                trace_id, thread_id,
                "channel.typing.clear",
                {"reason": "ttl_cleanup", "recipient": recipient},
                channel_type=channel_type,
            )
            cleared += 1

    return {"status": "ok", "cleared": cleared}
