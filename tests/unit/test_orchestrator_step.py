import asyncio
import sqlite3
from dataclasses import dataclass
from typing import Any

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    ensure_channel,
    ensure_open_thread,
    ensure_system_state,
    ensure_user,
    insert_message,
)
from jarvis.memory.skills import SkillsService
from jarvis.orchestrator.step import MAX_TOOL_ITERATIONS, _enforce_identity_policy, run_agent_step
from jarvis.providers.base import ModelResponse


@dataclass
class _FakeRuntime:
    execute_calls: int = 0

    class _Registry:
        @staticmethod
        def schemas() -> list[dict[str, object]]:
            return [{"name": "echo", "description": "echo"}]

    @property
    def registry(self) -> _Registry:
        return self._Registry()

    async def execute(
        self,
        conn: sqlite3.Connection,
        tool_name: str,
        arguments: dict[str, Any],
        caller_id: str,
        trace_id: str,
        thread_id: str | None = None,
    ) -> dict[str, object]:
        del conn, tool_name, arguments, caller_id, trace_id, thread_id
        self.execute_calls += 1
        return {"ok": True}


class _SequenceRouter:
    def __init__(self, responses: list[tuple[ModelResponse, str]]) -> None:
        self._responses = responses
        self.calls = 0
        self.messages_by_call: list[list[dict[str, str]]] = []

    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        priority: str = "normal",
    ) -> tuple[ModelResponse, str, str | None]:
        del tools, temperature, max_tokens, priority
        self.messages_by_call.append(messages)
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        response, lane = self._responses[idx]
        return response, lane, None


def test_run_agent_step_model_path_with_tool_loop(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    router = _SequenceRouter(
        [
            (
                ModelResponse(
                    text="calling tool",
                    tool_calls=[{"name": "echo", "arguments": {"x": 1}}],
                ),
                "fallback",
            ),
            (ModelResponse(text="final answer", tool_calls=[]), "primary"),
        ]
    )
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "hello")
        message_id = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_1")
        )
        row = conn.execute("SELECT content FROM messages WHERE id=?", (message_id,)).fetchone()
        fallback_row = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE trace_id=? AND event_type='model.fallback'",
            ("trc_step_1",),
        ).fetchone()
    assert row is not None and row["content"] == "final answer"
    assert runtime.execute_calls == 1
    assert fallback_row is not None and int(fallback_row["c"]) == 1


