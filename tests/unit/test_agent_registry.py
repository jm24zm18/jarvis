from jarvis.agents.registry import sync_tool_permissions
from jarvis.agents.types import AgentBundle
from jarvis.db.connection import get_conn


def _bundle(agent_id: str, allowed_tools: list[str]) -> AgentBundle:
    return AgentBundle(
        agent_id=agent_id,
        identity_markdown="---\n---\n",
        soul_markdown="# soul\n",
        heartbeat_markdown="# heartbeat\n",
        allowed_tools=allowed_tools,
        risk_tier="medium",
        max_actions_per_step=8,
        allowed_paths=("/tmp",),
        can_request_privileged_change=False,
    )


def test_sync_tool_permissions_reconciles_escalation_ownership() -> None:
    bundles = {
        "main": _bundle("main", ["echo", "request_human_escalation"]),
        "feature_builder": _bundle("feature_builder", ["echo", "exec_host"]),
    }
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
                "INSERT OR REPLACE INTO principals("
                "id, principal_type, created_at"
                ") VALUES(?,?,datetime('now'))"
            ),
            ("feature_builder", "agent"),
        )
        conn.execute(
            (
                "INSERT OR REPLACE INTO tool_permissions("
                "principal_id, tool_name, effect"
                ") VALUES(?,?,?)"
            ),
            ("feature_builder", "request_human_escalation", "allow"),
        )
        sync_tool_permissions(conn, bundles)
        main_tools = {
            str(row["tool_name"])
            for row in conn.execute(
                "SELECT tool_name FROM tool_permissions "
                "WHERE principal_id='main' AND effect='allow'"
            ).fetchall()
        }
        fb_tools = {
            str(row["tool_name"])
            for row in conn.execute(
                "SELECT tool_name FROM tool_permissions "
                "WHERE principal_id='feature_builder' AND effect='allow'"
            ).fetchall()
        }
    assert "request_human_escalation" in main_tools
    assert "request_human_escalation" not in fb_tools
