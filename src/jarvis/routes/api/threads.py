"""Thread CRUD API routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from jarvis.auth.dependencies import UserContext, require_auth
from jarvis.db.connection import get_conn
from jarvis.db.queries import create_thread, ensure_channel, set_thread_agents, set_thread_verbose

router = APIRouter(tags=["api-threads"])


@router.get("/threads")
def list_threads(
    ctx: UserContext = Depends(require_auth),
    all_threads: bool = Query(default=False, alias="all"),
    status: str | None = None,
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    filters: list[str] = []
    params: list[object] = []
    if all_threads and not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin required")
    if not all_threads:
        filters.append("t.user_id=?")
        params.append(ctx.user_id)
    if status:
        filters.append("t.status=?")
        params.append(status)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    query = (
        "SELECT t.id, t.status, t.created_at, t.updated_at, c.channel_type, "
        "(SELECT content FROM messages m WHERE m.thread_id=t.id "
        "ORDER BY m.created_at DESC LIMIT 1) "
        "AS last_message "
        "FROM threads t JOIN channels c ON c.id=t.channel_id "
        f"{where} "
        "ORDER BY t.updated_at DESC LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])

    with get_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    items = [
        {
            "id": str(row["id"]),
            "status": str(row["status"]),
            "channel_type": str(row["channel_type"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "last_message": str(row["last_message"]) if row["last_message"] is not None else None,
        }
        for row in rows
    ]
    return {"items": items, "limit": limit, "offset": offset}


@router.post("/threads")
def create_web_thread(ctx: UserContext = Depends(require_auth)) -> dict[str, str]:
    with get_conn() as conn:
        channel_id = ensure_channel(conn, ctx.user_id, "web")
        thread_id = create_thread(conn, ctx.user_id, channel_id)
    return {"id": thread_id, "channel_type": "web"}


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str, ctx: UserContext = Depends(require_auth)) -> dict[str, object]:
    with get_conn() as conn:
        row = conn.execute(
            (
                "SELECT t.id, t.user_id, t.status, t.created_at, t.updated_at, c.channel_type "
                "FROM threads t JOIN channels c ON c.id=t.channel_id "
                "WHERE t.id=? LIMIT 1"
            ),
            (thread_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="thread not found")
        if not ctx.is_admin and str(row["user_id"]) != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")
        settings_row = conn.execute(
            "SELECT verbose, active_agent_ids_json FROM thread_settings WHERE thread_id=?",
            (thread_id,),
        ).fetchone()

    active_agents: list[str] = ["main", "researcher", "planner", "coder"]
    verbose = False
    if settings_row is not None:
        verbose = int(settings_row["verbose"]) == 1
        raw = settings_row["active_agent_ids_json"]
        if isinstance(raw, str):
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, list):
                    active_agents = [str(item) for item in decoded if isinstance(item, str)]
            except json.JSONDecodeError:
                pass

    return {
        "id": str(row["id"]),
        "status": str(row["status"]),
        "channel_type": str(row["channel_type"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "settings": {"verbose": verbose, "active_agent_ids": active_agents},
    }


@router.patch("/threads/{thread_id}")
def patch_thread(
    thread_id: str, payload: dict[str, object], ctx: UserContext = Depends(require_auth)
) -> dict[str, bool]:
    with get_conn() as conn:
        row = conn.execute("SELECT id, user_id FROM threads WHERE id=?", (thread_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="thread not found")
        if not ctx.is_admin and str(row["user_id"]) != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")

        if "status" in payload and isinstance(payload["status"], str):
            conn.execute(
                "UPDATE threads SET status=?, updated_at=datetime('now') WHERE id=?",
                (payload["status"], thread_id),
            )
        if "verbose" in payload:
            set_thread_verbose(conn, thread_id, bool(payload["verbose"]))
        if "active_agent_ids" in payload and isinstance(payload["active_agent_ids"], list):
            agents = [str(item) for item in payload["active_agent_ids"] if isinstance(item, str)]
            if agents:
                set_thread_agents(conn, thread_id, agents)
    return {"ok": True}


def _stream_thread_jsonl(thread_id: str, include_events: bool = False):
    """Generator that yields JSONL lines for a thread's data."""
    with get_conn() as conn:
        # Messages
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE thread_id=? ORDER BY created_at ASC",
            (thread_id,),
        ).fetchall()
        for row in rows:
            yield json.dumps({
                "type": "message",
                "id": str(row["id"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "created_at": str(row["created_at"]),
            }) + "\n"

        # Memory items
        mem_rows = conn.execute(
            "SELECT id, text, created_at FROM memory_items "
            "WHERE thread_id=? ORDER BY created_at ASC",
            (thread_id,),
        ).fetchall()
        for row in mem_rows:
            yield json.dumps({
                "type": "memory",
                "id": str(row["id"]),
                "text": str(row["text"]),
                "created_at": str(row["created_at"]),
            }) + "\n"

        # Events (optional, can be large)
        if include_events:
            event_rows = conn.execute(
                "SELECT id, event_type, component, actor_type, actor_id, "
                "payload_redacted_json, created_at FROM events "
                "WHERE thread_id=? ORDER BY created_at ASC",
                (thread_id,),
            ).fetchall()
            for row in event_rows:
                yield json.dumps({
                    "type": "event",
                    "id": str(row["id"]),
                    "event_type": str(row["event_type"]),
                    "component": str(row["component"]),
                    "actor_type": str(row["actor_type"]),
                    "actor_id": str(row["actor_id"]),
                    "payload": str(row["payload_redacted_json"]),
                    "created_at": str(row["created_at"]),
                }) + "\n"

        # Thread summary
        summary_row = conn.execute(
            "SELECT short_summary, long_summary, updated_at FROM thread_summaries "
            "WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
        if summary_row is not None:
            yield json.dumps({
                "type": "summary",
                "short_summary": str(summary_row["short_summary"]),
                "long_summary": str(summary_row["long_summary"]),
                "updated_at": str(summary_row["updated_at"]),
            }) + "\n"


@router.get("/threads/{thread_id}/export")
def export_thread(
    thread_id: str,
    ctx: UserContext = Depends(require_auth),
    include_events: bool = Query(default=False),
) -> StreamingResponse:
    """Export thread data as streaming JSONL."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM threads WHERE id=? LIMIT 1", (thread_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="thread not found")
        if not ctx.is_admin and str(row["user_id"]) != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")

    return StreamingResponse(
        _stream_thread_jsonl(thread_id, include_events=include_events),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{thread_id}.jsonl"'},
    )


@router.get("/threads/export/bulk")
def export_bulk(
    ctx: UserContext = Depends(require_auth),
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> StreamingResponse:
    """Admin-only: export multiple threads as JSONL."""
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin required")

    def _generate():
        with get_conn() as conn:
            filters = []
            params: list[object] = []
            if status:
                filters.append("t.status=?")
                params.append(status)
            where = f"WHERE {' AND '.join(filters)}" if filters else ""
            thread_rows = conn.execute(
                f"SELECT t.id FROM threads t {where} "
                "ORDER BY t.updated_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()

        for thread_row in thread_rows:
            tid = str(thread_row["id"])
            yield from _stream_thread_jsonl(tid, include_events=False)

    return StreamingResponse(
        _generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="bulk_export.jsonl"'},
    )
