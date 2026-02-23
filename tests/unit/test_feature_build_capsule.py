"""Unit tests for feature build attempt capsule helpers and repeat fail-fast logic."""

from __future__ import annotations

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_feature_build_run,
    ensure_system_state,
    ensure_user,
)
from jarvis.tasks.feature_build import (
    _build_attempt_capsule,
    _capsule_stable_hash,
    _format_capsule_summary,
    get_previous_capsule,
    save_capsule,
)

# ---------------------------------------------------------------------------
# _capsule_stable_hash
# ---------------------------------------------------------------------------


def test_capsule_stable_hash_deterministic() -> None:
    capsule = _build_attempt_capsule(
        run_id="run_1",
        trace_id="trc_1",
        attempt=1,
        reason="insufficient_deliverable_evidence",
        changed_files=["src/foo.py", "src/bar.py"],
        tools_used=["exec_host", "write_file"],
        top_errors=["Permission denied"],
        blockers_summary="Missing env var",
        next_action="retry",
    )
    h1 = _capsule_stable_hash(capsule)
    h2 = _capsule_stable_hash(capsule)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_capsule_stable_hash_ignores_unstable_fields() -> None:
    """run_id, trace_id, attempt, schema_version must not affect the hash."""
    base = dict(
        reason="insufficient_deliverable_evidence",
        changed_files=["src/foo.py"],
        tools_used=["exec_host"],
        top_errors=[],
        blockers_summary="blocker",
        next_action="retry",
    )
    capsule_a = _build_attempt_capsule(
        run_id="run_A", trace_id="trc_A", attempt=1, **base  # type: ignore[arg-type]
    )
    capsule_b = _build_attempt_capsule(
        run_id="run_B", trace_id="trc_B", attempt=2, **base  # type: ignore[arg-type]
    )
    assert _capsule_stable_hash(capsule_a) == _capsule_stable_hash(capsule_b)


def test_capsule_stable_hash_differs_on_changed_files() -> None:
    base = dict(
        run_id="run_1",
        trace_id="trc_1",
        attempt=1,
        reason="insufficient_deliverable_evidence",
        tools_used=[],
        top_errors=[],
        blockers_summary="",
        next_action="retry",
    )
    c1 = _build_attempt_capsule(changed_files=["src/a.py"], **base)  # type: ignore[arg-type]
    c2 = _build_attempt_capsule(changed_files=["src/b.py"], **base)  # type: ignore[arg-type]
    assert _capsule_stable_hash(c1) != _capsule_stable_hash(c2)


# ---------------------------------------------------------------------------
# get_previous_capsule / save_capsule
# ---------------------------------------------------------------------------


def test_get_previous_capsule_returns_none_when_empty() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        actor_id = ensure_user(conn, "web_admin_capsule_empty")
        run_id = create_feature_build_run(conn, feature_id="bug_capsule_empty", created_by=actor_id)
        result = get_previous_capsule(conn, run_id)
    assert result is None


def test_save_and_get_capsule_round_trips() -> None:
    capsule = _build_attempt_capsule(
        run_id="run_rt",
        trace_id="trc_rt",
        attempt=1,
        reason="insufficient_deliverable_evidence",
        changed_files=["src/x.py"],
        tools_used=["exec_host"],
        top_errors=["err1"],
        blockers_summary="blocked on dep",
        next_action="retry",
    )
    h = _capsule_stable_hash(capsule)
    with get_conn() as conn:
        ensure_system_state(conn)
        actor_id = ensure_user(conn, "web_admin_capsule_rt")
        run_id = create_feature_build_run(conn, feature_id="bug_capsule_rt", created_by=actor_id)
        save_capsule(conn, run_id, capsule, h)
        result = get_previous_capsule(conn, run_id)
    assert result is not None
    assert result["reason"] == "insufficient_deliverable_evidence"
    assert result["changed_files"] == ["src/x.py"]
    assert result["tools_used"] == ["exec_host"]


# ---------------------------------------------------------------------------
# _format_capsule_summary
# ---------------------------------------------------------------------------


def test_format_capsule_summary_basic() -> None:
    capsule = _build_attempt_capsule(
        run_id="run_fmt",
        trace_id="trc_fmt",
        attempt=2,
        reason="insufficient_deliverable_evidence",
        changed_files=["src/a.py", "src/b.py"],
        tools_used=[],
        top_errors=[],
        blockers_summary="No tests passed",
        next_action="retry",
    )
    summary = _format_capsule_summary(capsule)
    assert "[Attempt 2 context]" in summary
    assert "insufficient_deliverable_evidence" in summary
    assert "src/a.py" in summary
    assert "No tests passed" in summary


