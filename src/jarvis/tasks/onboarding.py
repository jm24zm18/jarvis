"""Onboarding Celery task."""

import asyncio
import json
import logging

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import insert_message, now_iso
from jarvis.onboarding.service import maybe_handle_onboarding_message
from jarvis.providers.factory import build_fallback_provider, build_primary_provider
from jarvis.providers.router import ProviderRouter

logger = logging.getLogger(__name__)


def onboarding_step(trace_id: str, thread_id: str, user_id: str, user_message: str) -> str | None:
    start_created_at = now_iso()
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
                "VALUES(?,?,?,?)"
            ),
            (
                thread_id,
                "agent.thinking",
                json.dumps(
                    {
                        "thread_id": thread_id,
                        "agent_id": "main",
                        "trace_id": trace_id,
                        "created_at": start_created_at,
                    }
                ),
                start_created_at,
            ),
        )
        conn.execute(
            (
                "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
                "VALUES(?,?,?,?)"
            ),
            (
                thread_id,
                "trace.model.run.start",
                json.dumps(
                    {
                        "thread_id": thread_id,
                        "trace_id": trace_id,
                        "provider": "router",
                        "phase": "onboarding",
                        "created_at": start_created_at,
                    }
                ),
                start_created_at,
            ),
        )

    settings = get_settings()
    router = ProviderRouter(
        build_primary_provider(settings),
        build_fallback_provider(settings),
    )

    assistant_reply: str | None = None
    with get_conn() as conn:
        fallback_reason = ""
        try:
            assistant_reply = asyncio.run(
                maybe_handle_onboarding_message(
                    conn=conn,
                    router=router,
                    user_id=user_id,
                    thread_id=thread_id,
                    user_message=user_message,
                )
            )
        except Exception as exc:
            logger.exception("Onboarding handler failed for thread=%s", thread_id)
            fallback_reason = f"onboarding handler failed: {type(exc).__name__}: {exc}"
            assistant_reply = (
                "I hit an onboarding error while processing that message. "
                "Please try again, or run /onboarding reset to restart setup. "
                f"(trace: {trace_id})"
            )

        if assistant_reply and assistant_reply.startswith("I hit a temporary model"):
            fallback_reason = "router.generate failed for onboarding turn"

        if fallback_reason:
            fallback_created_at = now_iso()
            conn.execute(
                (
                    "INSERT INTO web_notifications"
                    "(thread_id, event_type, payload_json, created_at) "
                    "VALUES(?,?,?,?)"
                ),
                (
                    thread_id,
                    "trace.model.fallback",
                    json.dumps(
                        {
                            "thread_id": thread_id,
                            "trace_id": trace_id,
                            "error": fallback_reason,
                            "created_at": fallback_created_at,
                        }
                    ),
                    fallback_created_at,
                ),
            )

        message_id: str | None = None
        if assistant_reply is not None:
            message_id = insert_message(conn, thread_id, "assistant", assistant_reply)
            try:
                from jarvis.tasks import get_task_runner

                get_task_runner().send_task(
                    "jarvis.tasks.memory.index_event",
                    kwargs={
                        "trace_id": trace_id,
                        "thread_id": thread_id,
                        "text": assistant_reply,
                        "metadata": {
                            "role": "assistant",
                            "actor_id": "main",
                            "message_id": message_id,
                            "source": "onboarding.step",
                        },
                    },
                    queue="tools_io",
                )
            except Exception:
                logger.debug("failed to enqueue onboarding assistant memory indexing", exc_info=True)
            conn.execute(
                (
                    "INSERT INTO web_notifications("
                    "thread_id, event_type, payload_json, created_at"
                    ") "
                    "VALUES(?,?,?,?)"
                ),
                (
                    thread_id,
                    "message.new",
                    json.dumps({"message_id": message_id, "role": "assistant"}),
                    now_iso(),
                ),
            )

        end_created_at = now_iso()
        conn.execute(
            (
                "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
                "VALUES(?,?,?,?)"
            ),
            (
                thread_id,
                "trace.model.run.end",
                json.dumps(
                    {
                        "thread_id": thread_id,
                        "trace_id": trace_id,
                        "provider": "router",
                        "phase": "onboarding",
                        "created_at": end_created_at,
                    }
                ),
                end_created_at,
            ),
        )
        conn.execute(
            (
                "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
                "VALUES(?,?,?,?)"
            ),
            (
                thread_id,
                "agent.done",
                json.dumps(
                    {
                        "thread_id": thread_id,
                        "agent_id": "main",
                        "trace_id": trace_id,
                        "created_at": end_created_at,
                    }
                ),
                end_created_at,
            ),
        )
        return message_id
