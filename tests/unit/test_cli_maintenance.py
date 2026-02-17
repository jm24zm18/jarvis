from __future__ import annotations

from click.testing import CliRunner

from jarvis.cli.main import cli
from jarvis.config import get_settings
from jarvis.db.connection import get_conn


def test_maintenance_run_reports_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.tasks.maintenance.run_local_maintenance",
        lambda: {"ok": True, "bug_ids": []},
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["maintenance", "run"])
    assert result.exit_code == 0
    assert "maintenance run: ok" in result.output


def test_maintenance_run_reports_failures_and_bugs(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.tasks.maintenance.run_local_maintenance",
        lambda: {"ok": False, "bug_ids": ["bug_1"]},
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["maintenance", "run"])
    assert result.exit_code == 0
    assert "maintenance run: failures detected" in result.output
    assert "bug_1" in result.output


def test_maintenance_enqueue(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class _Runner:
        def send_task(self, name: str, queue: str) -> bool:
            calls.append((name, queue))
            return True

    def _get_runner() -> _Runner:
        return _Runner()

    monkeypatch.setattr("jarvis.tasks.get_task_runner", _get_runner)
    runner = CliRunner()
    result = runner.invoke(cli, ["maintenance", "enqueue"])
    assert result.exit_code == 0
    assert "maintenance task queued" in result.output
    assert calls == [("jarvis.tasks.maintenance.run_local_maintenance", "agent_default")]


def test_maintenance_status_json(monkeypatch) -> None:
    monkeypatch.setenv("MAINTENANCE_ENABLED", "1")
    monkeypatch.setenv("MAINTENANCE_INTERVAL_SECONDS", "900")
    monkeypatch.setenv("MAINTENANCE_COMMANDS", "make lint\\nmake typecheck")
    get_settings.cache_clear()
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO events(id, trace_id, span_id, parent_span_id, thread_id, event_type, "
                "component, actor_type, actor_id, payload_json, payload_redacted_json, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "evt_maintenance_heartbeat",
                "trc_maintenance_heartbeat",
                "spn_maintenance_heartbeat",
                None,
                None,
                "maintenance.heartbeat",
                "maintenance",
                "system",
                "maintenance",
                "{}",
                "{}",
                "2026-01-01T00:00:01+00:00",
            ),
        )
        conn.execute(
            (
                "INSERT INTO bug_reports(id, title, description, status, priority, reporter_id, "
                "assignee_agent, thread_id, trace_id, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "bug_test_maintenance",
                "Local maintenance check failed: make lint",
                "{}",
                "open",
                "medium",
                None,
                "release_ops",
                None,
                None,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
    runner = CliRunner()
    result = runner.invoke(cli, ["maintenance", "status", "--json"])
    assert result.exit_code == 0
    assert '"enabled": true' in result.output
    assert '"periodic_scheduler_active"' in result.output
    assert '"last_heartbeat"' in result.output
    assert '"trc_maintenance_heartbeat"' in result.output
    assert '"open_maintenance_bugs": 1' in result.output
