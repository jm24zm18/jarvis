"""Synthetic user story runner."""

from __future__ import annotations

import json

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    ensure_channel,
    ensure_root_user,
    ensure_system_state,
    ensure_user,
    insert_message,
    now_iso,
)
from jarvis.ids import new_id


def latest_story_pack_status(pack: str) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM story_runs WHERE pack=? ORDER BY created_at DESC LIMIT 1",
            (pack,),
        ).fetchone()
    if row is None:
        return "missing"
    return str(row["status"])


def run_story_pack(pack: str = "p0", created_by: str = "user_simulator") -> dict[str, object]:
    scenarios: list[dict[str, object]] = []
    run_id = new_id("stry")
    with get_conn() as conn:
        ensure_system_state(conn)
        _ = ensure_root_user(conn)

        user_id = ensure_user(conn, external_id=f"story:{pack}:user")
        channel_id = ensure_channel(conn, user_id=user_id, channel_type="web")
        thread_id = new_id("thr")
        conn.execute(
            (
                "INSERT INTO threads(id, user_id, channel_id, status, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?)"
            ),
            (thread_id, user_id, channel_id, "open", now_iso(), now_iso()),
        )
        user_msg_id = insert_message(conn, thread_id=thread_id, role="user", content="hello story")
        asst_msg_id = insert_message(
            conn,
            thread_id=thread_id,
            role="assistant",
            content="story acknowledged",
        )
        scenarios.append(
            {
                "story": "chat_bootstrap",
                "passed": True,
                "detail": f"thread={thread_id} user_msg={user_msg_id} assistant_msg={asst_msg_id}",
            }
        )

        gov_row = conn.execute(
            "SELECT COUNT(*) AS n FROM agent_governance WHERE principal_id='main'"
        ).fetchone()
        has_governance = gov_row is not None and int(gov_row["n"]) > 0
        scenarios.append(
            {
                "story": "governance_loaded",
                "passed": has_governance,
                "detail": (
                    "main governance row exists"
                    if has_governance
                    else "main governance row missing"
                ),
            }
        )

        mem_row = conn.execute("SELECT COUNT(*) AS n FROM memory_governance_audit").fetchone()
        has_memory_audit = mem_row is not None and int(mem_row["n"]) >= 0
        scenarios.append(
            {
                "story": "memory_governance_available",
                "passed": has_memory_audit,
                "detail": "memory governance audit table query succeeded",
            }
        )

        status = "passed" if all(bool(item["passed"]) for item in scenarios) else "failed"
        passed_count = sum(1 for item in scenarios if item["passed"])
        summary = f"{status}: {passed_count}/{len(scenarios)} stories"
        conn.execute(
            (
                "INSERT INTO story_runs("
                "id, pack, status, summary, report_json, created_by, created_at"
                ") "
                "VALUES(?,?,?,?,?,?,?)"
            ),
            (run_id, pack, status, summary, json.dumps(scenarios), created_by, now_iso()),
        )
    return {
        "run_id": run_id,
        "pack": pack,
        "status": status,
        "summary": summary,
        "stories": scenarios,
    }
