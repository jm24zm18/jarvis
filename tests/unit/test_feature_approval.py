"""Unit tests for feature request approval and build-run query helpers."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    consume_approval,
    create_approval,
    create_feature_build_run,
    list_approvals,
    list_feature_build_runs,
    now_iso,
    reconcile_stale_feature_build_runs,
    revoke_approval,
    set_feature_request_approval,
    update_feature_build_run,
)
from jarvis.ids import new_id


def _insert_feature(conn, title: str = "Test feature") -> str:
    fid = new_id("bug")
    now = now_iso()
    conn.execute(
        (
            "INSERT INTO bug_reports"
            "(id, kind, title, description, status, priority, "
            "reporter_id, assignee_agent, thread_id, trace_id, "
            "github_issue_number, github_issue_url, github_synced_at, github_sync_error, "
            "created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        (
            fid, "feature", title, "", "open", "medium",
            "usr_test", None, None, None,
            None, None, None, None,
            now, now,
        ),
    )
    return fid


# ---------------------------------------------------------------------------
# Feature approval helpers
# ---------------------------------------------------------------------------

def test_set_feature_request_approval_approve() -> None:
    with get_conn() as conn:
        fid = _insert_feature(conn)
        set_feature_request_approval(conn, fid, decision="approved", actor_id="usr_admin")
        row = conn.execute(
            "SELECT approval_status, approved_by, rejected_by FROM bug_reports WHERE id=?",
            (fid,),
        ).fetchone()
    assert row is not None
    assert str(row["approval_status"]) == "approved"
    assert str(row["approved_by"]) == "usr_admin"
    assert row["rejected_by"] is None


def test_set_feature_request_approval_reject() -> None:
    with get_conn() as conn:
        fid = _insert_feature(conn)
        set_feature_request_approval(
            conn, fid, decision="rejected", actor_id="usr_admin", note="Not now"
        )
        row = conn.execute(
            (
                "SELECT approval_status, rejected_by, approved_by, approval_note"
                " FROM bug_reports WHERE id=?"
            ),
            (fid,),
        ).fetchone()
    assert row is not None
    assert str(row["approval_status"]) == "rejected"
    assert str(row["rejected_by"]) == "usr_admin"
    assert row["approved_by"] is None
    assert str(row["approval_note"]) == "Not now"


def test_set_feature_request_approval_invalid_decision() -> None:
    with get_conn() as conn:
        fid = _insert_feature(conn)
        with pytest.raises(ValueError):
            set_feature_request_approval(conn, fid, decision="pending", actor_id="usr_admin")


def test_set_feature_request_approval_not_found() -> None:
    with get_conn() as conn:
        with pytest.raises(HTTPException) as exc_info:
            set_feature_request_approval(
                conn, "bug_nonexistent", decision="approved", actor_id="usr_admin"
            )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Feature build run helpers
# ---------------------------------------------------------------------------

def test_create_and_list_feature_build_runs() -> None:
    with get_conn() as conn:
        fid = _insert_feature(conn)
        run_id = create_feature_build_run(
            conn, feature_id=fid, created_by="usr_admin", trace_id="trc_test"
        )
        runs = list_feature_build_runs(conn, fid)

    assert len(runs) == 1
    assert str(runs[0]["id"]) == run_id
    assert str(runs[0]["status"]) == "queued"
    assert str(runs[0]["trace_id"]) == "trc_test"


def test_update_feature_build_run_status() -> None:
    with get_conn() as conn:
        fid = _insert_feature(conn)
        run_id = create_feature_build_run(conn, feature_id=fid, created_by="usr_admin")
        update_feature_build_run(conn, run_id, status="succeeded", summary="All good")
        row = conn.execute(
            "SELECT status, summary FROM feature_request_build_runs WHERE id=?",
            (run_id,),
        ).fetchone()

    assert str(row["status"]) == "succeeded"
    assert str(row["summary"]) == "All good"


def test_update_feature_build_run_invalid_status() -> None:
    with get_conn() as conn:
        fid = _insert_feature(conn)
        run_id = create_feature_build_run(conn, feature_id=fid, created_by="usr_admin")
        with pytest.raises(ValueError):
            update_feature_build_run(conn, run_id, status="unknown_status")


def test_reconcile_stale_feature_build_runs_marks_stale_running_failed() -> None:
    with get_conn() as conn:
        fid = _insert_feature(conn)
        run_id = create_feature_build_run(conn, feature_id=fid, created_by="usr_admin")
        stale_stamp = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        conn.execute(
            "UPDATE feature_request_build_runs SET status='running', updated_at=? WHERE id=?",
            (stale_stamp, run_id),
        )

        result = reconcile_stale_feature_build_runs(conn, stale_after_seconds=60, limit=10)
        row = conn.execute(
            "SELECT status, summary FROM feature_request_build_runs WHERE id=?",
            (run_id,),
        ).fetchone()

    assert int(result["reconciled"]) == 1
    assert run_id in result["ids"]
    assert row is not None
    assert str(row["status"]) == "failed"
    assert "stale running timeout" in str(row["summary"])


# ---------------------------------------------------------------------------
# Approval list / revoke helpers
# ---------------------------------------------------------------------------

def test_list_approvals_filters() -> None:
    with get_conn() as conn:
        aid1 = create_approval(
            conn, action="selfupdate.apply", actor_id="usr_a", target_ref="trc_1"
        )
        aid2 = create_approval(conn, action="host.exec.shell", actor_id="usr_b")

        all_approvals = list_approvals(conn)
        apply_only = list_approvals(conn, action="selfupdate.apply")
        shell_only = list_approvals(conn, action="host.exec.shell")

    ids = [str(a["id"]) for a in all_approvals]
    assert aid1 in ids
    assert aid2 in ids

    apply_ids = [str(a["id"]) for a in apply_only]
    assert aid1 in apply_ids
    assert aid2 not in apply_ids

    shell_ids = [str(a["id"]) for a in shell_only]
    assert aid2 in shell_ids
    assert aid1 not in shell_ids


def test_revoke_approval_success() -> None:
    with get_conn() as conn:
        aid = create_approval(
            conn, action="selfupdate.apply", actor_id="usr_admin", target_ref="trc_x"
        )
        revoked = revoke_approval(conn, aid, actor_id="usr_admin")
        row = conn.execute("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()

    assert revoked is True
    assert str(row["status"]) == "revoked"


def test_revoke_approval_not_found() -> None:
    with get_conn() as conn:
        result = revoke_approval(conn, "apr_nonexistent", actor_id="usr_admin")
    assert result is False


def test_revoke_approval_already_consumed() -> None:
    with get_conn() as conn:
        aid = create_approval(
            conn, action="selfupdate.apply", actor_id="usr_admin", target_ref="trc_y"
        )
        consume_approval(conn, "selfupdate.apply", target_ref="trc_y")
        result = revoke_approval(conn, aid, actor_id="usr_admin")

    assert result is False
