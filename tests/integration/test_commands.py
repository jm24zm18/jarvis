import json
import os

import pytest

from jarvis.commands.service import maybe_execute_command
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    ensure_channel,
    ensure_open_thread,
    ensure_system_state,
    ensure_user,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event
from jarvis.providers.base import ModelResponse
from jarvis.providers.router import ProviderRouter
from jarvis.providers.sglang import SGLangProvider


class StubProvider:
    async def generate(  # type: ignore[no-untyped-def]
        self,
        messages,
        tools=None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ModelResponse:
        del messages, tools, temperature, max_tokens
        return ModelResponse(text="ok", tool_calls=[])

    async def health_check(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_status_command_returns_json() -> None:
    from datetime import UTC, datetime

    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, "
                "created_at, last_run_at, max_catchup"
                ") VALUES(?,?,?,?,?,?,?,?)"
            ),
            (
                "sch_status_1",
                thread_id,
                "@every:60",
                '{"trace_id":"trc_status"}',
                1,
                datetime(2026, 2, 15, 12, 0, tzinfo=UTC).isoformat(),
                datetime(2026, 2, 15, 12, 0, tzinfo=UTC).isoformat(),
                1,
            ),
        )
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))
        result = await maybe_execute_command(
            conn,
            thread_id,
            "/status",
            "15555550123",
            router,
            {"15555550123"},
        )
    assert result is not None
    parsed = json.loads(result)
    assert "providers" in parsed
    assert "scheduler" in parsed
    assert "dispatchable_total" in parsed["scheduler"]


@pytest.mark.asyncio
async def test_logs_trace_command_returns_ordered_events() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        emit_event(
            conn,
            EventInput(
                trace_id="trace_x",
                span_id="s1",
                parent_span_id=None,
                thread_id=None,
                event_type="first",
                component="tests",
                actor_type="system",
                actor_id="pytest",
                payload_json="{}",
                payload_redacted_json="{}",
            ),
        )
        emit_event(
            conn,
            EventInput(
                trace_id="trace_x",
                span_id="s2",
                parent_span_id="s1",
                thread_id=None,
                event_type="second",
                component="tests",
                actor_type="system",
                actor_id="pytest",
                payload_json="{}",
                payload_redacted_json="{}",
            ),
        )

        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))
        result = await maybe_execute_command(
            conn,
            thread_id,
            "/logs trace trace_x",
            "15555550123",
            router,
            {"15555550123"},
        )

    assert result is not None
    parsed = json.loads(result)
    assert parsed["trace_id"] == "trace_x"
    assert len(parsed["events"]) >= 2


@pytest.mark.asyncio
async def test_restart_requires_admin() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))

        denied = await maybe_execute_command(
            conn,
            thread_id,
            "/restart",
            "15555550123",
            router,
            set(),
        )
        allowed = await maybe_execute_command(
            conn,
            thread_id,
            "/restart",
            "15555550123",
            router,
            {"15555550123"},
        )

    assert denied == "admin required"
    assert allowed == "restart flag set"


@pytest.mark.asyncio
async def test_logs_search_command_returns_matches() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        emit_event(
            conn,
            EventInput(
                trace_id="trace_search",
                span_id="s_search_1",
                parent_span_id=None,
                thread_id=None,
                event_type="channel.inbound",
                component="tests",
                actor_type="system",
                actor_id="pytest",
                payload_json='{"text":"alpha hello world"}',
                payload_redacted_json='{"text":"alpha hello world"}',
            ),
        )
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))
        result = await maybe_execute_command(
            conn,
            thread_id,
            "/logs search hello",
            "15555550123",
            router,
            {"15555550123"},
        )
    assert result is not None
    parsed = json.loads(result)
    assert parsed["query"] == "hello"
    assert len(parsed["events"]) >= 1


