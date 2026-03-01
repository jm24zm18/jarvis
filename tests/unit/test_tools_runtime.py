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
            await runtime.execute(conn, "echo", {"x": 1}, "unknown_agent", "trc_1")
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
async def test_wildcard_permission_allows_any_tool() -> None:
    """A wildcard '*' permission for a principal allows calling any registered tool."""
    registry = ToolRegistry()

    async def handler(args):
        return {"ok": True}

    registry.register("special_tool_xyz", "A tool not in explicit list", handler)
    runtime = ToolRuntime(registry)

    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO principals(id, principal_type, created_at) "
            "VALUES(?,?,datetime('now'))",
            ("main", "agent"),
        )
        # Insert wildcard permission — migration 057 adds ('main', '*', 'allow').
        conn.execute(
            "INSERT OR REPLACE INTO tool_permissions(principal_id, tool_name, effect) "
            "VALUES(?,?,?)",
            ("main", "*", "allow"),
        )
        result = await runtime.execute(conn, "special_tool_xyz", {}, "main", "trc_wildcard")

    assert result["ok"] is True


@pytest.mark.asyncio
async def test_max_actions_per_step_enforced() -> None:
    """When max_actions_per_step is set, exceeding it triggers R8 policy denial."""
    registry = ToolRegistry()
    call_count = 0

    async def handler(args):
        nonlocal call_count
        call_count += 1
        return {"ok": True, "call": call_count}

    registry.register("counter_tool", "Counter", handler)
    runtime = ToolRuntime(registry)

    principal = "agent_limited"
    trace_id = "trc_r8_test"

    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO principals(id, principal_type, created_at) "
            "VALUES(?,?,datetime('now'))",
            (principal, "agent"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO tool_permissions(principal_id, tool_name, effect) "
            "VALUES(?,?,?)",
            (principal, "counter_tool", "allow"),
        )
        # Set max_actions_per_step = 2.
        conn.execute(
            "INSERT OR REPLACE INTO agent_governance("
            "principal_id, risk_tier, max_actions_per_step, allowed_paths_json, "
            "can_request_privileged_change, updated_at"
            ") VALUES(?,?,?,?,?,datetime('now'))",
            (principal, "low", 2, "[]", 0),
        )

        # First two calls succeed.
        await runtime.execute(conn, "counter_tool", {}, principal, trace_id)
        await runtime.execute(conn, "counter_tool", {}, principal, trace_id)

        # Third call should be denied by R8.
        with pytest.raises(PolicyError, match="R8"):
            await runtime.execute(conn, "counter_tool", {}, principal, trace_id)

    assert call_count == 2


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
