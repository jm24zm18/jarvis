import asyncio
import json
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
from jarvis.errors import ProviderError
from jarvis.memory.skills import SkillsService
from jarvis.orchestrator.step import (
    DEGRADED_RESPONSE,
    MAX_TOOL_ITERATIONS,
    _enforce_identity_policy,
    _extract_embedded_tool_payload,
    _extract_primary_failure_fields,
    _get_thread_compaction_threshold,
    _load_agent_context,
    run_agent_step,
)
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


class _FailingProviderRouter:
    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        priority: str = "normal",
    ) -> tuple[ModelResponse, str, str | None]:
        del messages, tools, temperature, max_tokens, priority
        raise ProviderError(
            "all providers failed: primary=ConnectError: temporary failure in name resolution, "
            "fallback=ConnectError: [Errno -2] Name or service not known",
            retryable=False,
        )


class _ToolLoopThenSynthesisRouter:
    def __init__(self, synthesis_text: str = "terminal synthesis answer") -> None:
        self.calls = 0
        self.synthesis_text = synthesis_text

    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        priority: str = "normal",
    ) -> tuple[ModelResponse, str, str | None]:
        del messages, temperature, max_tokens, priority
        self.calls += 1
        if tools is None:
            return ModelResponse(text=self.synthesis_text, tool_calls=[]), "primary", None
        return (
            ModelResponse(
                text="I can help with that.",
                tool_calls=[{"name": "echo", "arguments": {"x": 1}}],
            ),
            "primary",
            None,
        )


class _ToolLoopThenSynthesisErrorRouter:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        priority: str = "normal",
    ) -> tuple[ModelResponse, str, str | None]:
        del messages, temperature, max_tokens, priority
        self.calls += 1
        if tools is None:
            raise ProviderError("all providers failed: fallback timeout", retryable=True)
        return (
            ModelResponse(
                text="I can help with that.",
                tool_calls=[{"name": "echo", "arguments": {"x": 1}}],
            ),
            "primary",
            None,
        )


class _ToolLoopThenSynthesisPlaceholderRouter:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        priority: str = "normal",
    ) -> tuple[ModelResponse, str, str | None]:
        del messages, temperature, max_tokens, priority
        self.calls += 1
        if tools is None:
            return ModelResponse(text="I can help with that.", tool_calls=[]), "primary", None
        return (
            ModelResponse(
                text="I can help with that.",
                tool_calls=[{"name": "echo", "arguments": {"x": 1}}],
            ),
            "primary",
            None,
        )


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
        thought_rows = conn.execute(
            "SELECT payload_json FROM events WHERE trace_id=? AND event_type='agent.thought' "
            "ORDER BY created_at ASC",
            ("trc_step_1",),
        ).fetchall()
    assert row is not None and row["content"] == "final answer"
    assert runtime.execute_calls == 1
    assert fallback_row is not None and int(fallback_row["c"]) == 1
    assert len(thought_rows) >= 2


def test_run_agent_step_prefers_provider_reasoning_for_thought_payload(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    router = _SequenceRouter(
        [
            (
                ModelResponse(
                    text="final answer",
                    tool_calls=[],
                    reasoning_text="reasoning trail",
                    reasoning_parts=[{"text": "reasoning trail"}],
                ),
                "primary",
            )
        ]
    )
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550126")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "hello")
        _ = asyncio.run(
            run_agent_step(
                conn,
                router,
                runtime,
                thread_id=thread_id,
                trace_id="trc_step_reasoning",
            )
        )
        thought_row = conn.execute(
            "SELECT payload_json FROM events WHERE trace_id=? AND event_type='agent.thought' "
            "ORDER BY created_at ASC LIMIT 1",
            ("trc_step_reasoning",),
        ).fetchone()
    assert thought_row is not None
    payload = json.loads(str(thought_row["payload_json"]))
    assert payload["text"] == "reasoning trail"
    assert payload["thought_source"] == "provider_reasoning"
    assert payload["reasoning_parts"] == [{"text": "reasoning trail"}]


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
        row = conn.execute(
            "SELECT role, content FROM messages WHERE id=?",
            (message_id,),
        ).fetchone()
    assert row is not None and row["content"] == "worker reply"
    assert row["role"] == "agent"
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
    assert router.calls == MAX_TOOL_ITERATIONS + 2
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
        structured_state: str,
        memory_chunks: list[str],
        tail: list[str],
        token_budget: int,
        max_memory_items: int = 6,
        prompt_mode: str = "full",
        available_tools: list[dict[str, str]] | None = None,
        skill_catalog: list[dict[str, object]] | None = None,
    ) -> tuple[str, str, dict[str, object]]:
        del summary_short, summary_long, structured_state, tail, token_budget, max_memory_items
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


