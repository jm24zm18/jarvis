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
        start_query = (
            "SELECT COUNT(*) AS c FROM events WHERE trace_id='trc_1' "
            "AND event_type='tool.call.start'"
        )
        starts = conn.execute(
            start_query
        ).fetchone()
        end_query = (
            "SELECT COUNT(*) AS c FROM events WHERE trace_id='trc_1' "
            "AND event_type='tool.call.end'"
        )
        ends = conn.execute(
            end_query
        ).fetchone()
        assert int(starts["c"]) == 1
        assert int(ends["c"]) == 1


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
        start_query = (
            "SELECT COUNT(*) AS c FROM events WHERE trace_id='trc_3' "
            "AND event_type='tool.call.start'"
        )
        starts = conn.execute(
            start_query
        ).fetchone()
        end_query = (
            "SELECT COUNT(*) AS c FROM events WHERE trace_id='trc_3' "
            "AND event_type='tool.call.end'"
        )
        ends = conn.execute(
            end_query
        ).fetchone()
        assert int(starts["c"]) == 1
        assert int(ends["c"]) == 1


@pytest.mark.asyncio
async def test_unknown_tool_emits_terminal_event() -> None:
    runtime = ToolRuntime(ToolRegistry())
    with get_conn() as conn:
        with pytest.raises(PolicyError, match="R3"):
            await runtime.execute(conn, "missing_tool", {}, "main", "trc_4")
        row = conn.execute(
            "SELECT payload_redacted_json FROM events "
            "WHERE trace_id='trc_4' AND event_type='tool.call.end' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert "unknown_tool" in str(row["payload_redacted_json"])
