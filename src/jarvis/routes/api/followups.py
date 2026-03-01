"""Thread follow-up heartbeat controls."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from jarvis.auth.dependencies import UserContext, require_auth
from jarvis.db.connection import get_conn
from jarvis.db.queries import now_iso

router = APIRouter(prefix="/followups", tags=["api-followups"])


def _assert_thread_access(conn: sqlite3.Connection, thread_id: str, ctx: UserContext) -> str:
    row = conn.execute("SELECT user_id FROM threads WHERE id=? LIMIT 1", (thread_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="thread not found")
    owner_id = str(row["user_id"])
    if owner_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="forbidden")
    return owner_id


@router.post("/threads/{thread_id}/enable")
def enable_followups(
    thread_id: str,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, object]:
    with get_conn() as conn:
        owner_id = _assert_thread_access(conn, thread_id, ctx)
        conn.execute(
            (
                "INSERT INTO thread_followups("
                "thread_id, enabled, last_checked_at, last_sent_at, last_result, "
                "consecutive_no_reply, updated_at, created_at"
                ") VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(thread_id) DO UPDATE SET "
                "enabled=1, updated_at=excluded.updated_at"
            ),
            (thread_id, 1, None, None, "no_reply", 0, now_iso(), now_iso()),
        )
    return {"ok": True, "thread_id": thread_id, "enabled": True, "owner_id": owner_id}


@router.post("/threads/{thread_id}/disable")
def disable_followups(
    thread_id: str,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, object]:
    with get_conn() as conn:
        owner_id = _assert_thread_access(conn, thread_id, ctx)
        conn.execute(
            (
                "INSERT INTO thread_followups("
                "thread_id, enabled, last_checked_at, last_sent_at, last_result, "
                "consecutive_no_reply, updated_at, created_at"
                ") VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(thread_id) DO UPDATE SET "
                "enabled=0, updated_at=excluded.updated_at"
            ),
            (thread_id, 0, None, None, "no_reply", 0, now_iso(), now_iso()),
        )
    return {"ok": True, "thread_id": thread_id, "enabled": False, "owner_id": owner_id}


@router.get("/threads/{thread_id}")
def get_followup_status(
    thread_id: str,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, object]:
    with get_conn() as conn:
        owner_id = _assert_thread_access(conn, thread_id, ctx)
        row = conn.execute(
            (
                "SELECT enabled, last_checked_at, last_sent_at, last_result, "
                "consecutive_no_reply, updated_at, created_at "
                "FROM thread_followups WHERE thread_id=?"
            ),
            (thread_id,),
        ).fetchone()

    if row is None:
        return {
            "thread_id": thread_id,
            "owner_id": owner_id,
            "enabled": False,
            "last_checked_at": None,
            "last_sent_at": None,
            "last_result": None,
            "consecutive_no_reply": 0,
            "updated_at": None,
            "created_at": None,
        }

    return {
        "thread_id": thread_id,
        "owner_id": owner_id,
        "enabled": int(row["enabled"]) == 1,
        "last_checked_at": str(row["last_checked_at"]) if row["last_checked_at"] else None,
        "last_sent_at": str(row["last_sent_at"]) if row["last_sent_at"] else None,
        "last_result": str(row["last_result"]),
        "consecutive_no_reply": int(row["consecutive_no_reply"] or 0),
        "updated_at": str(row["updated_at"]),
        "created_at": str(row["created_at"]),
    }
