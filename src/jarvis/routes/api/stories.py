"""Story-run artifacts API."""

import json

from fastapi import APIRouter, Depends, Query

from jarvis.auth.dependencies import UserContext, require_admin
from jarvis.db.connection import get_conn
from jarvis.tasks.story_runner import run_story_pack

router = APIRouter(prefix="/stories", tags=["api-stories"])


@router.post("/run")
def run_stories(
    pack: str = Query(default="p0"),
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    return run_story_pack(pack=pack, created_by=ctx.user_id)


@router.get("/runs")
def list_story_runs(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, pack, status, summary, created_by, created_at "
            "FROM story_runs ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return {
        "items": [
            {
                "id": str(row["id"]),
                "pack": str(row["pack"]),
                "status": str(row["status"]),
                "summary": str(row["summary"]),
                "created_by": str(row["created_by"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
    }


@router.get("/runs/{run_id}")
def get_story_run(run_id: str, ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, pack, status, summary, report_json, created_by, created_at "
            "FROM story_runs WHERE id=? LIMIT 1",
            (run_id,),
        ).fetchone()
    if row is None:
        return {"item": None}
    report_raw = str(row["report_json"])
    try:
        report = json.loads(report_raw)
    except json.JSONDecodeError:
        report = []
    return {
        "item": {
            "id": str(row["id"]),
            "pack": str(row["pack"]),
            "status": str(row["status"]),
            "summary": str(row["summary"]),
            "report": report,
            "created_by": str(row["created_by"]),
            "created_at": str(row["created_at"]),
        }
    }