def test_run_agent_step_worker_ignores_command_short_path(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    router = _SequenceRouter([(ModelResponse(text="worker reply", tool_calls=[]), "primary")])
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550124")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "/status")
        message_id = asyncio.run(
            run_agent_step(
                conn,
                router,
                runtime,
                thread_id=thread_id,
                trace_id="trc_step_2",
                actor_id="researcher",
            )
        )
        row = conn.execute("SELECT content FROM messages WHERE id=?", (message_id,)).fetchone()
    assert row is not None and row["content"] == "worker reply"
    assert runtime.execute_calls == 0


def test_run_agent_step_enforces_tool_iteration_cap(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    looping_response = (
        ModelResponse(
            text="loop",
            tool_calls=[{"name": "echo", "arguments": {"a": "b"}}],
        ),
        "primary",
    )
    router = _SequenceRouter([looping_response])
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550125")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "run")
        _ = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_3")
        )
    assert router.calls == MAX_TOOL_ITERATIONS + 1
    assert runtime.execute_calls == MAX_TOOL_ITERATIONS


def test_run_agent_step_strips_ai_identity_phrases(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    router = _SequenceRouter(
        [(ModelResponse(text="As an AI, I can help with deployment.", tool_calls=[]), "primary")]
    )
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550127")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "help me deploy")
        message_id = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_4")
        )
        row = conn.execute("SELECT content FROM messages WHERE id=?", (message_id,)).fetchone()
    assert row is not None
    text = str(row["content"]).lower()
    assert "as an ai" not in text
    assert "language model" not in text


def test_enforce_identity_policy_strips_unicode_hyphen_model_identity() -> None:
    text = (
        "If you’re curious about when the underlying model was made publicly available, "
        "the GPT‑4 architecture that powers me was released in June 2023."
    )
    cleaned = _enforce_identity_policy(text).lower()
    assert "gpt" not in cleaned
    assert "powers me" not in cleaned


def test_enforce_identity_policy_strips_software_identity_claims() -> None:
    text = (
        "I don’t have a birthday in the human sense—I’m a piece of software that was "
        "released publicly in June 2023."
    )
    cleaned = _enforce_identity_policy(text).lower()
    assert "piece of software" not in cleaned
    assert "released publicly" not in cleaned


def test_run_agent_step_uses_latest_user_message_for_command_check(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    router = _SequenceRouter([(ModelResponse(text="normal reply", tool_calls=[]), "primary")])
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550128")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "/status")
        insert_message(conn, thread_id, "assistant", "prior reply")
        insert_message(conn, thread_id, "user", "hello")
        message_id = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_5")
        )
        row = conn.execute("SELECT content FROM messages WHERE id=?", (message_id,)).fetchone()
    assert row is not None
    assert row["content"] == "normal reply"


def test_run_agent_step_includes_skills_and_environment_context(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    monkeypatch.setattr(
        "jarvis.orchestrator.step._build_environment_context",
        lambda _conn: "Current time: 2026-02-15T14:30:00+00:00",
    )
    captured: dict[str, object] = {}

    def _fake_build_prompt_with_report(
        system_context: str,
        summary_short: str,
        summary_long: str,
        memory_chunks: list[str],
        tail: list[str],
        token_budget: int,
        max_memory_items: int = 6,
        prompt_mode: str = "full",
        available_tools: list[dict[str, str]] | None = None,
        skill_catalog: list[dict[str, object]] | None = None,
    ) -> tuple[str, str, dict[str, object]]:
        del summary_short, summary_long, tail, token_budget, max_memory_items
        captured["system_context"] = system_context
        captured["memory_chunks"] = memory_chunks
        captured["prompt_mode"] = prompt_mode
        captured["available_tools"] = available_tools
        captured["skill_catalog"] = skill_catalog
        return system_context, "prompt", {"sections": {}}

    monkeypatch.setattr(
        "jarvis.orchestrator.step.build_prompt_with_report", _fake_build_prompt_with_report
    )
    router = _SequenceRouter([(ModelResponse(text="done", tool_calls=[]), "primary")])
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        SkillsService().put(
            conn,
            slug="jarvis-project",
            title="Jarvis Project",
            content="Pinned project context",
            scope="global",
            pinned=True,
            source="seed",
        )
        SkillsService().put(
            conn,
            slug="deploy-checklist",
            title="Deploy Checklist",
            content="Use migration checklist before deploy.",
            scope="global",
            pinned=False,
            source="agent",
        )
        user_id = ensure_user(conn, "15555550129")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "deploy checklist")
        _ = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_6")
        )

    assert "[environment]" in str(captured["system_context"])
    assert "Current time: 2026-02-15T14:30:00+00:00" in str(captured["system_context"])
    chunks = captured["memory_chunks"]
    assert isinstance(chunks, list)
    assert all("[skill:" not in str(item) for item in chunks)
    skills = captured["skill_catalog"]
    assert isinstance(skills, list)
    assert any(str(item.get("slug", "")) == "jarvis-project" for item in skills)
    assert any(str(item.get("slug", "")) == "deploy-checklist" for item in skills)
    assert captured["prompt_mode"] == "full"


def test_run_agent_step_sends_system_message(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    router = _SequenceRouter([(ModelResponse(text="done", tool_calls=[]), "primary")])
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550130")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "hello")
        _ = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_7")
        )
    assert router.messages_by_call
    first_call = router.messages_by_call[0]
    assert first_call[0]["role"] == "system"
    assert first_call[1]["role"] == "user"


def test_run_agent_step_emits_prompt_build_event(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    router = _SequenceRouter([(ModelResponse(text="done", tool_calls=[]), "primary")])
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550131")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "hello")
        _ = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_8")
        )
        row = conn.execute(
            "SELECT payload_json FROM events WHERE trace_id=? AND event_type='prompt.build' "
            "ORDER BY created_at DESC LIMIT 1",
            ("trc_step_8",),
        ).fetchone()
    assert row is not None
    payload = row["payload_json"]
    assert isinstance(payload, str)
    assert "prompt_mode" in payload
