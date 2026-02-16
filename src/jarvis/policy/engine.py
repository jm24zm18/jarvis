"""Minimal policy engine for tool access."""

import sqlite3

SAFE_DURING_LOCKDOWN = {"session_list", "session_history"}
SESSION_TOOLS = {"session_list", "session_history", "session_send"}


def is_allowed(conn: sqlite3.Connection, principal_id: str, tool_name: str) -> bool:
    row = conn.execute(
        "SELECT effect FROM tool_permissions WHERE principal_id=? AND tool_name=?",
        (principal_id, tool_name),
    ).fetchone()
    return bool(row and row["effect"] == "allow")


def decision(conn: sqlite3.Connection, principal_id: str, tool_name: str) -> tuple[bool, str]:
    state_row = conn.execute(
        "SELECT lockdown, restarting FROM system_state WHERE id='singleton'"
    ).fetchone()
    lockdown = int(state_row["lockdown"]) if state_row is not None else 0
    restarting = int(state_row["restarting"]) if state_row is not None else 0
    if restarting == 1:
        return False, "R2: restarting"
    if lockdown == 1 and tool_name not in SAFE_DURING_LOCKDOWN:
        return False, "R1: lockdown"
    if tool_name in SESSION_TOOLS and principal_id != "main":
        return False, "R5: main-agent-only session tool"
    if not is_allowed(conn, principal_id, tool_name):
        return False, "R4: permission denied"
    return True, "allow"


def is_admin(admin_ids: set[str], actor_id: str) -> bool:
    return actor_id in admin_ids