def test_extract_embedded_tool_payload_strips_tool_json_suffix() -> None:
    text = (
        'I will inspect docs and propose a plan. '
        '{"tool_calls":[{"name":"echo","arguments":{"x":1}}]}'
    )
    cleaned, tool_calls = _extract_embedded_tool_payload(text)
    assert cleaned == "I will inspect docs and propose a plan."
    assert tool_calls == [{"name": "echo", "arguments": {"x": 1}}]


def test_run_agent_step_parses_embedded_tool_calls_from_text(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    router = _SequenceRouter(
        [
            (
                ModelResponse(
                    text='Planning now {"tool_calls":[{"name":"echo","arguments":{"x":1}}]}',
                    tool_calls=[],
                ),
                "primary",
            ),
            (ModelResponse(text="done", tool_calls=[]), "primary"),
        ]
    )
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550132")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "build feature X")
        message_id = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_9")
        )
        row = conn.execute("SELECT content FROM messages WHERE id=?", (message_id,)).fetchone()
    assert row is not None and row["content"] == "done"
    assert runtime.execute_calls == 1


def test_run_agent_step_rewrites_placeholder_to_degraded_response(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    router = _SequenceRouter([(ModelResponse(text="I am an AI.", tool_calls=[]), "primary")])
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550133")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "status")
        message_id = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_10")
        )
        row = conn.execute("SELECT content FROM messages WHERE id=?", (message_id,)).fetchone()
        evt = conn.execute(
            (
                "SELECT COUNT(*) AS c FROM events WHERE trace_id=? "
                "AND event_type='agent.response.degraded'"
            ),
            ("trc_step_10",),
        ).fetchone()
    assert row is not None
    assert row["content"] == DEGRADED_RESPONSE
    assert evt is not None and int(evt["c"]) == 1


def test_run_agent_step_fallback_only_retry_recovers_response(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    router = _SequenceRouter(
        [
            (ModelResponse(text="I can help with that.", tool_calls=[]), "fallback"),
            (
                ModelResponse(
                    text="Recovered answer after fallback retry.",
                    tool_calls=[],
                ),
                "fallback",
            ),
        ]
    )
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550134")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "retry this")
        message_id = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_11")
        )
        row = conn.execute("SELECT content FROM messages WHERE id=?", (message_id,)).fetchone()
    assert row is not None
    assert row["content"] == "Recovered answer after fallback retry."
    assert runtime.execute_calls == 0
    assert router.calls == 2


def test_run_agent_step_tool_loop_exhaustion_runs_terminal_synthesis(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    monkeypatch.setattr("jarvis.orchestrator.step._enqueue_memory_index", lambda **_kwargs: None)
    monkeypatch.setattr("jarvis.events.writer.MemoryService.embed_text", lambda _self, _text: [0.0])
    monkeypatch.setattr(
        "jarvis.events.writer.MemoryService.upsert_event_vector",
        lambda _self, _conn, _event_id, _thread_id, _vector: None,
    )
    router = _ToolLoopThenSynthesisRouter("Recovered terminal synthesis answer.")
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550137")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "build loop")
        message_id = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_13")
        )
        row = conn.execute("SELECT content FROM messages WHERE id=?", (message_id,)).fetchone()
        evt = conn.execute(
            (
                "SELECT COUNT(*) AS c FROM events WHERE trace_id=? "
                "AND event_type='agent.response.degraded'"
            ),
            ("trc_step_13",),
        ).fetchone()
    assert row is not None
    assert row["content"] == "Recovered terminal synthesis answer."
    assert evt is not None and int(evt["c"]) == 0
    assert runtime.execute_calls == MAX_TOOL_ITERATIONS
    assert router.calls == MAX_TOOL_ITERATIONS + 2