def test_format_capsule_summary_truncates_many_files() -> None:
    files = [f"src/file{i}.py" for i in range(10)]
    capsule = _build_attempt_capsule(
        run_id="run_fmt2",
        trace_id="trc_fmt2",
        attempt=3,
        reason="insufficient_deliverable_evidence",
        changed_files=files,
        tools_used=[],
        top_errors=[],
        blockers_summary="",
        next_action="retry",
    )
    summary = _format_capsule_summary(capsule)
    assert "+5 more" in summary


# ---------------------------------------------------------------------------
# Repeat fail-fast integration via _apply_capsule_repeat_fail_fast
# ---------------------------------------------------------------------------


def _make_run(conn, uid_suffix: str) -> tuple[str, str]:
    actor_id = ensure_user(conn, f"web_admin_cap_{uid_suffix}")
    run_id = create_feature_build_run(
        conn, feature_id=f"bug_cap_{uid_suffix}", created_by=actor_id
    )
    return actor_id, run_id


def test_repeat_fail_fast_triggers_on_matching_hash(monkeypatch) -> None:
    """Two identical capsule hashes with attempt >= repeat_limit → denied."""
    from jarvis.tasks.agent import _apply_capsule_repeat_fail_fast

    emitted: list[tuple[str, dict]] = []

    def fake_emit(event_type: str, payload: dict) -> None:
        emitted.append((event_type, payload))

    class FakeSettings:
        feature_build_repeat_limit = 2
        feature_build_attempt_capsules_enabled = 1

    with get_conn() as conn:
        ensure_system_state(conn)
        _, run_id = _make_run(conn, "repeat_match")

        # Save a capsule so there is a "previous" one.
        # Use tools_used=[] to match what _collect_tools_used_from_trace returns from an
        # empty test DB (no events inserted for trc_curr).
        prev_capsule = _build_attempt_capsule(
            run_id=run_id,
            trace_id="trc_prev",
            attempt=1,
            reason="insufficient_deliverable_evidence",
            changed_files=[],
            tools_used=[],
            top_errors=[],
            blockers_summary="",
            next_action="retry",
        )
        prev_hash = _capsule_stable_hash(prev_capsule)
        save_capsule(conn, run_id, prev_capsule, prev_hash)

        # Simulate the same outcome on attempt 2.
        gate_checks: dict = {"changed_files": []}
        result = _apply_capsule_repeat_fail_fast(
            conn=conn,
            run_id=run_id,
            trace_id="trc_curr",
            attempt_count=2,
            gate_checks=gate_checks,
            message_id=None,
            settings=FakeSettings(),
            emit_build_event=fake_emit,
            max_attempts=5,
        )

    assert result is True  # denied
    assert any(et == "feature.build.retry.denied" for et, _ in emitted)
    denied_payload = next(p for et, p in emitted if et == "feature.build.retry.denied")
    assert denied_payload["policy_action"] == "repeat_fail_fast"

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, retry_state, terminal_reason "
            "FROM feature_request_build_runs WHERE id=? LIMIT 1",
            (run_id,),
        ).fetchone()
        assert str(row["status"]) == "failed"
        assert str(row["retry_state"]) == "exhausted"
        assert str(row["terminal_reason"]) == "FAILED_REPEAT"


def test_repeat_fail_fast_skips_on_new_hash(monkeypatch) -> None:
    """Different capsule hash → normal retry (returns False)."""
    from jarvis.tasks.agent import _apply_capsule_repeat_fail_fast

    emitted: list[tuple[str, dict]] = []

    class FakeSettings:
        feature_build_repeat_limit = 2
        feature_build_attempt_capsules_enabled = 1

    with get_conn() as conn:
        ensure_system_state(conn)
        _, run_id = _make_run(conn, "new_hash")

        # Save a capsule with one set of changed_files.
        prev_capsule = _build_attempt_capsule(
            run_id=run_id,
            trace_id="trc_prev2",
            attempt=1,
            reason="insufficient_deliverable_evidence",
            changed_files=["src/old.py"],
            tools_used=[],
            top_errors=[],
            blockers_summary="",
            next_action="retry",
        )
        prev_hash = _capsule_stable_hash(prev_capsule)
        save_capsule(conn, run_id, prev_capsule, prev_hash)

        # Current attempt has different changed_files → different hash.
        gate_checks: dict = {"changed_files": ["src/new.py"]}
        result = _apply_capsule_repeat_fail_fast(
            conn=conn,
            run_id=run_id,
            trace_id="trc_curr2",
            attempt_count=2,
            gate_checks=gate_checks,
            message_id=None,
            settings=FakeSettings(),
            emit_build_event=lambda et, p: emitted.append((et, p)),
            max_attempts=5,
        )

    assert result is False  # allowed to retry
    assert any(et == "feature.build.evidence.logged" for et, _ in emitted)


