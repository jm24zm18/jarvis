"""Agent registry service."""

import sqlite3
from datetime import UTC, datetime

from jarvis.agents.types import AgentBundle


def sync_tool_permissions(conn: sqlite3.Connection, bundles: dict[str, AgentBundle]) -> None:
    now = datetime.now(UTC).isoformat()
    for bundle in bundles.values():
        conn.execute(
            "INSERT OR REPLACE INTO principals(id, principal_type, created_at) VALUES(?,?,?)",
            (bundle.agent_id, "agent", now),
        )
        conn.execute("DELETE FROM tool_permissions WHERE principal_id=?", (bundle.agent_id,))
        for tool in bundle.allowed_tools:
            conn.execute(
                "INSERT INTO tool_permissions(principal_id, tool_name, effect) VALUES(?,?,?)",
                (bundle.agent_id, tool, "allow"),
            )
