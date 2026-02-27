"""Admin APIs for non-web reply approval gating."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from jarvis.auth.dependencies import UserContext, require_admin
from jarvis.db.connection import get_conn
from jarvis.ids import new_id
from jarvis.services.channel_reply_approval import (
    approve_request,
    list_approval_requests,
    list_permissions,
    reject_request,
    revoke_permission,
)

router = APIRouter(tags=["api-channel-reply-approvals"])


class ApproveBody(BaseModel):
    mode: str = "once"


class RejectBody(BaseModel):
    reason: str = ""


class RevokePermissionBody(BaseModel):
    channel_type: str
    recipient: str
    reason: str = "manual_revoke"


@router.get("/channel-reply-approvals")
def list_channel_reply_approvals(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    del ctx
    with get_conn() as conn:
        items = list_approval_requests(conn, status=status, limit=limit, offset=offset)
    return {"items": items}


@router.post("/channel-reply-approvals/{request_id}/approve")
def approve_channel_reply(
    request_id: str,
    body: ApproveBody,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    mode = str(body.mode or "once").strip().lower()
    if mode not in {"once", "always"}:
        return {"ok": False, "error": "mode must be 'once' or 'always'"}
    with get_conn() as conn:
        return approve_request(
            conn,
            request_id=request_id,
            approver_id=ctx.user_id,
            mode=mode,  # type: ignore[arg-type]
            trace_id=new_id("trc"),
        )


@router.post("/channel-reply-approvals/{request_id}/reject")
def reject_channel_reply(
    request_id: str,
    body: RejectBody,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    with get_conn() as conn:
        return reject_request(
            conn,
            request_id=request_id,
            approver_id=ctx.user_id,
            reason=str(body.reason or "").strip(),
            trace_id=new_id("trc"),
        )


@router.get("/channel-reply-permissions")
def list_channel_reply_permissions(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
    status: str | None = "active",
) -> dict[str, object]:
    del ctx
    with get_conn() as conn:
        return {"items": list_permissions(conn, status=status)}


@router.post("/channel-reply-permissions/revoke")
def revoke_channel_reply_permission(
    body: RevokePermissionBody,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    with get_conn() as conn:
        return revoke_permission(
            conn,
            channel_type=body.channel_type.strip().lower(),
            recipient=body.recipient.strip(),
            actor_id=ctx.user_id,
            reason=body.reason.strip(),
            trace_id=new_id("trc"),
        )
