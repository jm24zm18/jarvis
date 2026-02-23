import pytest
from fastapi import HTTPException

from jarvis.auth.dependencies import UserContext
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_feature_request,
    set_feature_request_approval,
)
from jarvis.routes.api.bugs import (
    FeatureSplitBody,
    FeatureSplitSubtask,
    split_feature_request_endpoint,
)
from jarvis.services.feature_requests import split_feature_request


def _setup_feature(parent_id: str | None = None) -> str:
    with get_conn() as conn:
        feature_id, _ = create_feature_request(
            conn,
            title="Parent",
            description="Parent desc",
            priority="medium",
            reporter_id="user",
            thread_id="",
            trace_id="trace",
        )
        set_feature_request_approval(conn, feature_id, decision="approved", actor_id="admin")
    return feature_id


def _simple_subtasks() -> list[dict[str, object]]:
    return [
        {
            "title": f"Task {i}",
            "description": "Implement something",
            "acceptance_criteria": "Add tests",
            "target_files": ["src/jarvis/tasks/feature_build.py"],
        }
        for i in range(3)
    ]


def test_split_feature_request_creates_children():
    feature_id = _setup_feature()
    with get_conn() as conn:
        child_ids = split_feature_request(
            conn,
            parent_id=feature_id,
            subtasks=_simple_subtasks(),
            actor_id="agent",
            split_reason="rlm",
        )
        assert len(child_ids) == 3
        for child_id in child_ids:
            row = conn.execute(
                "SELECT parent_id FROM bug_reports WHERE id=? LIMIT 1",
                (child_id,),
            ).fetchone()
            assert row is not None
            assert row["parent_id"] == feature_id


def test_split_feature_request_fails_on_child_parent():
    feature_id = _setup_feature()
    with get_conn() as conn:
        child_ids = split_feature_request(
            conn,
            parent_id=feature_id,
            subtasks=_simple_subtasks(),
            actor_id="agent",
            split_reason="rlm",
        )
        with pytest.raises(HTTPException):
            split_feature_request(
                conn,
                parent_id=child_ids[0],
                subtasks=_simple_subtasks(),
                actor_id="agent",
                split_reason="rlm",
            )


def test_split_route_dry_run_does_not_persist():
    feature_id = _setup_feature()
    admin_ctx = UserContext(user_id="admin", role="admin", scopes=frozenset({"*"}))
    subtotal = FeatureSplitSubtask(
        title="Dry run",
        description="Desc",
        acceptance_criteria="Add tests",
        target_files=["src/jarvis/tasks/feature_build.py"],
    )
    body = FeatureSplitBody(subtasks=[subtotal], dry_run=True)
    result = split_feature_request_endpoint(feature_id=feature_id, body=body, ctx=admin_ctx)
    assert result["dry_run"]
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM bug_reports WHERE parent_id=?",
            (feature_id,),
        ).fetchone()
        assert int(count["cnt"]) == 0
