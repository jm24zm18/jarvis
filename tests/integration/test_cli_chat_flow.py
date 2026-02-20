from __future__ import annotations

import json

from click.testing import CliRunner

from jarvis.cli.main import cli
from jarvis.db.connection import get_conn
from jarvis.providers.base import ModelResponse


def test_ask_runs_main_agent_command_path() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["ask", "/status", "--user-id", "cli:integration"])
    assert result.exit_code == 0
    assert "providers" in result.output
    assert "scheduler" in result.output

    with get_conn() as conn:
        row = conn.execute(
            (
                "SELECT m.role FROM messages m "
                "JOIN threads t ON t.id=m.thread_id "
                "JOIN users u ON u.id=t.user_id "
                "WHERE u.external_id=? "
                "ORDER BY m.created_at DESC LIMIT 1"
            ),
            ("cli:integration",),
        ).fetchone()
    assert row is not None
    assert row["role"] == "assistant"


class _StubProvider:
    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ModelResponse:
        del messages, tools, temperature, max_tokens
        return ModelResponse(text="mocked provider reply", tool_calls=[])

    async def health_check(self) -> bool:
        return True


def test_ask_json_output_is_warning_free_with_mocked_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.tasks.agent.build_primary_provider",
        lambda _settings: _StubProvider(),
    )
    monkeypatch.setattr(
        "jarvis.tasks.agent.build_fallback_provider",
        lambda _settings: _StubProvider(),
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["ask", "hello", "--user-id", "cli:integration-json", "--json"])
    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["ok"] is True
    assert payload["assistant"] == "mocked provider reply"
    lowered = result.output.lower()
    assert "warning:" not in lowered
    assert "no adapter registered" not in lowered
