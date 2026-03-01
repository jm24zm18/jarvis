"""DevSwarm API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from jarvis.auth.dependencies import UserContext, require_auth
from jarvis.db.connection import get_conn
from jarvis.db.queries import get_devswarm_task
from jarvis.tasks import devswarm

router = APIRouter(prefix="/swarm", tags=["api-swarm"])

VALID_TASK_TYPES = {"feature", "bugfix", "refactor"}
VALID_STATUSES = {
    "queued",
    "running",
    "needs_attention",
    "ready_for_review",
    "done",
    "failed",
}


class SwarmCreateBody(BaseModel):
    description: str = Field(min_length=1)
    task_type: str = Field(default="feature")
    model: str | None = None


class SwarmNudgeBody(BaseModel):
    message: str = Field(min_length=1)


class SwarmCleanupBody(BaseModel):
    remove_worktrees: bool = False


@router.get("/tasks")
def list_swarm_tasks(
    ctx: UserContext = Depends(require_auth),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
) -> dict[str, object]:
    del ctx
    clean_status = status.strip() if isinstance(status, str) else ""
    if clean_status and clean_status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="invalid status")
    return devswarm.status(limit=limit, status=clean_status or None)


@router.post("/tasks")
def create_swarm_task(
    body: SwarmCreateBody,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, object]:
    del ctx
    clean_type = body.task_type.strip().lower()
    if clean_type not in VALID_TASK_TYPES:
        raise HTTPException(status_code=400, detail="invalid task_type")
    desc = body.description.strip()
    if not desc:
        raise HTTPException(status_code=400, detail="description is required")

    result = devswarm.create_task(
        description=desc,
        repo_path=str(Path.cwd().resolve()),
        model=body.model,
        task_type=clean_type,
    )
    if not bool(result.get("ok")):
        raise HTTPException(
            status_code=400,
            detail=str(result.get("error") or "swarm create failed"),
        )
    task_id = str(result.get("task_id") or "")
    if not task_id:
        raise HTTPException(status_code=500, detail="swarm create missing task id")

    detail = devswarm.get_task_detail(task_id)
    if not detail.get("ok"):
        return result
    return detail


@router.post("/tasks/{task_id}/nudge")
def nudge_swarm_task(
    task_id: str,
    body: SwarmNudgeBody,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, object]:
    del ctx
    with get_conn() as conn:
        row = get_devswarm_task(conn, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    result = devswarm.send_tmux(task_id, message)
    if not bool(result.get("ok")):
        raise HTTPException(
            status_code=400,
            detail=str(result.get("error") or "swarm nudge failed"),
        )
    detail = devswarm.get_task_detail(task_id)
    if detail.get("ok"):
        result["task"] = detail.get("item")
    return result


@router.post("/tasks/{task_id}/cleanup")
def cleanup_swarm_task(
    task_id: str,
    body: SwarmCleanupBody,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, object]:
    del ctx
    with get_conn() as conn:
        row = get_devswarm_task(conn, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")

    result = devswarm.cleanup(task_id=task_id, remove_worktrees=bool(body.remove_worktrees))
    detail = devswarm.get_task_detail(task_id)
    if detail.get("ok"):
        result["task"] = detail.get("item")
    return result
