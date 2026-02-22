"""Feature request build-run task."""

from __future__ import annotations

import logging

from jarvis.db.connection import get_conn
from jarvis.db.queries import create_thread, ensure_channel, update_feature_build_run

logger = logging.getLogger(__name__)


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
    from jarvis.db.queries import now_iso
    from jarvis.ids import new_id
    from jarvis.tasks import get_task_runner

    try:
        with get_conn() as conn:
            # Mark run as running.
            update_feature_build_run(conn, run_id, status="running")

            # Find or create a web channel thread for build runs.
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

            # Insert build instruction message.
            msg_id = new_id("msg")
            now = now_iso()
            build_instruction = (
                f"Build feature request {feature_id!r}: {title!r}\n\n"
                "Review the feature description, implement the required changes following "
                "established patterns, run tests and linting, and open a pull request to dev. "
                "Record evidence for each step."
            )
            conn.execute(
                (
                    "INSERT INTO messages(id, thread_id, role, content, created_at) "
                    "VALUES(?,?,?,?,?)"
                ),
                (msg_id, thread_id, "user", build_instruction, now),
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
                    summary="agent_step task could not be enqueued",
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
