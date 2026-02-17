"""Governance inspection and reload routes."""

from pathlib import Path

from fastapi import APIRouter, Depends

from jarvis.agents.loader import load_agent_registry, reset_loader_caches
from jarvis.agents.registry import sync_tool_permissions
from jarvis.auth.dependencies import UserContext, require_admin
from jarvis.db.connection import get_conn

router = APIRouter(prefix="/governance", tags=["api-governance"])


@router.get("/agents")
def list_agent_governance(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT principal_id, risk_tier, max_actions_per_step, allowed_paths_json, "
            "can_request_privileged_change, updated_at "
            "FROM agent_governance ORDER BY principal_id ASC"
        ).fetchall()
    return {
        "items": [
            {
                "principal_id": str(row["principal_id"]),
                "risk_tier": str(row["risk_tier"]),
                "max_actions_per_step": int(row["max_actions_per_step"]),
                "allowed_paths_json": str(row["allowed_paths_json"]),
                "can_request_privileged_change": int(row["can_request_privileged_change"]) == 1,
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]
    }


@router.post("/reload")
def reload_governance(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    reset_loader_caches()
    bundles = load_agent_registry(Path("agents"))
    with get_conn() as conn:
        sync_tool_permissions(conn, bundles)
    return {"ok": True, "agents": sorted(bundles.keys())}


@router.get("/audit")
def memory_governance_audit(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, thread_id, actor_id, decision, reason, target_kind, target_id, "
            "payload_redacted_json, created_at "
            "FROM memory_governance_audit ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    return {
        "items": [
            {
                "id": str(row["id"]),
                "thread_id": str(row["thread_id"]) if row["thread_id"] is not None else "",
                "actor_id": str(row["actor_id"]),
                "decision": str(row["decision"]),
                "reason": str(row["reason"]),
                "target_kind": str(row["target_kind"]),
                "target_id": str(row["target_id"]),
                "payload_redacted_json": str(row["payload_redacted_json"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
    }