@pytest.mark.asyncio
async def test_unlock_requires_admin_and_correct_code(tmp_path) -> None:
    unlock_file = tmp_path / "admin_unlock_code"
    unlock_file.write_text("123456")
    os.environ["ADMIN_UNLOCK_CODE_PATH"] = str(unlock_file)

    from jarvis.config import get_settings

    get_settings.cache_clear()
    try:
        with get_conn() as conn:
            ensure_system_state(conn)
            conn.execute("UPDATE system_state SET lockdown=1 WHERE id='singleton'")
            user_id = ensure_user(conn, "15555550123")
            channel_id = ensure_channel(conn, user_id, "whatsapp")
            thread_id = ensure_open_thread(conn, user_id, channel_id)
            router = ProviderRouter(StubProvider(), SGLangProvider("f"))

            denied = await maybe_execute_command(
                conn,
                thread_id,
                "/unlock 123456",
                "15555550123",
                router,
                set(),
            )
            invalid = await maybe_execute_command(
                conn,
                thread_id,
                "/unlock 999999",
                "15555550123",
                router,
                {"15555550123"},
            )
            allowed = await maybe_execute_command(
                conn,
                thread_id,
                "/unlock 123456",
                "15555550123",
                router,
                {"15555550123"},
            )
            state = conn.execute(
                "SELECT lockdown FROM system_state WHERE id='singleton'"
            ).fetchone()
        assert denied == "admin required"
        assert invalid == "invalid unlock code"
        assert allowed == "lockdown cleared"
        assert state is not None and int(state["lockdown"]) == 0
        assert unlock_file.read_text() == ""
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_approve_command_requires_admin_and_inserts_record() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))

        denied = await maybe_execute_command(
            conn,
            thread_id,
            "/approve host.exec.sudo",
            "15555550123",
            router,
            set(),
        )
        allowed = await maybe_execute_command(
            conn,
            thread_id,
            "/approve host.exec.sudo",
            "15555550123",
            router,
            {"15555550123"},
        )
        row = conn.execute(
            "SELECT action, status FROM approvals ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    assert denied == "admin required"
    assert allowed == "approval created: host.exec.sudo"
    assert row is not None
    assert row["action"] == "host.exec.sudo"
    assert row["status"] == "approved"


@pytest.mark.asyncio
async def test_approve_command_rejects_unknown_action() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))
        result = await maybe_execute_command(
            conn,
            thread_id,
            "/approve something.else",
            "15555550123",
            router,
            {"15555550123"},
        )
    assert result == "invalid action"


@pytest.mark.asyncio
async def test_wa_review_list_requires_admin() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))
        denied = await maybe_execute_command(
            conn,
            thread_id,
            "/wa-review list",
            "15555550123",
            router,
            set(),
        )
        allowed = await maybe_execute_command(
            conn,
            thread_id,
            "/wa-review list",
            "15555550123",
            router,
            {"15555550123"},
        )
    assert denied == "admin required"
    assert allowed is not None
    parsed = json.loads(allowed)
    assert parsed["status"] == "open"


@pytest.mark.asyncio
async def test_wa_review_allow_updates_queue_row() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        conn.execute(
            (
                "INSERT OR REPLACE INTO whatsapp_sender_review_queue("
                "id, instance, sender_jid, remote_jid, participant_jid, "
                "thread_id, external_msg_id, "
                "reason, status, reviewer_id, resolution_note, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "sch_review_cmd_1",
                "personal",
                "15555559004",
                "15555559004",
                "",
                thread_id,
                "wamid.TEST.CMD.REVIEW.1",
                "unknown_sender",
                "open",
                None,
                None,
                "2026-02-19T00:00:00+00:00",
                "2026-02-19T00:00:00+00:00",
            ),
        )
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))
        result = await maybe_execute_command(
            conn,
            thread_id,
            "/wa-review allow sch_review_cmd_1 trusted",
            "15555550123",
            router,
            {"15555550123"},
        )
        row = conn.execute(
            "SELECT status, resolution_note FROM whatsapp_sender_review_queue WHERE id=?",
            ("sch_review_cmd_1",),
        ).fetchone()
    assert result == "review decision saved: sch_review_cmd_1 -> allowed"
    assert row is not None
    assert str(row["status"]) == "allowed"
    assert "trusted" in str(row["resolution_note"])


@pytest.mark.asyncio
async def test_new_command_closes_current_and_creates_next_thread() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))
        result = await maybe_execute_command(
            conn,
            thread_id,
            "/new",
            "15555550123",
            router,
            {"15555550123"},
        )
        old_row = conn.execute("SELECT status FROM threads WHERE id=?", (thread_id,)).fetchone()
        open_rows = conn.execute(
            "SELECT id FROM threads WHERE user_id=? AND channel_id=? AND status='open'",
            (user_id, channel_id),
        ).fetchall()

    assert result is not None
    assert result.startswith("new thread created:")
    assert old_row is not None and old_row["status"] == "closed"
    assert len(open_rows) == 1
    assert str(open_rows[0]["id"]) != thread_id


