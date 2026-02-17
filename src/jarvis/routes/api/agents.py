"""Agent browser API routes."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from jarvis.agents.loader import load_agent_registry
from jarvis.auth.dependencies import UserContext, require_auth
from jarvis.db.connection import get_conn

router = APIRouter(prefix="/agents", tags=["api-agents"])


@router.get("")
def list_agents(ctx: UserContext = Depends(require_auth)) -> dict[str, object]:  # noqa: B008
    del ctx
    try:
        bundles = load_agent_registry(Path("agents"))
    except RuntimeError:
        return {"items": []}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT principal_id, tool_name FROM tool_permissions WHERE effect='allow'"
        ).fetchall()
    tools_by_agent: dict[str, list[str]] = {}
    for row in rows:
        pid = str(row["principal_id"])
        tools_by_agent.setdefault(pid, []).append(str(row["tool_name"]))

    items = [
        {
            "id": bundle.agent_id,
            "description": bundle.identity_markdown.splitlines()[0]
            if bundle.identity_markdown
            else "",
            "tool_count": len(tools_by_agent.get(bundle.agent_id, bundle.allowed_tools)),
        }
        for bundle in bundles.values()
    ]
    return {"items": items}


@router.get("/{agent_id}")
def get_agent(agent_id: str, ctx: UserContext = Depends(require_auth)) -> dict[str, object]:  # noqa: B008
    del ctx
    try:
        bundles = load_agent_registry(Path("agents"))
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail="agent not found") from exc
    bundle = bundles.get(agent_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="agent not found")
    with get_conn() as conn:
        rows = conn.execute(
            (
                "SELECT tool_name, effect FROM tool_permissions "
                "WHERE principal_id=? ORDER BY tool_name"
            ),
            (agent_id,),
        ).fetchall()
    return {
        "id": bundle.agent_id,
        "identity_md": bundle.identity_markdown,
        "soul_md": bundle.soul_markdown,
        "heartbeat_md": bundle.heartbeat_markdown,
        "permissions": [
            {"tool_name": str(row["tool_name"]), "effect": str(row["effect"])} for row in rows
        ],
    }
