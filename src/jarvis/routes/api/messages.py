"""Message list/send API routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from jarvis.auth.dependencies import UserContext, require_auth
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import insert_message, now_iso, verify_thread_owner
from jarvis.ids import new_id
from jarvis.onboarding.service import (
    get_assistant_name,
    get_onboarding_status,
    get_user_name,
    is_onboarding_active,
    start_onboarding_prompt,
)
from jarvis.providers.factory import build_fallback_provider, build_primary_provider
from jarvis.providers.router import ProviderRouter
from jarvis.tasks import get_task_runner

router = APIRouter(tags=["api-messages"])


def _send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
    try:
        return get_task_runner().send_task(name, kwargs=kwargs, queue=queue)
    except Exception:
        return False


@router.get("/threads/{thread_id}/messages")
def list_messages(
    thread_id: str,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
    before: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    assistant_name = get_assistant_name()
    with get_conn() as conn:
        owner_row = conn.execute(
            "SELECT user_id FROM threads WHERE id=? LIMIT 1", (thread_id,)
        ).fetchone()
        if owner_row is None:
            raise HTTPException(status_code=404, detail="thread not found")
        thread_user_id = str(owner_row["user_id"])
        if not ctx.is_admin:
            verify_thread_owner(conn, thread_id, ctx.user_id)
        user_name = get_user_name(conn, thread_user_id)
        if before:
            rows = conn.execute(
                (
                    "SELECT m.id, m.role, m.content, m.created_at, "
                    "       e.actor_id AS actor_id "
                    "FROM messages m "
                    "LEFT JOIN events e ON "
                    "  e.thread_id = m.thread_id "
                    "  AND e.event_type = 'agent.step.end' "
                    "  AND json_extract(e.payload_json, '$.message_id') = m.id "
                    "WHERE m.thread_id=? "
                    "  AND ("
                    "    m.role='user' "
                    "    OR (m.role='assistant' AND (e.actor_id IS NULL OR e.actor_id='main'))"
                    "  ) "
                    "  AND m.created_at < ? "
                    "ORDER BY m.created_at DESC LIMIT ?"
                ),
                (thread_id, before, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                (
                    "SELECT m.id, m.role, m.content, m.created_at, "
                    "       e.actor_id AS actor_id "
                    "FROM messages m "
                    "LEFT JOIN events e ON "
                    "  e.thread_id = m.thread_id "
                    "  AND e.event_type = 'agent.step.end' "
                    "  AND json_extract(e.payload_json, '$.message_id') = m.id "
                    "WHERE m.thread_id=? "
                    "  AND ("
                    "    m.role='user' "
                    "    OR (m.role='assistant' AND (e.actor_id IS NULL OR e.actor_id='main'))"
                    "  ) "
                    "ORDER BY m.created_at DESC LIMIT ?"
                ),
                (thread_id, limit),
            ).fetchall()

    items = []
    for row in reversed(rows):
        content = str(row["content"])
        items.append({
            "id": str(row["id"]),
            "role": str(row["role"]),
            "content": content,
            "created_at": str(row["created_at"]),
            "speaker": (
                (
                    user_name
                    if str(row["role"]) == "user"
                    else str(row["role"])
                )
                if str(row["role"]) != "assistant"
                else (
                    assistant_name
                    if (row["actor_id"] is None or str(row["actor_id"]) == "main")
                    else str(row["actor_id"])
                )
            ),
        })
    next_before = str(rows[-1]["created_at"]) if rows else None
    return {"items": items, "next_before": next_before}


@router.post("/threads/{thread_id}/messages")
async def send_message(
    thread_id: str, payload: dict[str, str], ctx: UserContext = Depends(require_auth)  # noqa: B008
) -> dict[str, object]:
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    trace_id = new_id("trc")
    degraded = False
    onboarding = False
    thread_user_id = ""
    with get_conn() as conn:
        thread_row = conn.execute(
            "SELECT id, user_id FROM threads WHERE id=? LIMIT 1", (thread_id,)
        ).fetchone()
        if thread_row is None:
            raise HTTPException(status_code=404, detail="thread not found")
        thread_user_id = str(thread_row["user_id"])
        if not ctx.is_admin and thread_user_id != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")
        message_id = insert_message(conn, thread_id, "user", content)
        conn.execute(
            (
                "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
                "VALUES(?,?,?,?)"
            ),
            (
                thread_id,
                "message.new",
                json.dumps({"message_id": message_id, "role": "user"}),
                now_iso(),
            ),
        )
        onboarding = not content.startswith("/") and is_onboarding_active(
            conn,
            user_id=thread_user_id,
        )

    index_ok = _send_task(
        "jarvis.tasks.memory.index_event",
        kwargs={"trace_id": trace_id, "thread_id": thread_id, "text": content},
        queue="tools_io",
    )
    if onboarding:
        step_ok = _send_task(
            "jarvis.tasks.onboarding.onboarding_step",
            kwargs={
                "trace_id": trace_id,
                "thread_id": thread_id,
                "user_id": thread_user_id,
                "user_message": content,
            },
            queue="agent_priority",
        )
    else:
        step_ok = _send_task(
            "jarvis.tasks.agent.agent_step",
            kwargs={"trace_id": trace_id, "thread_id": thread_id},
            queue="agent_priority",
        )
    degraded = not (index_ok and step_ok)

    return {
        "ok": True,
        "message_id": message_id,
        "trace_id": trace_id,
        "degraded": degraded,
        "onboarding": onboarding,
    }


@router.get("/threads/{thread_id}/onboarding")
def get_thread_onboarding_status(
    thread_id: str, ctx: UserContext = Depends(require_auth)  # noqa: B008
) -> dict[str, object]:
    with get_conn() as conn:
        thread_row = conn.execute(
            "SELECT id, user_id FROM threads WHERE id=? LIMIT 1", (thread_id,)
        ).fetchone()
        if thread_row is None:
            raise HTTPException(status_code=404, detail="thread not found")
        thread_user_id = str(thread_row["user_id"])
        if not ctx.is_admin and thread_user_id != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")
        return get_onboarding_status(conn, user_id=thread_user_id)


@router.post("/threads/{thread_id}/onboarding/start")
async def start_thread_onboarding(
    thread_id: str, ctx: UserContext = Depends(require_auth)  # noqa: B008
) -> dict[str, object]:
    with get_conn() as conn:
        thread_row = conn.execute(
            "SELECT id, user_id FROM threads WHERE id=? LIMIT 1", (thread_id,)
        ).fetchone()
        if thread_row is None:
            raise HTTPException(status_code=404, detail="thread not found")
        thread_user_id = str(thread_row["user_id"])
        if not ctx.is_admin and thread_user_id != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")
        settings = get_settings()
        router = ProviderRouter(
            build_primary_provider(settings),
            build_fallback_provider(settings),
        )
        prompt = await start_onboarding_prompt(
            conn=conn,
            router=router,
            user_id=thread_user_id,
            thread_id=thread_id,
        )
        if prompt is None:
            return {"ok": True, "prompted": False, "message_id": None}

        last_row = conn.execute(
            (
                "SELECT id, role, content FROM messages "
                "WHERE thread_id=? ORDER BY created_at DESC LIMIT 1"
            ),
            (thread_id,),
        ).fetchone()
        if (
            last_row is not None
            and str(last_row["role"]) == "assistant"
            and str(last_row["content"]) == prompt
        ):
            return {"ok": True, "prompted": False, "message_id": str(last_row["id"])}

        assistant_message_id = insert_message(conn, thread_id, "assistant", prompt)
        _ = _send_task(
            "jarvis.tasks.memory.index_event",
            kwargs={
                "trace_id": new_id("trc"),
                "thread_id": thread_id,
                "text": prompt,
                "metadata": {
                    "role": "assistant",
                    "actor_id": "main",
                    "message_id": assistant_message_id,
                    "source": "onboarding.start",
                },
            },
            queue="tools_io",
        )
        conn.execute(
            (
                "INSERT INTO web_notifications("
                "thread_id, event_type, payload_json, created_at"
                ") VALUES(?,?,?,?)"
            ),
            (
                thread_id,
                "message.new",
                json.dumps({"message_id": assistant_message_id, "role": "assistant"}),
                now_iso(),
            ),
        )
        return {"ok": True, "prompted": True, "message_id": assistant_message_id}
