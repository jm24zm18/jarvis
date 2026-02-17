"""Tool permission editor routes."""

from fastapi import APIRouter, Depends

from jarvis.auth.dependencies import UserContext, require_admin
from jarvis.db.connection import get_conn

router = APIRouter(prefix="/permissions", tags=["api-permissions"])


@router.get("")
def get_permissions(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT p.id AS principal_id, p.principal_type, tp.tool_name, tp.effect "
            "FROM principals p LEFT JOIN tool_permissions tp ON tp.principal_id=p.id "
            "ORDER BY p.id ASC, tp.tool_name ASC"
        ).fetchall()

    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        principal_id = str(row["principal_id"])
        item = grouped.setdefault(
            principal_id,
            {
                "principal_id": principal_id,
                "principal_type": str(row["principal_type"]),
                "tools": {},
            },
        )
        if row["tool_name"] is not None:
            tools = item["tools"]
            assert isinstance(tools, dict)
            tools[str(row["tool_name"])] = str(row["effect"])
    return {"items": list(grouped.values())}


@router.put("/{principal_id}/{tool_name}")
def set_permission(
    principal_id: str,
    tool_name: str,
    ctx: UserContext = Depends(require_admin),  # TODO: admin-only now  # noqa: B008
) -> dict[str, bool]:
    del ctx
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT OR REPLACE INTO tool_permissions("
                "principal_id, tool_name, effect"
                ") VALUES(?,?,?)"
            ),
            (principal_id, tool_name, "allow"),
        )
    return {"ok": True}


@router.delete("/{principal_id}/{tool_name}")
def delete_permission(
    principal_id: str,
    tool_name: str,
    ctx: UserContext = Depends(require_admin),  # TODO: admin-only now  # noqa: B008
) -> dict[str, bool]:
    del ctx
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM tool_permissions WHERE principal_id=? AND tool_name=?",
            (principal_id, tool_name),
        )
    return {"ok": True}
