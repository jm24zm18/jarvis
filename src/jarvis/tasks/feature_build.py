"""Feature request build-run task."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_thread,
    ensure_channel,
    get_feature_build_run,
    list_due_feature_build_retries,
    now_iso,
    update_feature_build_run,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Attempt capsule helpers
# ---------------------------------------------------------------------------

def _capsule_stable_hash(capsule: dict) -> str:
    """Return a SHA-256 hex digest of the stable fields of an attempt capsule.

    Unstable fields (run_id, trace_id, attempt, schema_version) are excluded
    so that two consecutive attempts with identical outcomes produce the same
    hash and trigger the repeat fail-fast.
    """
    stable = {
        "reason": str(capsule.get("reason", "")),
        "changed_files": sorted(capsule.get("changed_files") or []),
        "tools_used": sorted(capsule.get("tools_used") or []),
        "top_errors": sorted(capsule.get("top_errors") or []),
        "next_action": str(capsule.get("next_action", "")),
        "blockers_summary": str(capsule.get("blockers_summary", "")),
    }
    blob = json.dumps(stable, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _build_attempt_capsule(
    *,
    run_id: str,
    trace_id: str,
    attempt: int,
    reason: str,
    changed_files: list[str],
    tools_used: list[str],
    top_errors: list[str],
    blockers_summary: str,
    next_action: str,
) -> dict:
    """Build a structured attempt capsule dict."""
    return {
        "schema_version": 1,
        "run_id": run_id,
        "trace_id": trace_id,
        "attempt": attempt,
        "reason": reason,
        "changed_files": sorted(changed_files),
        "tools_used": sorted(tools_used),
        "top_errors": top_errors[:5],
        "blockers_summary": blockers_summary[:500],
        "next_action": next_action[:200],
    }


def get_previous_capsule(conn, run_id: str) -> dict | None:
    """Read the last_capsule_json from the feature_request_build_runs row."""
    row = conn.execute(
        "SELECT last_capsule_json, last_capsule_hash "
        "FROM feature_request_build_runs WHERE id=? LIMIT 1",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    raw = str(row["last_capsule_json"] or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def save_capsule(conn, run_id: str, capsule: dict, capsule_hash: str) -> None:
    """Persist the capsule and its hash on the run record."""
    conn.execute(
        "UPDATE feature_request_build_runs SET last_capsule_json=?, last_capsule_hash=? WHERE id=?",
        (json.dumps(capsule), capsule_hash, run_id),
    )


def _format_capsule_summary(capsule: dict) -> str:
    """Format a concise capsule summary for injection as a system message."""
    attempt = capsule.get("attempt", "?")
    reason = capsule.get("reason", "unknown")
    files = capsule.get("changed_files") or []
    blockers = str(capsule.get("blockers_summary") or "").strip()
    parts = [f"[Attempt {attempt} context] Previous attempt failed: {reason}."]
    if files:
        files_str = ", ".join(files[:5])
        if len(files) > 5:
            files_str += f" (+{len(files) - 5} more)"
        parts.append(f"Changed: {files_str}.")
    if blockers:
        parts.append(f"Blockers: {blockers[:150]}.")
    return " ".join(parts)


def _collect_tools_used_from_trace(conn, trace_id: str) -> list[str]:
    """Return distinct tool names used in span events for this trace."""
    rows = conn.execute(
        (
            "SELECT DISTINCT json_extract(payload_json, '$.tool') AS tool "
            "FROM events WHERE trace_id=? AND event_type='tool.call.start' "
            "AND json_extract(payload_json, '$.tool') IS NOT NULL"
        ),
        (trace_id,),
    ).fetchall()
    return sorted(str(r["tool"]) for r in rows if r["tool"])


def _collect_top_errors_from_trace(conn, trace_id: str) -> list[str]:
    """Return up to 5 distinct error strings from tool events in this trace."""
    rows = conn.execute(
        (
            "SELECT json_extract(payload_json, '$.error') AS err "
            "FROM events WHERE trace_id=? AND event_type='tool.call.end' "
            "AND json_extract(payload_json, '$.error') IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 20"
        ),
        (trace_id,),
    ).fetchall()
    seen: list[str] = []
    for r in rows:
        err = str(r["err"] or "").strip()[:200]
        if err and err not in seen:
            seen.append(err)
        if len(seen) >= 5:
            break
    return seen


def _emit_build_event(
    *,
    conn,
    trace_id: str,
    thread_id: str | None,
    event_type: str,
    payload: dict[str, object],
) -> None:
    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id,
            event_type=event_type,
            component="feature_build",
            actor_type="system",
            actor_id="feature_build",
            payload_json=json.dumps(payload),
            payload_redacted_json=json.dumps(redact_payload(payload)),
        ),
    )


def _resolve_retry_delay_seconds(attempt_number: int) -> int:
    settings = get_settings()
    raw = str(settings.feature_build_retry_backoff_seconds).strip()
    values: list[int] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            values.append(max(1, int(item)))
        except ValueError:
            continue
    if not values:
        values = [30, 120, 300, 600]
    idx = max(0, min(len(values) - 1, attempt_number - 2))
    return values[idx]


def run_feature_build(
    run_id: str,
    feature_id: str,
    trace_id: str,
    title: str,
    actor_id: str,
) -> dict[str, object]:
    """Execute a feature build run via the main agent.

    Creates a web_admin thread if needed, inserts a build instruction message,
    then enqueues jarvis.tasks.agent.agent_step to process it.  The run status
    is reconciled from the agent step result.
    """
    from jarvis.tasks import get_task_runner

    try:
        settings = get_settings()
        with get_conn() as conn:
            run_row = get_feature_build_run(conn, run_id)
            if run_row is None:
                raise RuntimeError(f"feature build run not found: {run_id}")
            attempt_count = max(1, int(run_row.get("attempt_count", 1)))
            max_attempts = max(attempt_count, int(run_row.get("max_attempts", attempt_count)))
            update_feature_build_run(
                conn,
                run_id,
                status="running",
                trace_id=trace_id,
                retry_state="none",
                next_retry_at="",
                active_attempt=attempt_count,
                last_progress_at=now_iso(),
                last_event_type="feature.build.attempt.start",
                last_trace_id=trace_id,
                summary=f"Build attempt {attempt_count}/{max_attempts} in progress.",
            )

            # Find or create a web channel thread for build runs.
            row = None
            existing_thread_id = str(run_row.get("thread_id") or "").strip()
            if existing_thread_id:
                row = conn.execute(
                    "SELECT id FROM threads WHERE id=? AND status='open' LIMIT 1",
                    (existing_thread_id,),
                ).fetchone()
            if row is not None:
                thread_id = str(row["id"])
            else:
                row = conn.execute(
                    (
                        "SELECT t.id FROM threads t "
                        "JOIN channels c ON c.id=t.channel_id "
                        "WHERE t.user_id=? AND c.channel_type='web' AND t.status='open' "
                        "ORDER BY t.updated_at DESC LIMIT 1"
                    ),
                    (actor_id,),
                ).fetchone()
                if row is not None:
                    thread_id = str(row["id"])
                else:
                    channel_id = ensure_channel(conn, actor_id, "web")
                    thread_id = create_thread(conn, actor_id, channel_id)

            # Update run with thread_id.
            update_feature_build_run(conn, run_id, thread_id=thread_id)

            # On retry attempts, inject previous capsule context as a system message.
            if attempt_count > 1 and int(settings.feature_build_attempt_capsules_enabled) == 1:
                prev_capsule = get_previous_capsule(conn, run_id)
                if prev_capsule is not None:
                    capsule_summary = _format_capsule_summary(prev_capsule)
                    ctx_msg_id = new_id("msg")
                    ctx_now = now_iso()
                    conn.execute(
                        (
                            "INSERT INTO messages(id, thread_id, role, content, created_at) "
                            "VALUES(?,?,?,?,?)"
                        ),
                        (ctx_msg_id, thread_id, "system", capsule_summary, ctx_now),
                    )

            # Insert build instruction message.
            msg_id = new_id("msg")
            now = now_iso()
            build_instruction = (
                f"Build feature request {feature_id!r}: {title!r}\n\n"
                "Review the feature description, implement the required changes following "
                "established patterns, run tests and linting, and open a pull request to dev. "
                "Record evidence for each step.\n\n"
                "Final response requirements:\n"
                "1) summarize completed code changes with file references,\n"
                "2) report test/lint/typecheck commands and outcomes,\n"
                "3) include PR details if opened,\n"
                "4) if blocked and human help is needed, explicitly call request_human_escalation."
            )
            conn.execute(
                (
                    "INSERT INTO messages(id, thread_id, role, content, created_at) "
                    "VALUES(?,?,?,?,?)"
                ),
                (msg_id, thread_id, "user", build_instruction, now),
            )
            _emit_build_event(
                conn=conn,
                trace_id=trace_id,
                thread_id=thread_id,
                event_type="feature.build.attempt.start",
                payload={
                    "run_id": run_id,
                    "feature_id": feature_id,
                    "attempt_count": attempt_count,
                    "max_attempts": max_attempts,
                },
            )

        runner = get_task_runner()
        queued = runner.send_task(
            "jarvis.tasks.agent.agent_step",
            kwargs={"thread_id": thread_id, "trace_id": trace_id},
            queue="default",
        )

        if not queued:
            with get_conn() as conn:
                update_feature_build_run(
                    conn,
                    run_id,
                    status="failed",
                    last_progress_at=now_iso(),
                    last_event_type="feature.build.attempt.enqueue_failed",
                    last_trace_id=trace_id,
                    summary="agent_step task could not be enqueued",
                )
                _emit_build_event(
                    conn=conn,
                    trace_id=trace_id,
                    thread_id=thread_id,
                    event_type="feature.build.attempt.enqueue_failed",
                    payload={"run_id": run_id, "feature_id": feature_id},
                )
            return {
                "run_id": run_id,
                "feature_id": feature_id,
                "trace_id": trace_id,
                "status": "failed",
            }

        return {
            "run_id": run_id,
            "feature_id": feature_id,
            "trace_id": trace_id,
            "thread_id": thread_id,
            "status": "running",
        }
    except Exception as exc:
        logger.exception("feature build run failed before enqueue: run_id=%s", run_id)
        summary = f"feature build task crashed: {exc.__class__.__name__}: {exc}"
        with get_conn() as conn:
            update_feature_build_run(conn, run_id, status="failed", summary=summary[:500])
            _emit_build_event(
                conn=conn,
                trace_id=trace_id,
                thread_id=None,
                event_type="feature.build.attempt.crashed",
                payload={"run_id": run_id, "feature_id": feature_id, "error": str(exc)[:500]},
            )
        return {
            "run_id": run_id,
            "feature_id": feature_id,
            "trace_id": trace_id,
            "status": "failed",
            "error": summary,
        }


def reconcile_stale_feature_build_runs(
    stale_after_seconds: int = 900,
    limit: int = 200,
) -> dict[str, object]:
    """Periodic sweeper for stale running feature-build runs."""
    from jarvis.db.queries import reconcile_stale_feature_build_runs as reconcile_query

    with get_conn() as conn:
        return reconcile_query(
            conn,
            stale_after_seconds=stale_after_seconds,
            limit=limit,
        )


def dispatch_due_feature_build_retries(limit: int = 50) -> dict[str, object]:
    """Dispatch scheduled feature-build retries that are due."""
    from jarvis.tasks import get_task_runner

    attempted = 0
    dispatched = 0
    rescheduled = 0
    failed = 0
    now_dt = datetime.now(UTC)
    with get_conn() as conn:
        due_rows = list_due_feature_build_retries(conn, now=now_dt, limit=limit)
        runner = get_task_runner()
        for row in due_rows:
            attempted += 1
            run_id = str(row["id"])
            feature_id = str(row["feature_id"])
            actor_id = str(row["created_by"])
            thread_id = str(row["thread_id"] or "")
            attempt_count = max(1, int(row["attempt_count"]))
            max_attempts = max(attempt_count, int(row["max_attempts"]))
            if attempt_count > max_attempts:
                update_feature_build_run(
                    conn,
                    run_id,
                    status="failed",
                    retry_state="exhausted",
                    next_retry_at="",
                    last_progress_at=now_iso(),
                    last_event_type="feature.build.retry.exhausted",
                    summary=f"Build failed after {max_attempts} attempts (retry exhausted).",
                )
                failed += 1
                continue
            feature_row = conn.execute(
                "SELECT title FROM bug_reports WHERE id=? LIMIT 1",
                (feature_id,),
            ).fetchone()
            if feature_row is None:
                update_feature_build_run(
                    conn,
                    run_id,
                    status="failed",
                    retry_state="exhausted",
                    next_retry_at="",
                    last_progress_at=now_iso(),
                    last_event_type="feature.build.retry.exhausted",
                    summary="Build failed: feature request no longer exists.",
                )
                failed += 1
                continue
            trace_id = new_id("trc")
            update_feature_build_run(
                conn,
                run_id,
                trace_id=trace_id,
                retry_state="running",
                next_retry_at="",
                active_attempt=attempt_count,
                last_progress_at=now_iso(),
                last_event_type="feature.build.retry.started",
                last_trace_id=trace_id,
                summary=f"Retry attempt {attempt_count}/{max_attempts} dispatching.",
            )
            queued = runner.send_task(
                "jarvis.tasks.feature_build.run_feature_build",
                kwargs={
                    "run_id": run_id,
                    "feature_id": feature_id,
                    "trace_id": trace_id,
                    "title": str(feature_row["title"]),
                    "actor_id": actor_id,
                },
                queue="default",
            )
            if queued:
                dispatched += 1
                _emit_build_event(
                    conn=conn,
                    trace_id=trace_id,
                    thread_id=thread_id or None,
                    event_type="feature.build.retry.started",
                    payload={
                        "run_id": run_id,
                        "feature_id": feature_id,
                        "attempt_count": attempt_count,
                        "max_attempts": max_attempts,
                    },
                )
                continue
            delay = _resolve_retry_delay_seconds(attempt_count)
            next_retry_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
            update_feature_build_run(
                conn,
                run_id,
                retry_state="scheduled",
                next_retry_at=next_retry_at,
                last_progress_at=now_iso(),
                last_event_type="feature.build.retry.rescheduled",
                last_trace_id=trace_id,
                summary=(
                    f"Retry attempt {attempt_count}/{max_attempts} dispatch failed; "
                    f"rescheduled for {next_retry_at}."
                ),
            )
            _emit_build_event(
                conn=conn,
                trace_id=trace_id,
                thread_id=thread_id or None,
                event_type="feature.build.retry.rescheduled",
                payload={
                    "run_id": run_id,
                    "feature_id": feature_id,
                    "attempt_count": attempt_count,
                    "max_attempts": max_attempts,
                    "next_retry_at": next_retry_at,
                },
            )
            rescheduled += 1
    return {
        "attempted": attempted,
        "dispatched": dispatched,
        "rescheduled": rescheduled,
        "failed": failed,
    }