def test_repeat_fail_fast_skips_when_attempt_below_limit() -> None:
    """Even with same hash, if attempt_count < repeat_limit → allowed."""
    from jarvis.tasks.agent import _apply_capsule_repeat_fail_fast

    emitted: list[tuple[str, dict]] = []

    class FakeSettings:
        feature_build_repeat_limit = 3  # higher limit
        feature_build_attempt_capsules_enabled = 1

    with get_conn() as conn:
        ensure_system_state(conn)
        _, run_id = _make_run(conn, "below_limit")

        prev_capsule = _build_attempt_capsule(
            run_id=run_id,
            trace_id="trc_bl_prev",
            attempt=1,
            reason="insufficient_deliverable_evidence",
            changed_files=[],
            tools_used=[],
            top_errors=[],
            blockers_summary="",
            next_action="retry",
        )
        prev_hash = _capsule_stable_hash(prev_capsule)
        save_capsule(conn, run_id, prev_capsule, prev_hash)

        gate_checks: dict = {"changed_files": []}
        result = _apply_capsule_repeat_fail_fast(
            conn=conn,
            run_id=run_id,
            trace_id="trc_bl_curr",
            attempt_count=2,  # less than repeat_limit=3
            gate_checks=gate_checks,
            message_id=None,
            settings=FakeSettings(),
            emit_build_event=lambda et, p: emitted.append((et, p)),
            max_attempts=5,
        )

    assert result is False  # allowed to retry


# ---------------------------------------------------------------------------
# NEEDS_USER_GUIDANCE gate detection
# ---------------------------------------------------------------------------


def test_needs_user_guidance_gate_detects_prefix() -> None:
    """Gate returns (True, 'needs_user_guidance') when message starts with prefix."""
    from jarvis.tasks.agent import _evaluate_feature_build_deliverable_gate

    with get_conn() as conn:
        ensure_system_state(conn)
        actor_id = ensure_user(conn, "web_admin_nug_gate")

        # Insert a thread + message with NEEDS_USER_GUIDANCE prefix.
        from jarvis.db.queries import create_thread, ensure_channel
        from jarvis.ids import new_id

        channel_id = ensure_channel(conn, actor_id, "web")
        thread_id = create_thread(conn, actor_id, channel_id)
        msg_id = new_id("msg")
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) "
            "VALUES(?,?,?,?,datetime('now'))",
            (msg_id, thread_id, "assistant", "NEEDS_USER_GUIDANCE: Which branch should I target?"),
        )

        class FakeSettings:
            ralph_never_edit_paths = ""
            feature_build_loop_cap_threshold = 8

        gate_passed, gate_reason, checks = _evaluate_feature_build_deliverable_gate(
            conn,
            trace_id="trc_nug_gate",
            message_id=msg_id,
            settings=FakeSettings(),
        )

    assert gate_passed is True
    assert gate_reason == "needs_user_guidance"
    assert checks.get("message_is_needs_user_guidance") is True


# ---------------------------------------------------------------------------
# test_gates_executed gate check
# ---------------------------------------------------------------------------


def _insert_exec_host_event(conn, trace_id: str, command: str) -> None:
    """Insert a tool.call.start event for exec_host with the given command."""
    import json as _json

    from jarvis.events.models import EventInput
    from jarvis.events.writer import emit_event
    from jarvis.ids import new_id

    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=None,
            event_type="tool.call.start",
            component="agent",
            actor_type="system",
            actor_id="test",
            payload_json=_json.dumps({"tool": "exec_host", "arguments": {"command": command}}),
            payload_redacted_json=_json.dumps({}),
        ),
    )


def _make_gate_conn_with_message(uid_suffix: str, message_content: str):
    """Return (conn, msg_id) with a committed assistant message."""
    from jarvis.db.queries import create_thread, ensure_channel
    from jarvis.ids import new_id

    with get_conn() as conn:
        ensure_system_state(conn)
        actor_id = ensure_user(conn, f"web_admin_{uid_suffix}")
        channel_id = ensure_channel(conn, actor_id, "web")
        thread_id = create_thread(conn, actor_id, channel_id)
        msg_id = new_id("msg")
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) "
            "VALUES(?,?,?,?,datetime('now'))",
            (msg_id, thread_id, "assistant", message_content),
        )
    return msg_id


