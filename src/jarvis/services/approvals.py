"""Generic approval lifecycle service."""

from __future__ import annotations

import sqlite3

from fastapi import HTTPException

from jarvis.config import get_settings
from jarvis.db.queries import create_approval, list_approvals, revoke_approval

ALLOWED_ACTIONS = {"selfupdate.apply", "host.exec.shell", "host.exec.script"}


def list_approval_records(
    conn: sqlite3.Connection,
    *,
    action: str | None = None,
    status: str | None = None,
    target_ref: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, object]]:
    return list_approvals(
        conn,
        action=action,
        status=status,
        target_ref=target_ref,
        limit=limit,
        offset=offset,
    )


def create_approval_record(
    conn: sqlite3.Connection,
    *,
    action: str,
    actor_id: str,
    target_ref: str = "",
    ttl_minutes: int | None = None,
) -> dict[str, object]:
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported action {action!r}. Allowed: {sorted(ALLOWED_ACTIONS)}",
        )
    settings = get_settings()
    effective_ttl = ttl_minutes if ttl_minutes is not None else int(settings.approval_ttl_minutes)
    approval_id = create_approval(
        conn,
        action=action,
        actor_id=actor_id,
        target_ref=target_ref,
        ttl_minutes=max(1, effective_ttl),
    )
    return {
        "approval_id": approval_id,
        "action": action,
        "target_ref": target_ref,
        "ttl_minutes": effective_ttl,
    }


def revoke_approval_record(
    conn: sqlite3.Connection,
    approval_id: str,
    *,
    actor_id: str,
) -> dict[str, object]:
    revoked = revoke_approval(conn, approval_id, actor_id=actor_id)
    if not revoked:
        raise HTTPException(
            status_code=404,
            detail="Approval not found or not in an active state",
        )
    return {"approval_id": approval_id, "status": "revoked"}
