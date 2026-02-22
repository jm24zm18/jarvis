"""Feature request approval and build-run service logic."""

from __future__ import annotations

import sqlite3

from fastapi import HTTPException

from jarvis.config import get_settings
from jarvis.db.queries import (
    create_feature_build_run,
    list_feature_build_runs,
    reconcile_stale_feature_build_runs,
    set_feature_request_approval,
    update_feature_build_run,
)


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
        "SELECT id, kind, approval_status, title FROM bug_reports WHERE id=? LIMIT 1",
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
    run_id = create_feature_build_run(conn, feature_id=feature_id, created_by=actor_id)
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
