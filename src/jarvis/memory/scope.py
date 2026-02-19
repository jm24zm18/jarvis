"""Thread-scoped memory access checks for agent actors."""

from __future__ import annotations

import json
import sqlite3

from jarvis.agents.loader import get_all_agent_ids


def normalize_agent_id(agent_id: str | None, *, default: str = "main") -> str:
    clean = (agent_id or "").strip()
    return clean or default


def is_known_agent(agent_id: str) -> bool:
    return agent_id in get_all_agent_ids()


def thread_active_agent_ids(conn: sqlite3.Connection, thread_id: str) -> set[str]:
    known = set(get_all_agent_ids())
    row = conn.execute(
        "SELECT active_agent_ids_json FROM thread_settings WHERE thread_id=? LIMIT 1",
        (thread_id,),
    ).fetchone()
    if row is None:
        return known or {"main"}
    raw = row["active_agent_ids_json"]
    if not isinstance(raw, str) or not raw.strip():
        return known or {"main"}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return known or {"main"}
    if not isinstance(decoded, list):
        return known or {"main"}
    scoped = {
        str(item).strip()
        for item in decoded
        if isinstance(item, str) and str(item).strip()
    }
    filtered = {item for item in scoped if item in known}
    return filtered or {"main"}


def can_agent_access_thread_memory(
    conn: sqlite3.Connection, *, thread_id: str, agent_id: str
) -> tuple[bool, str]:
    clean = normalize_agent_id(agent_id)
    if not is_known_agent(clean):
        return False, "unknown_agent_scope"
    active = thread_active_agent_ids(conn, thread_id)
    if clean not in active:
        return False, "agent_scope_denied"
    return True, "allow"