def test_gate_fails_when_test_gates_not_in_trace() -> None:
    """allowed_changes present but no test-gates event → test_gates_not_executed."""
    from unittest.mock import patch

    from jarvis.tasks.agent import _evaluate_feature_build_deliverable_gate

    msg_id = _make_gate_conn_with_message("tgne_fail", "RALPH_SUCCESS: implemented the feature")

    class FakeSettings:
        ralph_never_edit_paths = ""
        feature_build_loop_cap_threshold = 8
        feature_build_require_test_gates = 1

    trace_id = "trc_tgne_fail"

    with get_conn() as conn:
        ensure_system_state(conn)
        # No exec_host tool.call.start events inserted → test-gates was never run.
        with (
            patch(
                "jarvis.tasks.agent._git_changed_files",
                return_value=(["src/foo.py"], None),
            ),
            patch(
                "jarvis.tasks.agent.get_attempt_initial_dirty_files",
                return_value=[],
            ),
        ):
            gate_passed, gate_reason, checks = _evaluate_feature_build_deliverable_gate(
                conn,
                trace_id=trace_id,
                message_id=msg_id,
                settings=FakeSettings(),
            )

    assert gate_passed is False
    assert gate_reason == "test_gates_not_executed"
    assert checks.get("test_gates_executed") is False
    assert checks.get("allowed_scope_changes") == ["src/foo.py"]


def test_gate_passes_when_test_gates_in_trace() -> None:
    """allowed_changes present and test-gates event found → gate passes."""
    from unittest.mock import patch

    from jarvis.tasks.agent import _evaluate_feature_build_deliverable_gate

    msg_id = _make_gate_conn_with_message("tgne_pass", "RALPH_SUCCESS: implemented the feature")

    class FakeSettings:
        ralph_never_edit_paths = ""
        feature_build_loop_cap_threshold = 8
        feature_build_require_test_gates = 1

    trace_id = "trc_tgne_pass"

    with get_conn() as conn:
        ensure_system_state(conn)
        # Insert a test-gates exec_host event.
        _insert_exec_host_event(conn, trace_id, "uv run jarvis test-gates --fail-fast")

        with (
            patch(
                "jarvis.tasks.agent._git_changed_files",
                return_value=(["src/foo.py"], None),
            ),
            patch(
                "jarvis.tasks.agent.get_attempt_initial_dirty_files",
                return_value=[],
            ),
        ):
            gate_passed, gate_reason, checks = _evaluate_feature_build_deliverable_gate(
                conn,
                trace_id=trace_id,
                message_id=msg_id,
                settings=FakeSettings(),
            )

    assert gate_passed is True
    assert gate_reason is None
    assert checks.get("test_gates_executed") is True


def test_gate_bypasses_test_gates_check_when_disabled() -> None:
    """feature_build_require_test_gates=0 → passes without test-gates event."""
    from unittest.mock import patch

    from jarvis.tasks.agent import _evaluate_feature_build_deliverable_gate

    msg_id = _make_gate_conn_with_message("tgne_bypass", "RALPH_SUCCESS: doc-only update")

    class FakeSettings:
        ralph_never_edit_paths = ""
        feature_build_loop_cap_threshold = 8
        feature_build_require_test_gates = 0

    trace_id = "trc_tgne_bypass"

    with get_conn() as conn:
        ensure_system_state(conn)
        # No test-gates event inserted, but flag is disabled.
        with (
            patch(
                "jarvis.tasks.agent._git_changed_files",
                return_value=(["docs/README.md"], None),
            ),
            patch(
                "jarvis.tasks.agent.get_attempt_initial_dirty_files",
                return_value=[],
            ),
        ):
            gate_passed, gate_reason, checks = _evaluate_feature_build_deliverable_gate(
                conn,
                trace_id=trace_id,
                message_id=msg_id,
                settings=FakeSettings(),
            )

    assert gate_passed is True
    assert gate_reason is None
    # test_gates_executed key should NOT be present when check is disabled
    assert "test_gates_executed" not in checks


def test_needs_user_guidance_gate_does_not_trigger_on_normal_message() -> None:
    """Gate does not detect NEEDS_USER_GUIDANCE for a normal message."""
    from jarvis.tasks.agent import _evaluate_feature_build_deliverable_gate

    with get_conn() as conn:
        ensure_system_state(conn)
        actor_id = ensure_user(conn, "web_admin_nug_normal")
        from jarvis.db.queries import create_thread, ensure_channel
        from jarvis.ids import new_id

        channel_id = ensure_channel(conn, actor_id, "web")
        thread_id = create_thread(conn, actor_id, channel_id)
        msg_id = new_id("msg")
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) "
            "VALUES(?,?,?,?,datetime('now'))",
            (msg_id, thread_id, "assistant", "RALPH_FAIL: tests failed"),
        )

        class FakeSettings:
            ralph_never_edit_paths = ""
            feature_build_loop_cap_threshold = 8
            feature_build_require_test_gates = 1

        gate_passed, gate_reason, checks = _evaluate_feature_build_deliverable_gate(
            conn,
            trace_id="trc_nug_normal",
            message_id=msg_id,
            settings=FakeSettings(),
        )

    # No NEEDS_USER_GUIDANCE prefix → flag must be False
    assert checks.get("message_is_needs_user_guidance") is False
    # Gate reason must NOT be needs_user_guidance (live git state may affect gate_passed).
    assert gate_reason != "needs_user_guidance"
