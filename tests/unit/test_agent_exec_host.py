import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from jarvis.db.connection import get_conn
from jarvis.tasks.agent import _build_registry


def test_exec_host_build_test_gates_gets_extended_default_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_execute_host_command(
        conn: sqlite3.Connection,
        *,
        command: str,
        trace_id: str,
        caller_id: str,
        thread_id: str | None = None,
        cwd: str | None = None,
        env: dict[str, object] | None = None,
        timeout_s: int = 120,
    ) -> dict[str, object]:
        del conn, trace_id, caller_id, thread_id, cwd, env
        captured["command"] = command
        captured["timeout_s"] = timeout_s
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr("jarvis.tasks.agent.execute_host_command", fake_execute_host_command)

    with get_conn() as conn:
        registry = _build_registry(conn, trace_id="trc_test", thread_id="thr_test", actor_id="main")
        tool = registry.get("exec_host")
        assert tool is not None
        _ = asyncio.run(
            _run_tool(tool.handler, {"command": "uv run jarvis test-gates --fail-fast"})
        )

    assert captured["command"] == "uv run jarvis test-gates --fail-fast"
    assert captured["timeout_s"] == 600


def test_exec_host_explicit_timeout_is_preserved_for_build_test_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_execute_host_command(
        conn: sqlite3.Connection,
        *,
        command: str,
        trace_id: str,
        caller_id: str,
        thread_id: str | None = None,
        cwd: str | None = None,
        env: dict[str, object] | None = None,
        timeout_s: int = 120,
    ) -> dict[str, object]:
        del conn, command, trace_id, caller_id, thread_id, cwd, env
        captured["timeout_s"] = timeout_s
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr("jarvis.tasks.agent.execute_host_command", fake_execute_host_command)

    with get_conn() as conn:
        registry = _build_registry(conn, trace_id="trc_test", thread_id="thr_test", actor_id="main")
        tool = registry.get("exec_host")
        assert tool is not None
        _ = asyncio.run(
            _run_tool(
                tool.handler,
                {"command": "uv run jarvis test-gates --fail-fast", "timeout_s": 180},
            )
        )

    assert captured["timeout_s"] == 180


async def _run_tool(
    handler: Callable[[dict[str, object]], Awaitable[dict[str, object]]],
    args: dict[str, object],
) -> dict[str, object]:
    return await handler(args)
