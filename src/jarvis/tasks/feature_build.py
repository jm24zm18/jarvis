"""Feature request build-run task."""

from __future__ import annotations

from jarvis.db.connection import get_conn
from jarvis.db.queries import update_feature_build_run


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

    with get_conn() as conn:
        # Mark run as running.
        update_feature_build_run(conn, run_id, status="running")

        # Find or create a web_admin thread for build runs.
        row = conn.execute(
            "SELECT id FROM threads WHERE channel_type='web_admin' AND status='active' LIMIT 1",
        ).fetchone()
        if row is not None:
            thread_id = str(row["id"])
        else:
            thread_id = new_id("thr")
            now = now_iso()
            conn.execute(
                (
                    "INSERT INTO threads"
                    "(id, user_id, channel_type, status, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,?)"
                ),
                (thread_id, actor_id, "web_admin", "active", now, now),
            )

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
