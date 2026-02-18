"""Local maintenance tasks (lint/typecheck/test checks)."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import insert_system_fitness_snapshot, now_iso
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id

_MAX_CAPTURE_CHARS = 4000


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _truncate(text: str, max_chars: int = _MAX_CAPTURE_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...[truncated]"


def _commands_from_settings(raw: str) -> list[str]:
    normalized = raw.replace("\\n", "\n")
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def _run_command(command: str, *, cwd: Path, timeout_s: int) -> dict[str, object]:
    try:
        proc = subprocess.run(
            ["/bin/bash", "-lc", command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=max(1, timeout_s),
            check=False,
        )
        return {
            "command": command,
            "ok": proc.returncode == 0,
            "exit_code": int(proc.returncode),
            "stdout": _truncate(proc.stdout or ""),
            "stderr": _truncate(proc.stderr or ""),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        err = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "command": command,
            "ok": False,
            "exit_code": 124,
            "stdout": _truncate(out),
            "stderr": _truncate(err),
            "timed_out": True,
        }


def _recent_open_bug_exists(conn, title: str, *, within_hours: int = 24) -> bool:
    row = conn.execute(
        "SELECT created_at FROM bug_reports WHERE title=? AND status IN ('open', 'in_progress') "
        "ORDER BY created_at DESC LIMIT 1",
        (title,),
    ).fetchone()
    if row is None:
        return False
    raw_created = str(row["created_at"])
    try:
        created = datetime.fromisoformat(raw_created)
    except ValueError:
        return False
    return created >= datetime.now(UTC) - timedelta(hours=within_hours)


def _record_maintenance_bug(command_result: dict[str, object], workdir: Path) -> str | None:
    title = f"Local maintenance check failed: {command_result.get('command', '')}"
    with get_conn() as conn:
        if _recent_open_bug_exists(conn, title):
            return None
        bug_id = new_id("bug")
        now = now_iso()
        conn.execute(
            (
                "INSERT INTO bug_reports(id, title, description, status, priority, "
                "reporter_id, assignee_agent, thread_id, trace_id, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                bug_id,
                title,
                json.dumps(
                    {
                        "source": "local_maintenance",
                        "workdir": str(workdir),
                        "result": command_result,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                "open",
                "medium",
                None,
                "release_ops",
                None,
                None,
                now,
                now,
            ),
        )
    return bug_id


def run_local_maintenance() -> dict[str, object]:
    settings = get_settings()
    if int(settings.maintenance_enabled) != 1:
        return {"ok": True, "skipped": "maintenance_disabled"}

    commands = _commands_from_settings(settings.maintenance_commands)
    if not commands:
        return {"ok": True, "skipped": "no_commands"}

    cwd = (
        Path(settings.maintenance_workdir).expanduser().resolve()
        if settings.maintenance_workdir.strip()
        else _repo_root()
    )
    timeout_s = int(settings.maintenance_timeout_seconds)

    results: list[dict[str, object]] = []
    bug_ids: list[str] = []
    for command in commands:
        result = _run_command(command, cwd=cwd, timeout_s=timeout_s)
        results.append(result)
        if not bool(result.get("ok")) and int(settings.maintenance_create_bugs) == 1:
            bug_id = _record_maintenance_bug(result, cwd)
            if bug_id:
                bug_ids.append(bug_id)

    ok = all(bool(item.get("ok")) for item in results)
    return {
        "ok": ok,
        "workdir": str(cwd),
        "command_count": len(results),
        "results": results,
        "bug_ids": bug_ids,
    }


def maintenance_heartbeat() -> dict[str, object]:
    settings = get_settings()
    payload = {
        "source": "maintenance.heartbeat",
        "maintenance_enabled": int(settings.maintenance_enabled) == 1,
        "maintenance_interval_seconds": int(settings.maintenance_interval_seconds),
    }
    trace_id = new_id("trc")
    with get_conn() as conn:
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=None,
                event_type="maintenance.heartbeat",
                component="maintenance",
                actor_type="system",
                actor_id="maintenance",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )
    return {"ok": True, "trace_id": trace_id, "timestamp": now_iso()}


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def compute_system_fitness(days: int = 7) -> dict[str, object]:
    window_days = max(1, int(days))
    now = datetime.now(UTC)
    period_start = (now - timedelta(days=window_days)).isoformat()
    period_end = now.isoformat()
    with get_conn() as conn:
        story_total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM story_runs WHERE created_at>=?",
            (period_start,),
        ).fetchone()
        story_passed_row = conn.execute(
            "SELECT COUNT(*) AS n FROM story_runs WHERE created_at>=? AND status='passed'",
            (period_start,),
        ).fetchone()
        rollback_count_row = conn.execute(
            "SELECT COUNT(*) AS n FROM selfupdate_transitions "
            "WHERE created_at>=? AND to_state='rolled_back'",
            (period_start,),
        ).fetchone()
        apply_total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM selfupdate_transitions "
            "WHERE created_at>=? AND to_state='applied'",
            (period_start,),
        ).fetchone()
        verified_total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM selfupdate_transitions "
            "WHERE created_at>=? AND to_state='verified'",
            (period_start,),
        ).fetchone()
        policy_denials_row = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE created_at>=? AND event_type='policy.decision' "
            "AND payload_redacted_json LIKE '%\"allowed\": false%'",
            (period_start,),
        ).fetchone()
        failure_total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM failure_capsules WHERE created_at>=?",
            (period_start,),
        ).fetchone()
        repeated_failure_row = conn.execute(
            "SELECT COUNT(*) AS n FROM ("
            "SELECT error_summary FROM failure_capsules WHERE created_at>=? "
            "GROUP BY error_summary HAVING COUNT(*)>1"
            ")",
            (period_start,),
        ).fetchone()

        story_total = int(story_total_row["n"]) if story_total_row is not None else 0
        story_passed = int(story_passed_row["n"]) if story_passed_row is not None else 0
        rollback_count = int(rollback_count_row["n"]) if rollback_count_row is not None else 0
        apply_total = int(apply_total_row["n"]) if apply_total_row is not None else 0
        verified_total = int(verified_total_row["n"]) if verified_total_row is not None else 0
        policy_denials = int(policy_denials_row["n"]) if policy_denials_row is not None else 0
        failure_total = int(failure_total_row["n"]) if failure_total_row is not None else 0
        repeated_failures = (
            int(repeated_failure_row["n"]) if repeated_failure_row is not None else 0
        )

        metrics: dict[str, object] = {
            "window_days": window_days,
            "story_pack_pass_rate": _safe_ratio(story_passed, story_total),
            "selfupdate_success_rate": _safe_ratio(verified_total, apply_total),
            "rollback_frequency": rollback_count,
            "policy_denials": policy_denials,
            "failure_capsule_recurrence_rate": _safe_ratio(repeated_failures, failure_total),
            "counts": {
                "story_total": story_total,
                "story_passed": story_passed,
                "selfupdate_applied": apply_total,
                "selfupdate_verified": verified_total,
                "rollbacks": rollback_count,
                "failure_capsules": failure_total,
                "repeated_failure_groups": repeated_failures,
            },
        }
        snapshot_id = insert_system_fitness_snapshot(
            conn,
            period_start=period_start,
            period_end=period_end,
            metrics=metrics,
        )

    trace_id = new_id("trc")
    payload = {
        "snapshot_id": snapshot_id,
        "period_start": period_start,
        "period_end": period_end,
        "metrics": metrics,
    }
    with get_conn() as conn:
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=None,
                event_type="governance.fitness.computed",
                component="maintenance",
                actor_type="system",
                actor_id="maintenance",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )
    return {"ok": True, "snapshot_id": snapshot_id, "metrics": metrics}


def refresh_learning_loop(days: int = 14) -> dict[str, object]:
    window_days = max(1, int(days))
    since = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
    inserted = 0
    updated = 0
    remediations_seeded = 0

    def _default_remediation_for_phase(phase: str, reason: str) -> tuple[str, str]:
        phase_key = phase.strip().lower()
        if phase_key == "validate":
            return (
                (
                    "Re-run validation from clean baseline and inspect patch "
                    f"integrity. ({reason[:120]})"
                ),
                "git apply --check proposal.diff",
            )
        if phase_key == "test":
            return (
                (
                    "Run targeted failing tests first, then run the declared "
                    f"test plan. ({reason[:120]})"
                ),
                "pytest -q",
            )
        if phase_key == "apply":
            return (
                (
                    "Reconcile repo to baseline and retry apply with fresh "
                    f"replay check. ({reason[:120]})"
                ),
                "git status --porcelain",
            )
        return (
            f"Reproduce the failure deterministically and add a regression check. ({reason[:120]})",
            "make test-gates",
        )

    with get_conn() as conn:
        rows = conn.execute(
            (
                "SELECT phase, error_summary, MAX(created_at) AS last_seen_at, "
                "MIN(created_at) AS first_seen_at, COUNT(*) AS n, "
                "MAX(trace_id) AS latest_trace_id "
                "FROM failure_capsules WHERE created_at>=? "
                "GROUP BY phase, error_summary ORDER BY n DESC, last_seen_at DESC LIMIT 200"
            ),
            (since,),
        ).fetchall()
        for row in rows:
            phase = str(row["phase"])
            reason = str(row["error_summary"])
            signature = f"{phase}:{reason[:160].lower()}"
            existing = conn.execute(
                "SELECT id FROM failure_patterns WHERE signature=? AND phase=? LIMIT 1",
                (signature, phase),
            ).fetchone()
            pattern_id = str(existing["id"]) if existing is not None else new_id("flp")
            if existing is None:
                conn.execute(
                    (
                        "INSERT INTO failure_patterns("
                        "id, signature, phase, count, latest_reason, latest_trace_id, "
                        "first_seen_at, last_seen_at"
                        ") VALUES(?,?,?,?,?,?,?,?)"
                    ),
                    (
                        pattern_id,
                        signature,
                        phase,
                        int(row["n"]),
                        reason,
                        str(row["latest_trace_id"]) if row["latest_trace_id"] is not None else "",
                        str(row["first_seen_at"]),
                        str(row["last_seen_at"]),
                    ),
                )
                inserted += 1
            else:
                conn.execute(
                    (
                        "UPDATE failure_patterns SET count=?, latest_reason=?, latest_trace_id=?, "
                        "first_seen_at=?, last_seen_at=? WHERE id=?"
                    ),
                    (
                        int(row["n"]),
                        reason,
                        str(row["latest_trace_id"]) if row["latest_trace_id"] is not None else "",
                        str(row["first_seen_at"]),
                        str(row["last_seen_at"]),
                        pattern_id,
                    ),
                )
                updated += 1

            rem_count_row = conn.execute(
                "SELECT COUNT(*) AS n FROM failure_pattern_remediations WHERE pattern_id=?",
                (pattern_id,),
            ).fetchone()
            rem_count = int(rem_count_row["n"]) if rem_count_row is not None else 0
            if rem_count == 0:
                remediation, verification = _default_remediation_for_phase(phase, reason)
                conn.execute(
                    (
                        "INSERT INTO failure_pattern_remediations("
                        "id, pattern_id, remediation, verification_test, confidence, created_at"
                        ") VALUES(?,?,?,?,?,?)"
                    ),
                    (new_id("frm"), pattern_id, remediation, verification, "medium", now_iso()),
                )
                remediations_seeded += 1
    return {
        "ok": True,
        "window_days": window_days,
        "inserted": inserted,
        "updated": updated,
        "remediations_seeded": remediations_seeded,
    }
