import pytest

from jarvis.db.connection import get_conn
from jarvis.errors import PolicyError
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.runtime import ToolRuntime


@pytest.mark.asyncio
async def test_tool_denied_by_default() -> None:
    registry = ToolRegistry()

    async def handler(args):
        return {"ok": True, "args": args}

    registry.register("echo", "Echo", handler)
    runtime = ToolRuntime(registry)

    with get_conn() as conn:
        with pytest.raises(PolicyError):
            await runtime.execute(conn, "echo", {"x": 1}, "main", "trc_1")


@pytest.mark.asyncio
async def test_tool_allowed() -> None:
    registry = ToolRegistry()

    async def handler(args):
        return {"ok": True, "args": args}

    registry.register("echo", "Echo", handler)
    runtime = ToolRuntime(registry)

    with get_conn() as conn:
        stmt = (
            "INSERT OR REPLACE INTO principals(id, principal_type, created_at) "
            "VALUES(?,?,datetime('now'))"
        )
        conn.execute(
            stmt,
            ("main", "agent"),
        )
        conn.execute(
            (
                "INSERT OR REPLACE INTO tool_permissions("
                "principal_id, tool_name, effect"
                ") VALUES(?,?,?)"
            ),
            ("main", "echo", "allow"),
        )
        result = await runtime.execute(conn, "echo", {"x": 1}, "main", "trc_2")
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_session_tool_denied_for_worker() -> None:
    registry = ToolRegistry()

    async def handler(args):
        return {"ok": True, "args": args}

    registry.register("session_send", "Send session message", handler)
    runtime = ToolRuntime(registry)

    with get_conn() as conn:
        conn.execute(
            (
                "INSERT OR REPLACE INTO tool_permissions("
                "principal_id, tool_name, effect"
                ") VALUES(?,?,?)"
            ),
            ("researcher", "session_send", "allow"),
        )
        with pytest.raises(PolicyError, match="R5"):
            await runtime.execute(
                conn,
                "session_send",
                {"session_id": "s1", "to_agent_id": "main", "message": "x"},
                "researcher",
                "trc_3",
            )
