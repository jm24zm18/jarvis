import pytest

from jarvis.db.connection import get_conn
from jarvis.errors import PolicyError
from jarvis.policy.engine import decision
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.runtime import ToolRuntime


@pytest.mark.asyncio
async def test_runtime_denies_by_governance_allowed_paths() -> None:
    registry = ToolRegistry()

    async def handler(args):
        return {"ok": True, "args": args}

    registry.register("echo", "Echo", handler)
    runtime = ToolRuntime(registry)
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT OR REPLACE INTO principals("
                "id, principal_type, created_at"
                ") VALUES(?,?,datetime('now'))"
            ),
            ("coder", "agent"),
        )
        conn.execute(
            (
                "INSERT OR REPLACE INTO tool_permissions("
                "principal_id, tool_name, effect"
                ") VALUES(?,?,?)"
            ),
            ("coder", "echo", "allow"),
        )
        conn.execute(
            (
                "INSERT OR REPLACE INTO agent_governance("
                "principal_id, risk_tier, max_actions_per_step, allowed_paths_json, "
                "can_request_privileged_change, updated_at"
                ") VALUES(?,?,?,?,?,datetime('now'))"
            ),
            ("coder", "medium", 6, "[\"/tmp/allowed\"]", 0),
        )
        with pytest.raises(PolicyError, match="R7"):
            await runtime.execute(
                conn,
                "echo",
                {"path": "/tmp/blocked/file.txt"},
                "coder",
                "trc_gov_1",
            )


def test_request_human_escalation_is_main_only() -> None:
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT OR REPLACE INTO principals("
                "id, principal_type, created_at"
                ") VALUES(?,?,datetime('now'))"
            ),
            ("researcher", "agent"),
        )
        conn.execute(
            (
                "INSERT OR REPLACE INTO tool_permissions("
                "principal_id, tool_name, effect"
                ") VALUES(?,?,?)"
            ),
            ("researcher", "request_human_escalation", "allow"),
        )
        allowed, reason = decision(
            conn,
            "researcher",
            "request_human_escalation",
            arguments={"reason": "x", "message": "y"},
            trace_id="trc_main_only",
        )
    assert allowed is False
    assert reason == "R5: main-agent-only escalation tool"


def test_request_human_escalation_allowed_for_main() -> None:
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT OR REPLACE INTO principals("
                "id, principal_type, created_at"
                ") VALUES(?,?,datetime('now'))"
            ),
            ("main", "agent"),
        )
        conn.execute(
            (
                "INSERT OR REPLACE INTO tool_permissions("
                "principal_id, tool_name, effect"
                ") VALUES(?,?,?)"
            ),
            ("main", "request_human_escalation", "allow"),
        )
        allowed, reason = decision(
            conn,
            "main",
            "request_human_escalation",
            arguments={"reason": "x", "message": "y"},
            trace_id="trc_main_allowed",
        )
    assert allowed is True
    assert reason == "allow"
