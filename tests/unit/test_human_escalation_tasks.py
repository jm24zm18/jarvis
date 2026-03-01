from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.tasks.human_escalation import request_human_escalation


class _FakeRunner:
    def send_task(self, _name: str, kwargs: dict | None = None, queue: str | None = None) -> bool:
        del kwargs, queue
        return True


def test_request_human_escalation_dispatches_to_configured_target(monkeypatch) -> None:
    monkeypatch.setenv("HUMAN_ESCALATION_CHANNEL_TYPE", "whatsapp")
    monkeypatch.setenv("HUMAN_ESCALATION_TARGETS", "15551234567@s.whatsapp.net")
    get_settings.cache_clear()
    monkeypatch.setattr("jarvis.tasks.human_escalation.get_task_runner", lambda: _FakeRunner())

    result = request_human_escalation(
        thread_id="thr_source",
        trace_id="trc_source",
        requested_by_actor_id="main",
        source_agent_id="main",
        reason="blocked_by_missing_input",
        message="Need approval to proceed with production rollout.",
        priority="high",
    )
    assert result["ok"] is True
    assert int(result["count"]) == 1

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, channel_type, target_external_id, dispatched_message_id "
            "FROM human_escalations WHERE trace_id='trc_source' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert str(row["status"]) == "dispatched"
        assert str(row["channel_type"]) == "whatsapp"
        assert str(row["target_external_id"]) == "15551234567@s.whatsapp.net"
        assert str(row["dispatched_message_id"]).startswith("msg_")


def test_request_human_escalation_requires_targets(monkeypatch) -> None:
    monkeypatch.setenv("HUMAN_ESCALATION_CHANNEL_TYPE", "whatsapp")
    monkeypatch.setenv("HUMAN_ESCALATION_TARGETS", "")
    get_settings.cache_clear()
    monkeypatch.setattr("jarvis.tasks.human_escalation.get_task_runner", lambda: _FakeRunner())

    result = request_human_escalation(
        thread_id="thr_source",
        trace_id="trc_missing_target",
        requested_by_actor_id="main",
        source_agent_id="main",
        reason="needs_human",
        message="No target should produce a deterministic error.",
    )
    assert result["ok"] is False
    assert "not configured" in str(result["error"])
