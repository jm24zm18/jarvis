"""Minimal policy engine for tool access."""

import json
import sqlite3
from pathlib import Path
from typing import Any

SAFE_DURING_LOCKDOWN = {"session_list", "session_history"}
SESSION_TOOLS = {"session_list", "session_history", "session_send"}
HIGH_RISK_TOOLS = {"exec_host", "session_send"}
PATH_HINT_KEYS = {
    "path",
    "paths",
    "cwd",
    "file",
    "files",
    "dir",
    "directory",
    "target",
    "repo_path",
}


def _risk_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(value.strip().lower(), 0)


def _normalize_path(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve())
    except OSError:
        return value


def _path_allowed(candidate: str, allowed_prefixes: list[str]) -> bool:
    for prefix in allowed_prefixes:
        if candidate == prefix or candidate.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def _extract_paths(arguments: dict[str, Any]) -> list[str]:
    paths: list[str] = []

    def visit(value: Any, hint: str | None = None) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, key)
            return
        if isinstance(value, list):
            for child in value:
                visit(child, hint)
            return
        if isinstance(value, str) and hint and hint in PATH_HINT_KEYS:
            clean = value.strip()
            if clean:
                paths.append(_normalize_path(clean))

    visit(arguments)
    unique: list[str] = []
    seen: set[str] = set()
    for item in paths:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _governance_decision(
    conn: sqlite3.Connection,
    principal_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    trace_id: str | None = None,
) -> tuple[bool, str]:
    row = conn.execute(
        (
            "SELECT risk_tier, max_actions_per_step, allowed_paths_json, "
            "can_request_privileged_change "
            "FROM agent_governance WHERE principal_id=? LIMIT 1"
        ),
        (principal_id,),
    ).fetchone()
    if row is None:
        return True, "allow"

    risk_tier = str(row["risk_tier"]).strip().lower()
    can_request = int(row["can_request_privileged_change"]) == 1

    if (
        tool_name in HIGH_RISK_TOOLS
        and _risk_rank(risk_tier) < _risk_rank("high")
        and not can_request
    ):
        return False, "R6: governance.risk_tier"

    # R8: enforce max_actions_per_step
    max_actions_raw = row["max_actions_per_step"]
    if max_actions_raw is not None and trace_id:
        max_actions = int(max_actions_raw)
        if max_actions > 0:
            action_count_row = conn.execute(
                "SELECT COUNT(*) AS n FROM events "
                "WHERE trace_id=? AND event_type='tool.call.start'",
                (trace_id,),
            ).fetchone()
            action_count = int(action_count_row["n"]) if action_count_row is not None else 0
            if action_count > max_actions:
                return False, "R8: step_limit_exceeded"

    raw_paths = row["allowed_paths_json"]
    try:
        decoded = json.loads(str(raw_paths)) if raw_paths is not None else []
    except json.JSONDecodeError:
        decoded = []
    allowed_prefixes = [
        _normalize_path(item.strip())
        for item in decoded
        if isinstance(item, str) and item.strip()
    ]
    if not allowed_prefixes:
        return True, "allow"
    for candidate in _extract_paths(arguments):
        if not _path_allowed(candidate, allowed_prefixes):
            return False, "R7: governance.allowed_paths"
    return True, "allow"


def is_allowed(conn: sqlite3.Connection, principal_id: str, tool_name: str) -> bool:
    # Check exact tool_name match first, then wildcard '*'.
    row = conn.execute(
        "SELECT effect FROM tool_permissions WHERE principal_id=? AND tool_name IN (?, '*') "
        "ORDER BY CASE tool_name WHEN ? THEN 0 ELSE 1 END LIMIT 1",
        (principal_id, tool_name, tool_name),
    ).fetchone()
    return bool(row and row["effect"] == "allow")


def decision(
    conn: sqlite3.Connection,
    principal_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> tuple[bool, str]:
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
    gov_allowed, gov_reason = _governance_decision(
        conn, principal_id, tool_name, arguments or {}, trace_id=trace_id
    )
    if not gov_allowed:
        return False, gov_reason
    return True, "allow"


def is_admin(admin_ids: set[str], actor_id: str) -> bool:
    return actor_id in admin_ids
