from datetime import UTC, datetime, timedelta

import pytest

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_system_state
from jarvis.ids import new_id
from jarvis.tasks.system import watchdog_stall_check


def _insert_event(*, created_at: str, event_type: str) -> None:
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                new_id("evt"),
                new_id("trc"),
                new_id("spn"),
                None,
                "thr_test",
                event_type,
                "channels.whatsapp",
                "user",
                "usr_test",
                "{}",
                "{}",
                created_at,
            ),
        )


def test_watchdog_stall_check_triggers_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    old_ts = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    called: list[str] = []

    monkeypatch.setenv("STALL_DETECT_ENABLED", "1")
    monkeypatch.setenv("STALL_DETECT_THRESHOLD_SECONDS", "30")
    monkeypatch.setenv("STALL_RECOVERY_COOLDOWN_SECONDS", "600")
    get_settings.cache_clear()

    with get_conn() as conn:
        ensure_system_state(conn)
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM messages")

    _insert_event(created_at=old_ts, event_type="channel.inbound")
    def _enqueue_restart(trace_id: str) -> bool:
        called.append(trace_id)
        return True

    monkeypatch.setattr("jarvis.tasks.system.enqueue_restart", _enqueue_restart)

    result = watchdog_stall_check()

    assert result["status"] == "stalled"
    assert result["restart_enqueued"] is True
    assert len(called) == 1
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 AS present FROM events "
            "WHERE event_type='runtime.stall.detected' LIMIT 1"
        ).fetchone()
    assert row is not None


def test_watchdog_stall_check_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STALL_DETECT_ENABLED", "0")
    get_settings.cache_clear()
    result = watchdog_stall_check()
    assert result["status"] == "disabled"
