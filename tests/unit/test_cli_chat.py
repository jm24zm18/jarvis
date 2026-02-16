from __future__ import annotations

import json

from click.testing import CliRunner

from jarvis.cli.main import cli
from jarvis.db.connection import get_conn
from jarvis.db.queries import insert_message


def _fake_agent_step(trace_id: str, thread_id: str, actor_id: str = "main") -> str:
    _ = trace_id
    _ = actor_id
    with get_conn() as conn:
        return insert_message(conn, thread_id, "assistant", "hello from main")


def test_ask_sync_round_trip(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.cli.chat.agent_step", _fake_agent_step)
    runner = CliRunner()
    result = runner.invoke(cli, ["ask", "hi", "--user-id", "cli:test"])
    assert result.exit_code == 0
    assert "hello from main" in result.output


def test_ask_json_output(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.cli.chat.agent_step", _fake_agent_step)
    runner = CliRunner()
    result = runner.invoke(cli, ["ask", "hi", "--user-id", "cli:test", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["assistant"] == "hello from main"
    assert str(payload["thread_id"]).startswith("thr_")


def test_ask_enqueue_mode(monkeypatch) -> None:
    def _send_task(name: str, kwargs: dict[str, str], queue: str) -> None:
        assert name == "jarvis.tasks.agent.agent_step"
        assert queue == "agent_priority"
        thread_id = kwargs["thread_id"]
        with get_conn() as conn:
            insert_message(conn, thread_id, "assistant", "queued reply")

    monkeypatch.setattr("jarvis.cli.chat.celery_app.send_task", _send_task)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "ask",
            "hi",
            "--user-id",
            "cli:test",
            "--enqueue",
            "--timeout-s",
            "1.0",
            "--poll-interval-s",
            "0.1",
        ],
    )
    assert result.exit_code == 0
    assert "queued reply" in result.output


def test_chat_interactive_loop(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.cli.chat.agent_step", _fake_agent_step)
    runner = CliRunner()
    result = runner.invoke(cli, ["chat", "--user-id", "cli:test"], input="hello\n/quit\n")
    assert result.exit_code == 0
    assert "assistant > hello from main" in result.output