def test_run_agent_step_terminal_synthesis_provider_error_sets_specific_reason(
    monkeypatch,
) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    monkeypatch.setattr("jarvis.orchestrator.step._enqueue_memory_index", lambda **_kwargs: None)
    monkeypatch.setattr("jarvis.events.writer.MemoryService.embed_text", lambda _self, _text: [0.0])
    monkeypatch.setattr(
        "jarvis.events.writer.MemoryService.upsert_event_vector",
        lambda _self, _conn, _event_id, _thread_id, _vector: None,
    )
    router = _ToolLoopThenSynthesisErrorRouter()
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550138")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "build loop error")
        message_id = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_14")
        )
        row = conn.execute("SELECT content FROM messages WHERE id=?", (message_id,)).fetchone()
        degraded_evt = conn.execute(
            (
                "SELECT payload_json FROM events WHERE trace_id=? "
                "AND event_type='agent.response.degraded' ORDER BY created_at DESC LIMIT 1"
            ),
            ("trc_step_14",),
        ).fetchone()
    assert row is not None
    assert row["content"] == DEGRADED_RESPONSE
    assert degraded_evt is not None
    payload = json.loads(str(degraded_evt["payload_json"]))
    assert payload["reason"] == "provider_error_terminal_synthesis"
    assert runtime.execute_calls == MAX_TOOL_ITERATIONS


def test_run_agent_step_tool_loop_placeholder_uses_deterministic_terminal_message(
    monkeypatch,
) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    monkeypatch.setattr("jarvis.orchestrator.step._enqueue_memory_index", lambda **_kwargs: None)
    monkeypatch.setattr("jarvis.events.writer.MemoryService.embed_text", lambda _self, _text: [0.0])
    monkeypatch.setattr(
        "jarvis.events.writer.MemoryService.upsert_event_vector",
        lambda _self, _conn, _event_id, _thread_id, _vector: None,
    )
    router = _ToolLoopThenSynthesisPlaceholderRouter()
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550139")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "build loop placeholder")
        message_id = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_15")
        )
        row = conn.execute("SELECT content FROM messages WHERE id=?", (message_id,)).fetchone()
        degraded_evt = conn.execute(
            (
                "SELECT payload_json FROM events WHERE trace_id=? "
                "AND event_type='agent.response.degraded' ORDER BY created_at DESC LIMIT 1"
            ),
            ("trc_step_15",),
        ).fetchone()
    assert row is not None
    assert "I completed tool execution but could not synthesize a final summary." in str(
        row["content"]
    )
    assert "Trace: trc_step_15." in str(row["content"])
    assert degraded_evt is not None
    payload = json.loads(str(degraded_evt["payload_json"]))
    assert payload["reason"] == "placeholder_response_after_tool_loop"


def test_extract_primary_failure_fields_parses_retry_and_request_id() -> None:
    payload = _extract_primary_failure_fields(
        "Quota exceeded 429 retry-after 2.5 req_abc123"
    )
    assert payload["primary_failure_kind"] == "quota_retryable"
    assert payload["primary_status_code"] == 429
    assert payload["primary_retry_seconds"] == 2
    assert payload["primary_request_id"] == "req_abc123"


def test_extract_primary_failure_fields_classifies_dns_and_transport() -> None:
    dns_payload = _extract_primary_failure_fields(
        "ConnectError: temporary failure in name resolution"
    )
    transport_payload = _extract_primary_failure_fields(
        "ConnectError: failed to establish a new connection: connection refused"
    )
    assert dns_payload["primary_failure_kind"] == "dns_resolution"
    assert transport_payload["primary_failure_kind"] == "transport_unavailable"


def test_run_agent_step_provider_failure_writes_degraded_message_and_error_event(
    monkeypatch,
) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    runtime = _FakeRuntime()
    router = _FailingProviderRouter()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550135")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "hello")
        message_id = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_12")
        )
        message_row = conn.execute(
            "SELECT content FROM messages WHERE id=?",
            (message_id,),
        ).fetchone()
        event_row = conn.execute(
            (
                "SELECT payload_json FROM events WHERE trace_id=? "
                "AND event_type='model.run.error' ORDER BY created_at DESC LIMIT 1"
            ),
            ("trc_step_12",),
        ).fetchone()
    assert message_row is not None
    assert message_row["content"] == DEGRADED_RESPONSE
    assert event_row is not None
    payload = json.loads(str(event_row["payload_json"]))
    assert payload["primary_failure_kind"] == "dns_resolution"


