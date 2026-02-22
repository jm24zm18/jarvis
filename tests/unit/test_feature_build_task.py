from jarvis.db.connection import get_conn
from jarvis.db.queries import create_feature_build_run, ensure_system_state, ensure_user
from jarvis.tasks.feature_build import run_feature_build


def test_run_feature_build_uses_current_thread_channel_schema(monkeypatch) -> None:
    queued: list[tuple[str, dict[str, object], str]] = []

    class _Runner:
        def send_task(self, name: str, kwargs: dict[str, object], queue: str) -> bool:
            queued.append((name, kwargs, queue))
            return True

    monkeypatch.setattr("jarvis.tasks.get_task_runner", lambda: _Runner())

    with get_conn() as conn:
        ensure_system_state(conn)
        actor_id = ensure_user(conn, "web_admin_feature_build")
        run_id = create_feature_build_run(conn, feature_id="bug_feature_build", created_by=actor_id)

    result = run_feature_build(
        run_id=run_id,
        feature_id="bug_feature_build",
        trace_id="trc_feature_build_1",
        title="Feature Build Thread Schema",
        actor_id=actor_id,
    )

    assert result["status"] == "running"
    assert queued
    assert queued[0][0] == "jarvis.tasks.agent.agent_step"

    with get_conn() as conn:
        row = conn.execute(
            "SELECT thread_id, status FROM feature_request_build_runs WHERE id=? LIMIT 1",
            (run_id,),
        ).fetchone()
        assert row is not None
        assert str(row["thread_id"])
        assert str(row["status"]) == "running"


def test_run_feature_build_marks_failed_on_internal_exception(monkeypatch) -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        actor_id = ensure_user(conn, "web_admin_feature_build_fail")
        run_id = create_feature_build_run(
            conn,
            feature_id="bug_feature_build_fail",
            created_by=actor_id,
        )

    def _explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("jarvis.tasks.feature_build.ensure_channel", _explode)

    result = run_feature_build(
        run_id=run_id,
        feature_id="bug_feature_build_fail",
        trace_id="trc_feature_build_fail",
        title="Feature Build Failure",
        actor_id=actor_id,
    )

    assert result["status"] == "failed"
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, summary FROM feature_request_build_runs WHERE id=? LIMIT 1",
            (run_id,),
        ).fetchone()
        assert row is not None
        assert str(row["status"]) == "failed"
        assert "RuntimeError: boom" in str(row["summary"])
