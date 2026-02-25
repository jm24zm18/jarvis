"""Feature request approval and build-run service logic."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import HTTPException

from jarvis.config import get_settings
from jarvis.db.queries import (
    create_feature_build_run,
    list_feature_build_runs,
    now_iso,
    reconcile_stale_feature_build_runs,
    set_feature_request_approval,
    update_feature_build_run,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id


def approve_feature_request(
    conn: sqlite3.Connection,
    feature_id: str,
    *,
    decision: str,
    actor_id: str,
    note: str = "",
) -> dict[str, object]:
    """Apply an approval or rejection decision to a feature request.

    Raises HTTPException on invalid decision or if the feature does not exist.
    Returns a summary dict.
    """
    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail=f"Invalid decision: {decision!r}")
    row = conn.execute(
        "SELECT id, kind, approval_status FROM bug_reports WHERE id=? LIMIT 1",
        (feature_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Feature request not found")
    if str(row["kind"]) != "feature":
        raise HTTPException(status_code=400, detail="Record is not a feature request")
    set_feature_request_approval(conn, feature_id, decision=decision, actor_id=actor_id, note=note)
    return {
        "id": feature_id,
        "approval_status": decision,
        "approved_by" if decision == "approved" else "rejected_by": actor_id,
        "note": note,
    }


def enqueue_feature_build(
    conn: sqlite3.Connection,
    feature_id: str,
    *,
    actor_id: str,
    task_runner: object,
) -> dict[str, object]:
    """Create a build run record and enqueue the build task.

    Requires the feature to be in 'approved' state.
    Returns run metadata including run_id and trace_id.
    """
    row = conn.execute(
        (
            "SELECT id, kind, approval_status, title, thread_id "
            "FROM bug_reports WHERE id=? LIMIT 1"
        ),
        (feature_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Feature request not found")
    if str(row["kind"]) != "feature":
        raise HTTPException(status_code=400, detail="Record is not a feature request")
    if str(row["approval_status"]) != "approved":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Feature must be approved before building; "
                f"current approval_status={row['approval_status']!r}"
            ),
        )
    source_thread_id = str(row["thread_id"] or "").strip()
    run_id = create_feature_build_run(
        conn,
        feature_id=feature_id,
        created_by=actor_id,
        source_thread_id=source_thread_id,
        execution_mode="direct",
    )
    from jarvis.ids import new_id

    settings = get_settings()
    max_attempts = max(1, int(settings.feature_build_retry_max_attempts))
    trace_id = new_id("trc")
    update_feature_build_run(
        conn,
        run_id,
        trace_id=trace_id,
        max_attempts=max_attempts,
        attempt_count=1,
        retry_state="none",
        next_retry_at="",
        last_failure_reason="",
    )

    from jarvis.tasks.runner import TaskRunner

    runner = task_runner
    queued = False
    if isinstance(runner, TaskRunner):
        queued = runner.send_task(
            "jarvis.tasks.feature_build.run_feature_build",
            kwargs={
                "run_id": run_id,
                "feature_id": feature_id,
                "trace_id": trace_id,
                "title": str(row["title"]),
                "actor_id": actor_id,
            },
            queue="default",
        )
    if not queued:
        conn.execute(
            (
                "UPDATE feature_request_build_runs"
                " SET status='failed', summary=?, updated_at=datetime('now') WHERE id=?"
            ),
            ("Failed to enqueue build task", run_id),
        )
    return {
        "run_id": run_id,
        "trace_id": trace_id,
        "feature_id": feature_id,
        "execution_mode": "direct",
        "target_thread_id": source_thread_id,
        "status": "queued" if queued else "failed",
        "queued": queued,
    }


def get_feature_build_runs(
    conn: sqlite3.Connection,
    feature_id: str,
    limit: int = 20,
) -> list[dict[str, object]]:
    row = conn.execute(
        "SELECT id, kind FROM bug_reports WHERE id=? LIMIT 1",
        (feature_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Feature request not found")
    if str(row["kind"]) != "feature":
        raise HTTPException(status_code=400, detail="Record is not a feature request")
    # Keep run statuses honest for the UI by reconciling stale "running" entries.
    reconcile_stale_feature_build_runs(conn, stale_after_seconds=900, limit=200)
    return list_feature_build_runs(conn, feature_id, limit=limit)


def reconcile_feature_build_runs(
    conn: sqlite3.Connection,
    *,
    stale_after_seconds: int = 900,
    limit: int = 200,
) -> dict[str, object]:
    return reconcile_stale_feature_build_runs(
        conn,
        stale_after_seconds=stale_after_seconds,
        limit=limit,
    )


def split_feature_request(
    conn: sqlite3.Connection,
    parent_id: str,
    *,
    subtasks: list[dict[str, Any]],
    actor_id: str,
    split_reason: str = "manual",
) -> list[str]:
    row = conn.execute(
        (
            "SELECT parent_id, priority, reporter_id, assignee_agent, thread_id, trace_id, "
            "approval_status FROM bug_reports WHERE id=? LIMIT 1"
        ),
        (parent_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Parent feature not found")
    if row["parent_id"]:
        raise HTTPException(
            status_code=400,
            detail="Cannot split a child feature request (no grandchildren allowed)",
        )
    priority = str(row["priority"] or "medium")
    reporter_id = str(row["reporter_id"] or "")
    assignee_agent = row["assignee_agent"]
    thread_id = str(row["thread_id"] or "")
    trace_id = str(row["trace_id"] or "")
    approval_status = str(row["approval_status"] or "approved")
    child_ids: list[str] = []
    now = now_iso()
    for idx, subtask in enumerate(subtasks, start=1):
        title = str(subtask.get("title") or "").strip()
        description = str(subtask.get("description") or "").strip()
        acceptance = str(subtask.get("acceptance_criteria") or "").strip()
        target_files = subtask.get("target_files") or []
        if isinstance(target_files, str):
            target_files = [target_files]
        target_list = ", ".join(
            str(path).strip() for path in target_files if str(path).strip()
        )
        if not title:
            raise HTTPException(status_code=400, detail=f"Subtask {idx} missing title.")
        if not description:
            raise HTTPException(status_code=400, detail=f"Subtask {idx} missing description.")
        description_parts = [description]
        if acceptance:
            description_parts.append(f"Acceptance criteria: {acceptance}")
        if target_list:
            description_parts.append(f"Target files: {target_list}")
        child_description = "\n\n".join(description_parts)
        child_id = new_id("bug")
        conn.execute(
            (
                "INSERT INTO bug_reports("
                "id, kind, title, description, status, priority, reporter_id, assignee_agent, "
                "thread_id, trace_id, parent_id, approval_status, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                child_id,
                "feature",
                title,
                child_description,
                "open",
                priority,
                reporter_id,
                assignee_agent,
                thread_id or None,
                trace_id or None,
                parent_id,
                approval_status,
                now,
                now,
            ),
        )
        child_ids.append(child_id)
    payload = {
        "parent_id": parent_id,
        "child_ids": child_ids,
        "split_reason": split_reason,
    }
    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id or None,
            event_type="feature.split",
            component="feature_build",
            actor_type="system",
            actor_id=actor_id,
            payload_json=json.dumps(payload),
            payload_redacted_json=json.dumps(redact_payload(payload)),
        ),
    )
    return child_ids
