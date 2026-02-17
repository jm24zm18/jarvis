"""Event search + trace API routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from jarvis.auth.dependencies import UserContext, require_auth
from jarvis.db.connection import get_conn

router = APIRouter(tags=["api-events"])


def _parse_json_payload(raw_value: str) -> dict[str, object]:
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {"raw": raw_value}
    return parsed if isinstance(parsed, dict) else {"raw": raw_value}


@router.get("/events")
def search_events(
    ctx: UserContext = Depends(require_auth),  # noqa: B008
    event_type: str | None = None,
    component: str | None = None,
    thread_id: str | None = None,
    query: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    filters: list[str] = []
    params: list[object] = []
    if event_type:
        filters.append("event_type=?")
        params.append(event_type)
    if component:
        filters.append("component=?")
        params.append(component)
    if thread_id:
        filters.append("e.thread_id=?")
        params.append(thread_id)
    if not ctx.is_admin:
        filters.append(
            "(e.thread_id IS NULL OR EXISTS("
            "SELECT 1 FROM threads t WHERE t.id=e.thread_id AND t.user_id=?"
            "))"
        )
        params.append(ctx.user_id)
    if query:
        filters.append("e.payload_redacted_json LIKE ?")
        params.append(f"%{query}%")

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    sql = (
        "SELECT e.id, e.trace_id, e.span_id, e.parent_span_id, e.thread_id, "
        "e.event_type, e.component, e.actor_type, e.actor_id, "
        "e.payload_redacted_json, e.created_at "
        f"FROM events e {where} "
        "ORDER BY e.created_at DESC LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])

    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    items = []
    for row in rows:
        payload = str(row["payload_redacted_json"])
        parsed = _parse_json_payload(payload)
        items.append(
            {
                "id": str(row["id"]),
                "trace_id": str(row["trace_id"]),
                "span_id": str(row["span_id"]),
                "parent_span_id": str(row["parent_span_id"]) if row["parent_span_id"] else None,
                "thread_id": str(row["thread_id"]) if row["thread_id"] else None,
                "event_type": str(row["event_type"]),
                "component": str(row["component"]),
                "actor_type": str(row["actor_type"]),
                "actor_id": str(row["actor_id"]),
                "payload": parsed,
                "created_at": str(row["created_at"]),
            }
        )
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/events/{event_id}")
def get_event(event_id: str, ctx: UserContext = Depends(require_auth)) -> dict[str, object]:  # noqa: B008
    with get_conn() as conn:
        row = conn.execute(
            (
                "SELECT id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_redacted_json, created_at "
                "FROM events WHERE id=? LIMIT 1"
            ),
            (event_id,),
        ).fetchone()
        if row is not None and not ctx.is_admin and row["thread_id"] is not None:
            owner = conn.execute(
                "SELECT user_id FROM threads WHERE id=? LIMIT 1",
                (str(row["thread_id"]),),
            ).fetchone()
            if owner is None or str(owner["user_id"]) != ctx.user_id:
                raise HTTPException(status_code=403, detail="forbidden")
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")
    return {
        "id": str(row["id"]),
        "trace_id": str(row["trace_id"]),
        "span_id": str(row["span_id"]),
        "parent_span_id": str(row["parent_span_id"]) if row["parent_span_id"] else None,
        "thread_id": str(row["thread_id"]) if row["thread_id"] else None,
        "event_type": str(row["event_type"]),
        "component": str(row["component"]),
        "actor_type": str(row["actor_type"]),
        "actor_id": str(row["actor_id"]),
        "payload_redacted_json": str(row["payload_redacted_json"]),
        "created_at": str(row["created_at"]),
    }


@router.get("/traces/{trace_id}")
def get_trace(
    trace_id: str,
    view: str = Query(default="redacted", pattern="^(redacted|raw)$"),
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, object]:  # noqa: B008
    raw_view = view == "raw"
    with get_conn() as conn:
        if ctx.is_admin:
            payload_column = "payload_json" if raw_view else "payload_redacted_json"
            rows = conn.execute(
                (
                    "SELECT id, span_id, parent_span_id, thread_id, event_type, component, "
                    f"actor_type, actor_id, {payload_column} AS payload, created_at "
                    "FROM events WHERE trace_id=? ORDER BY created_at ASC"
                ),
                (trace_id,),
            ).fetchall()
        else:
            payload_column = "e.payload_json" if raw_view else "e.payload_redacted_json"
            rows = conn.execute(
                (
                    "SELECT e.id, e.span_id, e.parent_span_id, e.thread_id, e.event_type, "
                    f"e.component, e.actor_type, e.actor_id, {payload_column} AS payload, "
                    "e.created_at "
                    "FROM events e LEFT JOIN threads t ON t.id=e.thread_id "
                    "WHERE e.trace_id=? AND (e.thread_id IS NULL OR t.user_id=?) "
                    "ORDER BY e.created_at ASC"
                ),
                (trace_id, ctx.user_id),
            ).fetchall()
    items = [
        {
            "id": str(row["id"]),
            "span_id": str(row["span_id"]),
            "parent_span_id": str(row["parent_span_id"]) if row["parent_span_id"] else None,
            "thread_id": str(row["thread_id"]) if row["thread_id"] else None,
            "event_type": str(row["event_type"]),
            "component": str(row["component"]),
            "actor_type": str(row["actor_type"]),
            "actor_id": str(row["actor_id"]),
            "payload": _parse_json_payload(str(row["payload"])),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]
    return {"trace_id": trace_id, "view": view, "items": items}
