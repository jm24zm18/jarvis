"""Release candidate evidence builder."""

from __future__ import annotations

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import insert_governance_agent_run, latest_system_fitness_snapshot
from jarvis.tasks.story_runner import latest_story_pack_status


def build_release_candidate() -> dict[str, object]:
    settings = get_settings()
    if int(settings.release_candidate_agent_enabled) != 1:
        result = {"status": "disabled"}
        with get_conn() as conn:
            insert_governance_agent_run(
                conn,
                run_type="release_candidate",
                status="disabled",
                summary="release candidate agent disabled",
                payload=result,
            )
        return result
    required_pack = settings.user_simulator_required_pack.strip() or "p0"
    story_status = latest_story_pack_status(required_pack)
    blockers: list[str] = []
    checks: dict[str, str] = {
        "lint": "required",
        "typecheck": "required",
        "test_gates": "required",
        "security": "required",
        "migrations": "required",
    }
    if story_status != "passed":
        blockers.append(f"story_pack:{required_pack}:{story_status}")

    with get_conn() as conn:
        migration_ok_row = conn.execute("PRAGMA integrity_check").fetchone()
        migration_ok = (
            migration_ok_row is not None and str(migration_ok_row[0]).strip().lower() == "ok"
        )
        checks["migrations"] = "passed" if migration_ok else "failed"
        if not migration_ok:
            blockers.append("db_integrity_check_failed")

        readyz_url = settings.selfupdate_readyz_url.strip()
        checks["readyz_probe"] = "required" if readyz_url else "not_configured"

        latest_events = conn.execute(
            "SELECT event_type, created_at FROM events "
            "WHERE event_type IN ("
            "'self_update.validate','self_update.test','self_update.apply',"
            "'self_update.verified'"
            ") "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        latest_event_types = [str(row["event_type"]) for row in latest_events]
        checks["selfupdate_recent_verify"] = (
            "passed" if "self_update.verified" in latest_event_types else "missing"
        )
        if checks["selfupdate_recent_verify"] != "passed":
            blockers.append("no_recent_self_update_verified_event")

        fitness = latest_system_fitness_snapshot(conn)
    if not fitness:
        blockers.append("missing_system_fitness_snapshot")

    status = "ready" if not blockers else "blocked"
    result = {
        "status": status,
        "required_story_pack": required_pack,
        "story_status": story_status,
        "checks": checks,
        "blockers": blockers,
        "evidence": {
            "fitness_latest": fitness,
        },
    }
    with get_conn() as conn:
        insert_governance_agent_run(
            conn,
            run_type="release_candidate",
            status=str(status),
            summary=f"status={status} blockers={len(blockers)}",
            payload=result,
        )
    return result
