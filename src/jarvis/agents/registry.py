"""Agent registry service."""

import json
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
        conn.execute(
            (
                "INSERT OR REPLACE INTO agent_governance("
                "principal_id, risk_tier, max_actions_per_step, allowed_paths_json, "
                "can_request_privileged_change, updated_at"
                ") VALUES(?,?,?,?,?,?)"
            ),
            (
                bundle.agent_id,
                bundle.risk_tier,
                int(bundle.max_actions_per_step),
                json.dumps(list(bundle.allowed_paths)),
                1 if bundle.can_request_privileged_change else 0,
                now,
            ),
        )
        conn.execute("DELETE FROM tool_permissions WHERE principal_id=?", (bundle.agent_id,))
        for tool in bundle.allowed_tools:
            conn.execute(
                "INSERT INTO tool_permissions(principal_id, tool_name, effect) VALUES(?,?,?)",
                (bundle.agent_id, tool, "allow"),
            )
