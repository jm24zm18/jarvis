from __future__ import annotations

from click.testing import CliRunner

from jarvis.cli.main import cli
from jarvis.db.connection import get_conn


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
