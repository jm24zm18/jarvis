"""Bug report CRUD API routes."""

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from jarvis.auth.dependencies import UserContext, require_auth
from jarvis.db.connection import get_conn
from jarvis.ids import new_id
from jarvis.tasks import get_task_runner

router = APIRouter(tags=["api-bugs"])

def _send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
    try:
        return get_task_runner().send_task(name, kwargs=kwargs, queue=queue)
    except Exception:
        return False


VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}
VALID_KINDS = {"bug", "feature"}


class CreateBugBody(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    thread_id: str | None = None
    trace_id: str | None = None
    kind: str = "bug"
    sync_to_github: bool = False


class UpdateBugBody(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee_agent: str | None = None


def _now() -> str:
    from datetime import datetime
    return datetime.now(UTC).isoformat()


@router.get("/bugs")
def list_bugs(
    ctx: UserContext = Depends(require_auth),  # noqa: B008
    status: str | None = None,
    priority: str | None = None,
    kind: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    filters: list[str] = []
    params: list[object] = []
    if not ctx.is_admin:
        filters.append("reporter_id=?")
        params.append(ctx.user_id)
    if status:
        filters.append("status=?")
        params.append(status)
    if priority:
        filters.append("priority=?")
        params.append(priority)
    if kind:
        if kind not in VALID_KINDS:
            raise HTTPException(status_code=400, detail=f"Invalid kind: {kind}")
        filters.append("kind=?")
        params.append(kind)
    if search:
        filters.append("(title LIKE ? OR description LIKE ?)")
        params.append(f"%{search}%")
        params.append(f"%{search}%")
    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM bug_reports{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        total_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM bug_reports{where}",
            tuple(params),
        ).fetchone()
        total = int(total_row["cnt"]) if total_row else 0
    return {"items": [dict(r) for r in rows], "total": total}


@router.post("/bugs")
def create_bug(
    body: CreateBugBody,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, object]:
    if body.priority not in VALID_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {body.priority}")
    if body.kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid kind: {body.kind}")
    bug_id = new_id("bug")
    now = _now()
    degraded = False
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO bug_reports(id, kind, title, description, status, priority, "
                "reporter_id, assignee_agent, thread_id, trace_id, "
                "github_issue_number, github_issue_url, github_synced_at, github_sync_error, "
                "created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                bug_id,
                body.kind,
                body.title,
                body.description,
                "open",
                body.priority,
                ctx.user_id,
                None,
                body.thread_id,
                body.trace_id,
                None,
                None,
                None,
                None,
                now,
                now,
            ),
        )
    github_sync_queued = False
    if body.sync_to_github:
        github_sync_queued = _send_task(
            "jarvis.tasks.github.github_issue_sync_bug_report",
            kwargs={"bug_id": bug_id},
            queue="tools_io",
        )
        degraded = not github_sync_queued
    return {
        "id": bug_id,
        "kind": body.kind,
        "github_sync_queued": github_sync_queued,
        "degraded": degraded,
    }


@router.get("/feature-requests")
def list_feature_requests(
    ctx: UserContext = Depends(require_auth),  # noqa: B008
    status: str | None = None,
    priority: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    return list_bugs(
        ctx=ctx,
        status=status,
        priority=priority,
        kind="feature",
        search=search,
        limit=limit,
        offset=offset,
    )


@router.post("/feature-requests")
def create_feature_request(
    body: CreateBugBody,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, object]:
    feature_body = CreateBugBody(
        title=body.title,
        description=body.description,
        priority=body.priority,
        thread_id=body.thread_id,
        trace_id=body.trace_id,
        kind="feature",
        sync_to_github=body.sync_to_github,
    )
    return create_bug(body=feature_body, ctx=ctx)


@router.patch("/bugs/{bug_id}")
def update_bug(
    bug_id: str,
    body: UpdateBugBody,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, bool]:
    updates: list[str] = []
    params: list[object] = []
    if body.title is not None:
        updates.append("title=?")
        params.append(body.title)
    if body.description is not None:
        updates.append("description=?")
        params.append(body.description)
    if body.status is not None:
        if body.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
        updates.append("status=?")
        params.append(body.status)
    if body.priority is not None:
        if body.priority not in VALID_PRIORITIES:
            raise HTTPException(status_code=400, detail=f"Invalid priority: {body.priority}")
        updates.append("priority=?")
        params.append(body.priority)
    if body.assignee_agent is not None:
        updates.append("assignee_agent=?")
        params.append(body.assignee_agent)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates.append("updated_at=?")
    params.append(_now())
    params.append(bug_id)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, reporter_id FROM bug_reports WHERE id=?",
            (bug_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Bug not found")
        if not ctx.is_admin and str(row["reporter_id"]) != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")
        conn.execute(
            f"UPDATE bug_reports SET {', '.join(updates)} WHERE id=?",
            tuple(params),
        )
    return {"ok": True}


@router.delete("/bugs/{bug_id}")
def delete_bug(
    bug_id: str,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, bool]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, reporter_id FROM bug_reports WHERE id=?",
            (bug_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Bug not found")
        if not ctx.is_admin and str(row["reporter_id"]) != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")
        conn.execute("DELETE FROM bug_reports WHERE id=?", (bug_id,))
    return {"ok": True}
