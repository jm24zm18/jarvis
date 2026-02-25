"""Feature request build-run task."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_human_escalation,
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
from jarvis.rlm.config import build_rlm_config
from jarvis.rlm.decomposer import compute_run_hash, context_reasons, select_context_files
from jarvis.rlm.fallback_splitter import build_fallback_subtasks
from jarvis.rlm.service import AsyncRLMService
from jarvis.services.feature_requests import enqueue_feature_build, split_feature_request
from jarvis.tasks.github import github_feature_validation_comment
from jarvis.tools.feature_isolate import (
    IsolationError,
    WorkspaceContext,
    cleanup_expired_workspaces,
    create_workspace,
    validate_workspace,
)

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
        "blocker_category": str(capsule.get("blocker_category", "")),
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
    blocker_category: str = "",
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
        "blocker_category": blocker_category[:64],
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


def _emit_rlm_event(
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
            component="rlm",
            actor_type="system",
            actor_id="rlm",
            payload_json=json.dumps(payload),
            payload_redacted_json=json.dumps(redact_payload(payload)),
        ),
    )


def _get_rlm_trajectory(
    conn: sqlite3.Connection,
    feature_id: str,
    run_hash: str,
) -> dict[str, object] | None:
    row = conn.execute(
        "SELECT * FROM rlm_trajectories WHERE feature_id=? AND run_hash=? LIMIT 1",
        (feature_id, run_hash),
    ).fetchone()
    return dict(row) if row is not None else None


def _create_rlm_trajectory(
    conn: sqlite3.Connection,
    *,
    feature_id: str,
    run_id: str,
    trace_id: str,
    run_hash: str,
    context_paths: list[str],
    context_reasons_json: str,
) -> dict[str, object]:
    trajectory_id = new_id("trc")
    now = now_iso()
    try:
        conn.execute(
            (
                "INSERT INTO rlm_trajectories("
                "id, feature_id, run_id, trace_id, run_hash, status, context_paths_json, "
                "context_reasons_json, error, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                trajectory_id,
                feature_id,
                run_id,
                trace_id,
                run_hash,
                "in_progress",
                json.dumps(context_paths),
                context_reasons_json,
                "",
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError:
        existing = _get_rlm_trajectory(conn, feature_id, run_hash)
        if existing is not None:
            return existing
        raise
    return _get_rlm_trajectory(conn, feature_id, run_hash)  # type: ignore[return-value]


def _update_rlm_trajectory(
    conn: sqlite3.Connection,
    trajectory_id: str,
    **fields: str,
) -> None:
    if not fields:
        return
    updates = []
    params: list[object] = []
    for key, value in fields.items():
        updates.append(f"{key}=?")
        params.append(value)
    updates.append("updated_at=?")
    params.append(now_iso())
    params.append(trajectory_id)
    conn.execute(
        f"UPDATE rlm_trajectories SET {', '.join(updates)} WHERE id=?",
        tuple(params),
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


def _feature_scope_layers(text: str) -> set[str]:
    lowered = text.lower()
    layers: dict[str, tuple[str, ...]] = {
        "db": ("db", "database", "sqlite", "schema", "migration"),
        "services": ("service", "business logic"),
        "tasks": ("task", "orchestrator", "runner"),
        "memory": ("memory", "state item"),
        "prompt": ("prompt", "agent bundle", "identity.md", "soul.md"),
        "docs": ("docs", "documentation", "runbook", "guide"),
        "cli": ("cli", "command"),
        "web": ("web", "ui", "frontend", "react", "theme", "styles"),
        "api": ("api", "endpoint", "route"),
        "skills": ("skill", "skills"),
    }
    detected: set[str] = set()
    for layer, needles in layers.items():
        if any(token in lowered for token in needles):
            detected.add(layer)
    return detected


def _is_broad_scope_feature(*, title: str, description: str) -> bool:
    text = f"{title}\n{description}"
    layers = _feature_scope_layers(text)
    path_markers = text.count("src/") + text.count("web/") + text.count("docs/")
    has_db = "migration" in text.lower() or "schema" in text.lower() or "db" in text.lower()
    has_web = "web" in layers or "ui" in text.lower() or "frontend" in text.lower()
    has_backend = bool({"api", "services", "tasks", "db"} & layers)
    has_skills_or_prompt = bool({"skills", "prompt"} & layers)
    return (
        len(layers) >= 3
        or has_db and (has_web or has_backend)
        or path_markers >= 4
        or (has_backend and has_skills_or_prompt)
    )


def _choose_build_thread(
    *,
    conn: sqlite3.Connection,
    run_row: dict[str, object],
    actor_id: str,
    settings,
) -> str:
    existing_thread_id = str(run_row.get("thread_id") or "").strip()
    if existing_thread_id:
        row = conn.execute(
            "SELECT id FROM threads WHERE id=? AND status='open' LIMIT 1",
            (existing_thread_id,),
        ).fetchone()
        if row is not None:
            return str(row["id"])

    target_mode = str(getattr(settings, "feature_build_thread_target", "reporter") or "reporter")
    target_mode = target_mode.strip().lower()
    if target_mode not in {"reporter", "admin"}:
        target_mode = "reporter"

    if target_mode == "reporter":
        source_thread_id = str(run_row.get("source_thread_id") or "").strip()
        if source_thread_id:
            row = conn.execute(
                "SELECT id FROM threads WHERE id=? AND status='open' LIMIT 1",
                (source_thread_id,),
            ).fetchone()
            if row is not None:
                return str(row["id"])

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
        return str(row["id"])
    channel_id = ensure_channel(conn, actor_id, "web")
    return create_thread(conn, actor_id, channel_id)


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
        if int(settings.feature_isolation_enabled) == 1:
            _ = cleanup_expired_workspaces(
                tmp_prefix=str(settings.feature_isolation_tmp_prefix),
                ttl_hours=int(settings.feature_isolation_ttl_hours),
            )
        rlm_config = build_rlm_config(settings)
        with get_conn() as conn:
            feature_row = conn.execute(
                "SELECT title, description FROM bug_reports WHERE id=? AND kind='feature' LIMIT 1",
                (feature_id,),
            ).fetchone()
        feature_title = str(feature_row["title"] or title) if feature_row is not None else title
        feature_description = (
            str(feature_row["description"] or "") if feature_row is not None else ""
        )
        broad_scope = _is_broad_scope_feature(title=feature_title, description=feature_description)
        force_decompose = (
            not rlm_config.active
            and broad_scope
            and int(settings.feature_build_auto_decompose) == 1
        )
        rlm_result = _decompose_and_split(
            run_id=run_id,
            feature_id=feature_id,
            trace_id=trace_id,
            actor_id=actor_id,
            settings=settings,
            rlm_config=rlm_config,
            force=force_decompose,
            use_fallback=int(settings.feature_build_decompose_fallback) == 1,
            layer_strict=int(settings.feature_build_subtask_layer_strict) == 1,
        )
        if rlm_result is not None:
            return rlm_result
        with get_conn() as conn:
            run_row = get_feature_build_run(conn, run_id)
            if run_row is None:
                raise RuntimeError(f"feature build run not found: {run_id}")
            if int(settings.feature_isolation_enabled) == 1:
                workspace_path = str(run_row.get("workspace_path") or "").strip()
                if not workspace_path:
                    _emit_build_event(
                        conn=conn,
                        trace_id=trace_id,
                        thread_id=None,
                        event_type="feature.isolation.workspace.creating",
                        payload={"run_id": run_id, "feature_id": feature_id},
                    )
                    ctx = create_workspace(
                        feature_id,
                        repo_root=Path.cwd(),
                        tmp_prefix=str(settings.feature_isolation_tmp_prefix),
                        clone_ref=str(settings.feature_isolation_clone_ref),
                        ttl_hours=int(settings.feature_isolation_ttl_hours),
                        min_free_gb=int(settings.feature_isolation_min_disk_gb),
                    )
                else:
                    raw_snapshot = (
                        str(run_row.get("dependency_snapshot_json") or "{}").strip() or "{}"
                    )
                    try:
                        parsed_snapshot = json.loads(raw_snapshot)
                    except json.JSONDecodeError:
                        parsed_snapshot = {}
                    ctx = WorkspaceContext(
                        feature_id=feature_id,
                        workspace_path=Path(workspace_path),
                        created_at=str(run_row.get("workspace_created_at") or ""),
                        expires_at=str(run_row.get("workspace_expires_at") or ""),
                        dependency_snapshot=(
                            parsed_snapshot
                            if isinstance(parsed_snapshot, dict)
                            else {}
                        ),
                    )
                validation = validate_workspace(
                    ctx, min_free_gb=int(settings.feature_isolation_min_disk_gb)
                )
                update_feature_build_run(
                    conn,
                    run_id,
                    workspace_path=str(ctx.workspace_path),
                    workspace_created_at=ctx.created_at,
                    workspace_expires_at=ctx.expires_at,
                    dependency_snapshot_json=json.dumps(ctx.dependency_snapshot),
                    validation_status="passed" if validation.ok else "failed",
                    validation_log_path=validation.log_path,
                    validation_error=validation.error,
                )
                _emit_build_event(
                    conn=conn,
                    trace_id=trace_id,
                    thread_id=None,
                    event_type=(
                        "feature.isolation.validation.passed"
                        if validation.ok
                        else "feature.isolation.validation.failed"
                    ),
                    payload={
                        "run_id": run_id,
                        "feature_id": feature_id,
                        "workspace_path": str(ctx.workspace_path),
                        "validation_log_path": validation.log_path,
                        "error": validation.error,
                    },
                )
                try:
                    _ = github_feature_validation_comment(
                        feature_id=feature_id,
                        run_id=run_id,
                        validation_status="passed" if validation.ok else "failed",
                        validation_log_path=validation.log_path,
                        dependency_snapshot_json=json.dumps(ctx.dependency_snapshot),
                        error=validation.error,
                    )
                except Exception:
                    logger.exception(
                        "failed to post feature validation comment: run_id=%s feature_id=%s",
                        run_id,
                        feature_id,
                    )
                if not validation.ok:
                    update_feature_build_run(
                        conn,
                        run_id,
                        status="failed",
                        summary=f"Isolation validation failed: {validation.error}"[:500],
                        terminal_reason="isolation_validation_failed",
                        last_event_type="feature.isolation.validation.failed",
                    )
                    return {
                        "run_id": run_id,
                        "feature_id": feature_id,
                        "trace_id": trace_id,
                        "status": "failed",
                        "error": f"isolation validation failed: {validation.error}",
                    }

            attempt_count = max(1, int(run_row.get("attempt_count", 1)))
            max_attempts = max(attempt_count, int(run_row.get("max_attempts", attempt_count)))
            update_feature_build_run(
                conn,
                run_id,
                status="running",
                trace_id=trace_id,
                execution_mode="direct",
                retry_state="none",
                next_retry_at="",
                active_attempt=attempt_count,
                last_progress_at=now_iso(),
                last_event_type="feature.build.attempt.start",
                last_trace_id=trace_id,
                summary=f"Build attempt {attempt_count}/{max_attempts} in progress.",
            )

            # Route build updates to the configured thread target.
            thread_id = _choose_build_thread(
                conn=conn,
                run_row=run_row,
                actor_id=actor_id,
                settings=settings,
            )

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
                "4) if blocked, explicitly report blockers and missing prerequisites.\n\n"
                "Isolation requirements:\n"
                "- Execute all build/test commands from the isolated workspace "
                "configured for this run.\n"
                "- Do not run write operations against the primary repository checkout."
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
            kwargs={"thread_id": thread_id, "trace_id": trace_id, "actor_id": "feature_builder"},
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
        if isinstance(exc, IsolationError):
            with get_conn() as conn:
                update_feature_build_run(
                    conn,
                    run_id,
                    status="failed",
                    summary=f"Isolation setup failed: {exc}"[:500],
                    validation_status="failed",
                    validation_error=str(exc),
                    terminal_reason="isolation_setup_failed",
                )
            return {
                "run_id": run_id,
                "feature_id": feature_id,
                "trace_id": trace_id,
                "status": "failed",
                "error": f"isolation setup failed: {exc}",
            }
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


def _decompose_and_split(
    *,
    run_id: str,
    feature_id: str,
    trace_id: str,
    actor_id: str,
    settings,
    rlm_config,
    force: bool = False,
    use_fallback: bool = True,
    layer_strict: bool = True,
) -> dict[str, object] | None:
    if not rlm_config.active and not force:
        return None
    with get_conn() as conn:
        feature_row = conn.execute(
            "SELECT id, title, description FROM bug_reports WHERE id=? AND kind='feature' LIMIT 1",
            (feature_id,),
        ).fetchone()
    if feature_row is None:
        return None
    feature_title = str(feature_row["title"] or "")
    feature_description = str(feature_row["description"] or "")
    context_files = select_context_files(feature_description, rlm_config)
    run_hash = compute_run_hash(feature_id, feature_description, context_files)
    context_paths = [item.path for item in context_files]
    reasons_json = json.dumps(context_reasons(context_files))
    with get_conn() as conn:
        trajectory = _get_rlm_trajectory(conn, feature_id, run_hash)
        if trajectory is not None:
            status = str(trajectory["status"])
            child_ids_json = str(trajectory.get("child_ids_json") or "")
            if status == "completed" and child_ids_json:
                return {
                    "run_id": run_id,
                    "feature_id": feature_id,
                    "trace_id": trace_id,
                    "status": "decomposed",
                    "child_ids": json.loads(child_ids_json),
                }
            if status == "in_progress":
                return None
        trajectory = _create_rlm_trajectory(
            conn,
            feature_id=feature_id,
            run_id=run_id,
            trace_id=trace_id,
            run_hash=run_hash,
            context_paths=context_paths,
            context_reasons_json=reasons_json,
        )
    trajectory_id = str(trajectory["id"])
    service = AsyncRLMService(settings)
    result = asyncio.run(
        service.decompose(feature_id, feature_title, feature_description, context_files)
    )
    with get_conn() as conn:
        run_row = get_feature_build_run(conn, run_id)
        thread_id = str(run_row["thread_id"] or "") if run_row else ""
        if result["status"] == "success":
            child_ids = split_feature_request(
                conn,
                parent_id=feature_id,
                subtasks=result["subtasks"],
                actor_id=actor_id,
                split_reason="rlm",
            )
            usage_json = json.dumps(result.get("usage") or {})
            _update_rlm_trajectory(
                conn,
                trajectory_id,
                status="completed",
                prompt_hash=result.get("prompt_hash", ""),
                results_raw=result.get("raw", ""),
                usage_json=usage_json,
                child_ids_json=json.dumps(child_ids),
                validation_errors_json="[]",
                error="",
                provider=result.get("provider", ""),
            )
            update_feature_build_run(
                conn,
                run_id,
                status="decomposed",
                summary=f"Decomposed into {len(child_ids)} child feature builds.",
                terminal_reason="decomposed",
                last_event_type="feature.build.decomposed",
                execution_mode="decomposed",
            )
            _emit_build_event(
                conn=conn,
                trace_id=trace_id,
                thread_id=thread_id or None,
                event_type="feature.build.decomposed",
                payload={
                    "run_id": run_id,
                    "feature_id": feature_id,
                    "child_ids": child_ids,
                    "trajectory_id": trajectory_id,
                    "decomposition_mode": "rlm_forced" if force else "rlm",
                },
            )
            _emit_rlm_event(
                conn=conn,
                trace_id=trace_id,
                thread_id=thread_id or None,
                event_type="rlm.decompose.complete",
                payload={
                    "run_id": run_id,
                    "feature_id": feature_id,
                    "trajectory_id": trajectory_id,
                    "child_ids": child_ids,
                },
            )
            from jarvis.tasks import get_task_runner

            runner = get_task_runner()
            for child_id in child_ids:
                enqueue_feature_build(
                    conn,
                    child_id,
                    actor_id=actor_id,
                    task_runner=runner,
                )
            return {
                "run_id": run_id,
                "feature_id": feature_id,
                "trace_id": trace_id,
                "status": "decomposed",
                "child_ids": child_ids,
            }
        if use_fallback:
            fallback_subtasks = build_fallback_subtasks(
                feature_title=feature_title,
                feature_description=feature_description,
                layer_strict=layer_strict,
            )
            if len(fallback_subtasks) >= 3:
                child_ids = split_feature_request(
                    conn,
                    parent_id=feature_id,
                    subtasks=fallback_subtasks,
                    actor_id=actor_id,
                    split_reason="fallback_split",
                )
                _update_rlm_trajectory(
                    conn,
                    trajectory_id,
                    status="completed",
                    prompt_hash=result.get("prompt_hash", ""),
                    results_raw=result.get("raw", ""),
                    usage_json=json.dumps(result.get("usage") or {}),
                    child_ids_json=json.dumps(child_ids),
                    validation_errors_json=json.dumps(
                        (result.get("validation_errors") or []) + ["fallback_split"]
                    ),
                    error="",
                    provider=result.get("provider", ""),
                )
                update_feature_build_run(
                    conn,
                    run_id,
                    status="decomposed",
                    summary=(
                        "RLM decomposition failed; deterministic fallback split created "
                        f"{len(child_ids)} child feature builds."
                    )[:500],
                    terminal_reason="decomposed",
                    last_event_type="feature.build.decomposed",
                    execution_mode="fallback_split",
                )
                _emit_build_event(
                    conn=conn,
                    trace_id=trace_id,
                    thread_id=thread_id or None,
                    event_type="feature.build.decomposed",
                    payload={
                        "run_id": run_id,
                        "feature_id": feature_id,
                        "child_ids": child_ids,
                        "trajectory_id": trajectory_id,
                        "decomposition_mode": "fallback_split",
                        "fallback_reason": result.get("error") or "rlm_decompose_failed",
                    },
                )
                from jarvis.tasks import get_task_runner

                runner = get_task_runner()
                for child_id in child_ids:
                    enqueue_feature_build(
                        conn,
                        child_id,
                        actor_id=actor_id,
                        task_runner=runner,
                    )
                return {
                    "run_id": run_id,
                    "feature_id": feature_id,
                    "trace_id": trace_id,
                    "status": "decomposed",
                    "child_ids": child_ids,
                }
        error_code = result.get("error") or "rlm_decompose_failed"
        usage_json = json.dumps(result.get("usage") or {})
        validation_errors = result.get("validation_errors") or []
        _update_rlm_trajectory(
            conn,
            trajectory_id,
            status=result["status"],
            prompt_hash=result.get("prompt_hash", ""),
            results_raw=result.get("raw", ""),
            usage_json=usage_json,
            validation_errors_json=json.dumps(validation_errors),
            error=error_code,
            provider=result.get("provider", ""),
        )
        failure_summary = (
            f"RLM decomposition failed: {error_code}. "
            + ("; ".join(validation_errors) if validation_errors else "")
        ).strip()
        update_feature_build_run(
            conn,
            run_id,
            status="failed",
            summary=failure_summary[:500],
            terminal_reason=error_code,
            last_event_type="feature.build.decompose.failed",
        )
        _emit_build_event(
            conn=conn,
            trace_id=trace_id,
            thread_id=thread_id or None,
            event_type="feature.build.decompose.failed",
            payload={
                "run_id": run_id,
                "feature_id": feature_id,
                "error": error_code,
                "validation_errors": validation_errors,
                "trajectory_id": trajectory_id,
            },
        )
        event_type = (
            "rlm.decompose.timeout"
            if result["status"] == "timeout"
            else "rlm.decompose.failed"
        )
        _emit_rlm_event(
            conn=conn,
            trace_id=trace_id,
            thread_id=thread_id or None,
            event_type=event_type,
            payload={
                "run_id": run_id,
                "feature_id": feature_id,
                "trajectory_id": trajectory_id,
                "error": error_code,
                "validation_errors": validation_errors,
            },
        )
        create_human_escalation(
            conn,
            thread_id=thread_id,
            trace_id=trace_id,
            requested_by_actor_id=actor_id,
            source_agent_id="rlm",
            reason=error_code,
            message=failure_summary,
            channel_type=str(settings.human_escalation_channel_type or "whatsapp"),
            target_external_id=str(settings.human_escalation_targets or ""),
            priority=str(settings.human_escalation_default_priority or "normal"),
        )
    return {
        "run_id": run_id,
        "feature_id": feature_id,
        "trace_id": trace_id,
        "status": "failed",
        "error": error_code,
    }
