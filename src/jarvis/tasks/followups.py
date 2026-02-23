"""Heartbeat-driven proactive follow-up checks."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import insert_message, now_iso
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.providers.factory import build_fallback_provider, build_primary_provider
from jarvis.providers.router import ProviderRouter

logger = logging.getLogger(__name__)


def _emit(
    event_type: str,
    payload: dict[str, object],
    *,
    thread_id: str | None,
    trace_id: str,
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
                component="followups",
                actor_type="system",
                actor_id="followups",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )


def _extract_json_object(text: str) -> dict[str, object] | None:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if "\n" in raw:
            raw = raw.split("\n", 1)[1]
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    body = raw[start : end + 1]
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _parse_decision(text: str) -> tuple[str, str, str]:
    parsed = _extract_json_object(text)
    if parsed is None:
        return ("no_reply", "", "invalid_json")

    action_raw = str(parsed.get("action", "")).strip().lower()
    reason = str(parsed.get("reason", "")).strip()[:240]
    if action_raw not in {"reply", "no_reply"}:
        return ("no_reply", "", reason or "invalid_action")
    if action_raw == "reply":
        message = str(parsed.get("message", "")).strip()
        if not message:
            return ("no_reply", "", reason or "empty_reply")
        return ("reply", message[:2000], reason)
    return ("no_reply", "", reason)


def _build_followup_prompt(history: list[tuple[str, str]]) -> list[dict[str, str]]:
    compact = "\n".join(f"{role}: {content[:500]}" for role, content in history if content.strip())
    if not compact:
        compact = "(no recent messages)"
    return [
        {
            "role": "system",
            "content": (
                "You decide whether Jarvis should proactively send a follow-up message now. "
                "Return strict JSON only: "
                '{"action":"reply"|"no_reply","message":"...","reason":"..."}. '
                "Use action=no_reply when there is no concrete, useful update. "
                "Do not ask questions unless there is an actionable update."
            ),
        },
        {
            "role": "user",
            "content": (
                "Recent thread history:\n"
                f"{compact}\n\n"
                "Decide if a proactive follow-up should be sent now. "
                "If no meaningful update exists, return no_reply."
            ),
        },
    ]


async def _evaluate(
    router: ProviderRouter, history: list[tuple[str, str]]
) -> tuple[str, str, str, str]:
    resp, lane, _primary_error = await router.generate(
        _build_followup_prompt(history),
        tools=None,
        temperature=0.1,
        max_tokens=300,
        priority="low",
    )
    action, message, reason = _parse_decision(resp.text)
    return action, message, reason, lane


def _touch_followup_row(
    *,
    thread_id: str,
    enabled: bool,
    last_result: str,
    last_checked_at: str,
    last_sent_at: str | None,
    increment_no_reply: bool,
) -> None:
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO thread_followups("
                "thread_id, enabled, last_checked_at, last_sent_at, last_result, "
                "consecutive_no_reply, updated_at, created_at"
                ") VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(thread_id) DO UPDATE SET "
                "enabled=excluded.enabled, "
                "last_checked_at=excluded.last_checked_at, "
                "last_sent_at=excluded.last_sent_at, "
                "last_result=excluded.last_result, "
                "consecutive_no_reply=CASE "
                "WHEN excluded.last_result='no_reply' "
                "THEN thread_followups.consecutive_no_reply + 1 "
                "ELSE 0 END, "
                "updated_at=excluded.updated_at"
            ),
            (
                thread_id,
                1 if enabled else 0,
                last_checked_at,
                last_sent_at,
                last_result,
                1 if increment_no_reply else 0,
                now_iso(),
                now_iso(),
            ),
        )


def _dispatch_channel_message(*, thread_id: str, message_id: str, trace_id: str) -> bool:
    from jarvis.tasks import get_task_runner

    with get_conn() as conn:
        row = conn.execute(
            (
                "SELECT c.channel_type FROM threads t "
                "JOIN channels c ON c.id=t.channel_id WHERE t.id=? LIMIT 1"
            ),
            (thread_id,),
        ).fetchone()
        if row is None:
            return False
        channel_type = str(row["channel_type"])
        if not channel_type or channel_type == "web":
            return True
        _emit(
            "channel.dispatch.enqueue.start",
            {"message_id": message_id, "channel_type": channel_type, "source": "followup"},
            thread_id=thread_id,
            trace_id=trace_id,
        )
    ok = get_task_runner().send_task(
        "jarvis.tasks.channel.send_channel_message",
        kwargs={
            "thread_id": thread_id,
            "message_id": message_id,
            "channel_type": channel_type,
        },
        queue="tools_io",
    )
    _emit(
        "channel.dispatch.enqueue.end" if ok else "channel.dispatch.enqueue.failed",
        {
            "message_id": message_id,
            "channel_type": channel_type,
            "source": "followup",
        },
        thread_id=thread_id,
        trace_id=trace_id,
    )
    return ok


def followup_heartbeat_tick() -> dict[str, object]:
    settings = get_settings()
    trace_id = new_id("trc")
    now_dt = datetime.now(UTC)
    idle_threshold = max(0, int(settings.followup_min_idle_seconds))
    limit = max(1, int(settings.followup_max_threads_per_tick))
    emit_idle_ticks = int(settings.followup_emit_idle_ticks) == 1

    with get_conn() as conn:
        rows = conn.execute(
            (
                "SELECT f.thread_id, f.enabled, f.last_checked_at, f.last_sent_at, "
                "f.consecutive_no_reply, t.status "
                "FROM thread_followups f "
                "JOIN threads t ON t.id=f.thread_id "
                "WHERE f.enabled=1 ORDER BY COALESCE(f.last_checked_at, f.created_at) ASC LIMIT ?"
            ),
            (limit,),
        ).fetchall()

    if not rows:
        result = {
            "ok": True,
            "trace_id": trace_id,
            "checked": 0,
            "sent": 0,
            "no_reply": 0,
            "skipped": 0,
            "errors": 0,
        }
        if emit_idle_ticks:
            _emit(
                "followup.tick.start",
                {
                    "max_threads": limit,
                    "idle_seconds": idle_threshold,
                },
                thread_id=None,
                trace_id=trace_id,
            )
            _emit("followup.tick.end", result, thread_id=None, trace_id=trace_id)
        return result

    _emit(
        "followup.tick.start",
        {
            "max_threads": limit,
            "idle_seconds": idle_threshold,
        },
        thread_id=None,
        trace_id=trace_id,
    )

    router = ProviderRouter(
        build_primary_provider(settings),
        build_fallback_provider(settings),
    )

    checked = 0
    sent = 0
    no_reply = 0
    skipped = 0
    errors = 0

    for row in rows:
        thread_id = str(row["thread_id"])
        checked += 1

        with get_conn() as conn:
            if str(row["status"] or "") != "open":
                skipped += 1
                _emit(
                    "followup.skipped",
                    {"thread_id": thread_id, "reason": "thread_closed"},
                    thread_id=thread_id,
                    trace_id=trace_id,
                )
                continue
            running = conn.execute(
                "SELECT 1 FROM agent_run_attempts WHERE thread_id=? AND status='running' LIMIT 1",
                (thread_id,),
            ).fetchone()
            if running is not None:
                skipped += 1
                _emit(
                    "followup.skipped",
                    {"thread_id": thread_id, "reason": "active_run"},
                    thread_id=thread_id,
                    trace_id=trace_id,
                )
                continue
            last_msg_row = conn.execute(
                (
                    "SELECT created_at FROM messages "
                    "WHERE thread_id=? ORDER BY created_at DESC LIMIT 1"
                ),
                (thread_id,),
            ).fetchone()
            if last_msg_row is not None and idle_threshold > 0:
                try:
                    last_msg_at = datetime.fromisoformat(str(last_msg_row["created_at"]))
                except ValueError:
                    last_msg_at = now_dt
                if (now_dt - last_msg_at).total_seconds() < float(idle_threshold):
                    skipped += 1
                    _emit(
                        "followup.skipped",
                        {"thread_id": thread_id, "reason": "recent_activity"},
                        thread_id=thread_id,
                        trace_id=trace_id,
                    )
                    continue
            history_rows = conn.execute(
                (
                    "SELECT role, content FROM messages "
                    "WHERE thread_id=? ORDER BY created_at DESC LIMIT 10"
                ),
                (thread_id,),
            ).fetchall()

        history = [
            (str(item["role"]), str(item["content"])) for item in reversed(history_rows)
        ]
        checked_at = now_iso()
        try:
            action, message, reason, lane = asyncio.run(_evaluate(router, history))
        except Exception as exc:
            errors += 1
            logger.exception("followup evaluation failed for thread_id=%s", thread_id)
            _touch_followup_row(
                thread_id=thread_id,
                enabled=True,
                last_result="error",
                last_checked_at=checked_at,
                last_sent_at=str(row["last_sent_at"]) if row["last_sent_at"] else None,
                increment_no_reply=False,
            )
            _emit(
                "followup.error",
                {
                    "thread_id": thread_id,
                    "error": str(exc)[:300],
                },
                thread_id=thread_id,
                trace_id=trace_id,
            )
            continue

        if action == "no_reply":
            no_reply += 1
            _touch_followup_row(
                thread_id=thread_id,
                enabled=True,
                last_result="no_reply",
                last_checked_at=checked_at,
                last_sent_at=str(row["last_sent_at"]) if row["last_sent_at"] else None,
                increment_no_reply=True,
            )
            _emit(
                "followup.no_reply",
                {
                    "thread_id": thread_id,
                    "reason": reason,
                    "lane": lane,
                },
                thread_id=thread_id,
                trace_id=trace_id,
            )
            continue

        with get_conn() as conn:
            message_id = insert_message(conn, thread_id, "assistant", message)
        dispatch_ok = _dispatch_channel_message(
            thread_id=thread_id,
            message_id=message_id,
            trace_id=trace_id,
        )
        sent += 1
        _touch_followup_row(
            thread_id=thread_id,
            enabled=True,
            last_result="reply",
            last_checked_at=checked_at,
            last_sent_at=checked_at,
            increment_no_reply=False,
        )
        _emit(
            "followup.sent",
            {
                "thread_id": thread_id,
                "message_id": message_id,
                "lane": lane,
                "reason": reason,
                "dispatch_ok": dispatch_ok,
            },
            thread_id=thread_id,
            trace_id=trace_id,
        )

    result = {
        "ok": True,
        "trace_id": trace_id,
        "checked": checked,
        "sent": sent,
        "no_reply": no_reply,
        "skipped": skipped,
        "errors": errors,
    }
    _emit("followup.tick.end", result, thread_id=None, trace_id=trace_id)
    return result
