"""Approval center API routes (admin only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from jarvis.auth.dependencies import UserContext, require_admin
from jarvis.db.connection import get_conn
from jarvis.services.approvals import (
    ALLOWED_ACTIONS,
    create_approval_record,
    list_approval_records,
    revoke_approval_record,
)

router = APIRouter(tags=["api-approvals"])


class CreateApprovalBody(BaseModel):
    action: str
    target_ref: str = ""
    ttl_minutes: int | None = None


@router.get("/approvals")
def list_approvals_endpoint(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
    action: str | None = None,
    status: str | None = None,
    target_ref: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    with get_conn() as conn:
        items = list_approval_records(
            conn,
            action=action,
            status=status,
            target_ref=target_ref,
            limit=limit,
            offset=offset,
        )
    return {"items": items, "allowed_actions": sorted(ALLOWED_ACTIONS)}


@router.post("/approvals")
def create_approval_endpoint(
    body: CreateApprovalBody,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    with get_conn() as conn:
        result = create_approval_record(
            conn,
            action=body.action,
            actor_id=ctx.user_id,
            target_ref=body.target_ref,
            ttl_minutes=body.ttl_minutes,
        )
    return result


@router.post("/approvals/{approval_id}/revoke")
def revoke_approval_endpoint(
    approval_id: str,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    with get_conn() as conn:
        result = revoke_approval_record(conn, approval_id, actor_id=ctx.user_id)
    return result
