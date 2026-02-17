import asyncio

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    ensure_channel,
    ensure_open_thread,
    ensure_system_state,
    ensure_user,
    insert_message,
)
from jarvis.orchestrator.step import run_agent_step
from jarvis.providers.base import ModelResponse
from jarvis.providers.router import ProviderRouter
from jarvis.providers.sglang import SGLangProvider
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.runtime import ToolRuntime


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


def test_orchestrator_executes_command_short_path() -> None:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "15555550123")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "/status")

        router = ProviderRouter(StubProvider(), SGLangProvider("s"))
        runtime = ToolRuntime(ToolRegistry())
        _ = asyncio.run(run_agent_step(conn, router, runtime, thread_id, "trc_99"))

        row = conn.execute(
            "SELECT role, content FROM messages WHERE thread_id=? ORDER BY created_at DESC LIMIT 1",
            (thread_id,),
        ).fetchone()

    assert row is not None
    assert row["role"] == "assistant"
    assert "providers" in row["content"]
