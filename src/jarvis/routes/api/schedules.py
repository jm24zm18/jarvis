"""Schedule manager API routes."""

from fastapi import APIRouter, Depends, HTTPException

from jarvis.auth.dependencies import UserContext, require_auth
from jarvis.db.connection import get_conn
from jarvis.db.queries import now_iso
from jarvis.ids import new_id

router = APIRouter(prefix="/schedules", tags=["api-schedules"])


@router.get("")
def list_schedules(ctx: UserContext = Depends(require_auth)) -> dict[str, object]:
    with get_conn() as conn:
        if ctx.is_admin:
            rows = conn.execute(
                "SELECT id, thread_id, cron_expr, payload_json, enabled, last_run_at, "
                "created_at, max_catchup FROM schedules ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT s.id, s.thread_id, s.cron_expr, s.payload_json, s.enabled, s.last_run_at, "
                "s.created_at, s.max_catchup "
                "FROM schedules s JOIN threads t ON t.id=s.thread_id "
                "WHERE t.user_id=? "
                "ORDER BY s.created_at DESC",
                (ctx.user_id,),
            ).fetchall()
    return {
        "items": [
            {
                "id": str(row["id"]),
                "thread_id": str(row["thread_id"]) if row["thread_id"] else None,
                "cron_expr": str(row["cron_expr"]),
                "payload_json": str(row["payload_json"]),
                "enabled": int(row["enabled"]) == 1,
                "last_run_at": str(row["last_run_at"]) if row["last_run_at"] else None,
                "created_at": str(row["created_at"]),
                "max_catchup": int(row["max_catchup"]) if row["max_catchup"] is not None else None,
            }
            for row in rows
        ]
    }


@router.post("")
def create_schedule(
    payload: dict[str, object], ctx: UserContext = Depends(require_auth)
) -> dict[str, str]:
    cron_expr = str(payload.get("cron_expr", "")).strip()
    payload_json = str(payload.get("payload_json", "{}"))
    thread_id = str(payload.get("thread_id", "")).strip() or None
    if not cron_expr:
        raise HTTPException(status_code=400, detail="cron_expr is required")
    schedule_id = new_id("sch")
    with get_conn() as conn:
        if thread_id:
            thread_row = conn.execute(
                "SELECT user_id FROM threads WHERE id=? LIMIT 1", (thread_id,)
            ).fetchone()
            if thread_row is None:
                raise HTTPException(status_code=404, detail="thread not found")
            if str(thread_row["user_id"]) != ctx.user_id:
                raise HTTPException(status_code=403, detail="forbidden")
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, last_run_at, "
                "created_at, max_catchup) VALUES(?,?,?,?,?,?,?,?)"
            ),
            (
                schedule_id,
                thread_id,
                cron_expr,
                payload_json,
                1,
                None,
                now_iso(),
                payload.get("max_catchup"),
            ),
        )
    return {"id": schedule_id}


@router.patch("/{schedule_id}")
def update_schedule(
    schedule_id: str,
    payload: dict[str, object],
    ctx: UserContext = Depends(require_auth),
) -> dict[str, bool]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT s.id, t.user_id AS thread_user_id "
            "FROM schedules s LEFT JOIN threads t ON t.id=s.thread_id "
            "WHERE s.id=?",
            (schedule_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        owner = row["thread_user_id"]
        if owner is None:
            if not ctx.is_admin:
                raise HTTPException(status_code=403, detail="forbidden")
        elif not ctx.is_admin and str(owner) != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")
        if "enabled" in payload:
            conn.execute(
                "UPDATE schedules SET enabled=? WHERE id=?",
                (1 if bool(payload["enabled"]) else 0, schedule_id),
            )
        if "cron_expr" in payload and isinstance(payload["cron_expr"], str):
            conn.execute(
                "UPDATE schedules SET cron_expr=? WHERE id=?", (payload["cron_expr"], schedule_id)
            )
        if "payload_json" in payload and isinstance(payload["payload_json"], str):
            conn.execute(
                "UPDATE schedules SET payload_json=? WHERE id=?",
                (payload["payload_json"], schedule_id),
            )
        if "max_catchup" in payload:
            conn.execute(
                "UPDATE schedules SET max_catchup=? WHERE id=?",
                (payload["max_catchup"], schedule_id),
            )
    return {"ok": True}


@router.get("/{schedule_id}/dispatches")
def list_dispatches(
    schedule_id: str, ctx: UserContext = Depends(require_auth)
) -> dict[str, object]:
    with get_conn() as conn:
        schedule_row = conn.execute(
            "SELECT s.id, t.user_id AS thread_user_id "
            "FROM schedules s LEFT JOIN threads t ON t.id=s.thread_id "
            "WHERE s.id=?",
            (schedule_id,),
        ).fetchone()
        if schedule_row is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        owner = schedule_row["thread_user_id"]
        if owner is None:
            if not ctx.is_admin:
                raise HTTPException(status_code=403, detail="forbidden")
        elif not ctx.is_admin and str(owner) != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")
        rows = conn.execute(
            (
                "SELECT schedule_id, due_at, dispatched_at FROM schedule_dispatches "
                "WHERE schedule_id=? ORDER BY dispatched_at DESC LIMIT 200"
            ),
            (schedule_id,),
        ).fetchall()
    return {
        "items": [
            {
                "schedule_id": str(row["schedule_id"]),
                "due_at": str(row["due_at"]),
                "dispatched_at": str(row["dispatched_at"]),
            }
            for row in rows
        ]
    }
