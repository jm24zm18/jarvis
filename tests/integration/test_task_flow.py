from datetime import UTC, datetime

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    ensure_channel,
    ensure_open_thread,
    ensure_system_state,
    ensure_user,
    insert_message,
)
from jarvis.tasks.agent import agent_step
from jarvis.tasks.scheduler import scheduler_tick


def test_scheduler_tick_and_agent_step_flow(monkeypatch) -> None:
    enqueued_from_scheduler: list[dict[str, str]] = []
    enqueued_from_agent: list[dict[str, str]] = []

    def _send_task(name: str, kwargs: dict[str, str], queue: str) -> None:
        if name == "jarvis.tasks.agent.agent_step" and queue == "agent_priority":
            enqueued_from_scheduler.append(kwargs)
        if name in (
            "jarvis.tasks.channel.send_whatsapp_message",
            "jarvis.tasks.channel.send_channel_message",
        ) and queue == "tools_io":
            enqueued_from_agent.append(kwargs)

    monkeypatch.setattr("jarvis.tasks.scheduler._send_task", _send_task)

    class _Runner:
        def send_task(self, name: str, kwargs: dict[str, str], queue: str) -> bool:
            if name in (
                "jarvis.tasks.channel.send_whatsapp_message",
                "jarvis.tasks.channel.send_channel_message",
            ) and queue == "tools_io":
                enqueued_from_agent.append(kwargs)
            return True

    monkeypatch.setattr("jarvis.tasks.agent.get_task_runner", lambda: _Runner())

    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "/status")
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, created_at"
                ") VALUES(?,?,?,?,?,?)"
            ),
            (
                "sch_taskflow_1",
                thread_id,
                "@every:60",
                '{"trace_id":"trc_task_flow"}',
                1,
                datetime(2026, 2, 15, 12, 0, tzinfo=UTC).isoformat(),
            ),
        )

    result = scheduler_tick()
    assert result["ok"] is True
    assert int(result["dispatched"]) >= 1
    assert len(enqueued_from_scheduler) >= 1

    payload = enqueued_from_scheduler[0]
    message_id = agent_step(trace_id=payload["trace_id"], thread_id=payload["thread_id"])
    assert message_id.startswith("msg_")
    assert len(enqueued_from_agent) == 1
    assert enqueued_from_agent[0]["thread_id"] == payload["thread_id"]
    assert enqueued_from_agent[0]["message_id"] == message_id