@pytest.mark.asyncio
async def test_kb_add_search_and_get_commands() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550900")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))

        added = await maybe_execute_command(
            conn,
            thread_id,
            "/kb add deployment-runbook :: restart with /restart after backup",
            "15555550900",
            router,
            {"15555550900"},
        )
        searched = await maybe_execute_command(
            conn,
            thread_id,
            "/kb search restart backup",
            "15555550900",
            router,
            {"15555550900"},
        )
        listed = await maybe_execute_command(
            conn,
            thread_id,
            "/kb list 5",
            "15555550900",
            router,
            {"15555550900"},
        )

    assert added is not None
    assert "saved kb doc:" in added
    assert searched is not None
    parsed_search = json.loads(searched)
    assert parsed_search["items"]
    assert "restart" in parsed_search["items"][0]["content"]
    assert listed is not None
    parsed_list = json.loads(listed)
    assert parsed_list["items"]


@pytest.mark.asyncio
async def test_compact_command_enqueues_task(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, dict[str, str], str]] = []

    def _send_task(name: str, kwargs: dict[str, str], queue: str) -> bool:
        captured.append((name, kwargs, queue))
        return True

    monkeypatch.setattr("jarvis.commands.service._send_task", _send_task)

    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))
        result = await maybe_execute_command(
            conn,
            thread_id,
            "/compact",
            "15555550123",
            router,
            {"15555550123"},
        )

    assert result == "compaction enqueued"
    assert len(captured) == 1
    assert captured[0][0] == "jarvis.tasks.memory.compact_thread"
    assert captured[0][1]["thread_id"] == thread_id
    assert captured[0][2] == "tools_io"


@pytest.mark.asyncio
async def test_verbose_command_updates_thread_setting() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))
        result = await maybe_execute_command(
            conn,
            thread_id,
            "/verbose on",
            "15555550123",
            router,
            {"15555550123"},
        )
        row = conn.execute(
            "SELECT verbose FROM thread_settings WHERE thread_id=?",
            (thread_id,),
        ).fetchone()

    assert result == "verbose set to on"
    assert row is not None and int(row["verbose"]) == 1


@pytest.mark.asyncio
async def test_group_command_uses_existing_state_and_keeps_main() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        conn.execute(
            "INSERT INTO thread_settings(thread_id, verbose, active_agent_ids_json, updated_at) "
            "VALUES(?,?,?,datetime('now'))",
            (thread_id, 0, '["main","planner"]'),
        )
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))
        first = await maybe_execute_command(
            conn,
            thread_id,
            "/group on researcher",
            "15555550123",
            router,
            {"15555550123"},
        )
        second = await maybe_execute_command(
            conn,
            thread_id,
            "/group off main",
            "15555550123",
            router,
            {"15555550123"},
        )
        row = conn.execute(
            "SELECT active_agent_ids_json FROM thread_settings WHERE thread_id=?",
            (thread_id,),
        ).fetchone()

    assert first is not None and "researcher" in first
    assert second == "cannot disable main agent"
    assert row is not None
    assert "planner" in str(row["active_agent_ids_json"])
    assert "researcher" in str(row["active_agent_ids_json"])


@pytest.mark.asyncio
async def test_onboarding_reset_command_clears_state(monkeypatch) -> None:
    async def _fake_start_onboarding_prompt(*_args, **_kwargs) -> str:
        return "What should I call your assistant?"

    monkeypatch.setattr(
        "jarvis.commands.service.start_onboarding_prompt",
        _fake_start_onboarding_prompt,
    )

    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550126")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        conn.execute(
            (
                "INSERT INTO onboarding_states("
                "user_id, thread_id, status, step, answers_json, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                user_id,
                thread_id,
                "in_progress",
                2,
                '{"assistant_name":"Jarvis"}',
                "2026-02-15T12:00:00+00:00",
                "2026-02-15T12:00:00+00:00",
            ),
        )
        router = ProviderRouter(StubProvider(), SGLangProvider("f"))
        result = await maybe_execute_command(
            conn,
            thread_id,
            "/onboarding reset",
            "15555550126",
            router,
            {"15555550126"},
        )
        row = conn.execute(
            (
                "SELECT user_id, thread_id, status, step, answers_json "
                "FROM onboarding_states WHERE user_id=?"
            ),
            (user_id,),
        ).fetchone()

    assert result is not None
    assert "onboarding reset" in result.lower()
    assert "what should i call your assistant" in result.lower()
    assert row is not None
    assert row["user_id"] == user_id
    assert row["thread_id"] == thread_id
    assert row["status"] == "required"
    assert row["step"] == 0
    assert row["answers_json"] == "{}"