def test_load_agent_context_falls_back_to_files(monkeypatch, tmp_path) -> None:
    bundle_dir = tmp_path / "agents" / "tester"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "identity.md").write_text("# id", encoding="utf-8")
    (bundle_dir / "soul.md").write_text("# soul", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "jarvis.orchestrator.step.load_agent_bundle_cached",
        lambda _path: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert _load_agent_context("tester") == "# id\n\n# soul"


def test_get_thread_compaction_threshold_ignores_non_positive_values() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550999")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        conn.execute(
            (
                "INSERT INTO thread_settings("
                "thread_id, verbose, active_agent_ids_json, compaction_threshold, updated_at"
                ") VALUES(?,?,?,?,datetime('now'))"
            ),
            (thread_id, 0, "[]", 0),
        )
        assert _get_thread_compaction_threshold(conn, thread_id, default=12) == 12


class _FailingRuntime(_FakeRuntime):
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
        raise RuntimeError("tool failed")


def test_run_agent_step_emits_tool_error_notification(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    router = _SequenceRouter(
        [
            (
                ModelResponse(
                    text="",
                    tool_calls=[{"name": "echo", "arguments": {"a": "b"}}],
                ),
                "primary",
            ),
            (ModelResponse(text="done", tool_calls=[]), "primary"),
        ]
    )
    runtime = _FailingRuntime()
    notifications: list[tuple[str, dict[str, object]]] = []

    def notify(event_type: str, payload: dict[str, object]) -> None:
        notifications.append((event_type, payload))

    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550888")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "do thing")
        _ = asyncio.run(
            run_agent_step(
                conn,
                router,
                runtime,
                thread_id=thread_id,
                trace_id="trc_step_tool_error",
                notify_fn=notify,
            )
        )
    assert any(evt == "tool.call.end" and "error" in payload for evt, payload in notifications)


def test_run_agent_step_enqueues_full_tool_memory_payload(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    captured: list[dict[str, object]] = []

    def _capture_memory(**kwargs: object) -> None:
        captured.append(dict(kwargs))

    monkeypatch.setattr("jarvis.orchestrator.step._enqueue_memory_index", _capture_memory)
    router = _SequenceRouter(
        [
            (
                ModelResponse(
                    text="calling tool",
                    tool_calls=[{"name": "echo", "arguments": {"x": 1}}],
                ),
                "primary",
            ),
            (ModelResponse(text="done", tool_calls=[]), "primary"),
        ]
    )
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550877")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "run tool")
        _ = asyncio.run(
            run_agent_step(conn, router, runtime, thread_id=thread_id, trace_id="trc_step_tool_mem")
        )
    tool_entries = [
        item for item in captured if item.get("metadata", {}).get("source") == "tool.call.end"
    ]
    assert tool_entries
    first = tool_entries[0]
    metadata = first["metadata"]
    assert isinstance(metadata, dict)
    assert "result_sha256" in metadata
    assert "result_char_count" in metadata
    text = str(first["text"])
    assert '"type": "tool.call.end"' in text
    assert '"status": "success"' in text


def test_run_agent_step_enqueues_thought_memory_payload(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.orchestrator.step._update_heartbeat", lambda *_args: None)
    captured: list[dict[str, object]] = []

    def _capture_memory(**kwargs: object) -> None:
        captured.append(dict(kwargs))

    monkeypatch.setattr("jarvis.orchestrator.step._enqueue_memory_index", _capture_memory)
    router = _SequenceRouter(
        [
            (
                ModelResponse(
                    text="answer",
                    tool_calls=[],
                    reasoning_text="reasoned thoughts",
                    reasoning_parts=[{"text": "reasoned thoughts"}],
                ),
                "primary",
            )
        ]
    )
    runtime = _FakeRuntime()
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550876")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "hello")
        _ = asyncio.run(
            run_agent_step(
                conn,
                router,
                runtime,
                thread_id=thread_id,
                trace_id="trc_step_thought_mem",
            )
        )
    thought_entries = [
        item for item in captured if item.get("metadata", {}).get("source") == "agent.thought"
    ]
    assert thought_entries
    metadata = thought_entries[0]["metadata"]
    assert isinstance(metadata, dict)
    assert "thought_sha256" in metadata
    assert "thought_char_count" in metadata
    assert '"type": "agent.thought"' in str(thought_entries[0]["text"])
