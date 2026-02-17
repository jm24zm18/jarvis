from pathlib import Path

from jarvis.db.connection import get_conn
from jarvis.tasks import maintenance as maintenance_tasks


def test_commands_from_settings_supports_escaped_newline() -> None:
    commands = maintenance_tasks._commands_from_settings("make lint\\nmake typecheck")
    assert commands == ["make lint", "make typecheck"]


def test_run_local_maintenance_disabled(monkeypatch) -> None:
    monkeypatch.setenv("MAINTENANCE_ENABLED", "0")
    maintenance_tasks.get_settings.cache_clear()
    result = maintenance_tasks.run_local_maintenance()
    assert result["ok"] is True
    assert result["skipped"] == "maintenance_disabled"


def test_run_local_maintenance_records_bug_for_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAINTENANCE_ENABLED", "1")
    monkeypatch.setenv("MAINTENANCE_COMMANDS", "cmd_ok\\ncmd_fail")
    monkeypatch.setenv("MAINTENANCE_CREATE_BUGS", "1")
    monkeypatch.setenv("MAINTENANCE_WORKDIR", str(tmp_path))
    maintenance_tasks.get_settings.cache_clear()

    def fake_run_command(command: str, *, cwd: Path, timeout_s: int) -> dict[str, object]:
        if command == "cmd_ok":
            return {
                "command": command,
                "ok": True,
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "timed_out": False,
            }
        return {
            "command": command,
            "ok": False,
            "exit_code": 2,
            "stdout": "",
            "stderr": "bad",
            "timed_out": False,
        }

    monkeypatch.setattr(maintenance_tasks, "_run_command", fake_run_command)
    result = maintenance_tasks.run_local_maintenance()
    assert result["ok"] is False
    assert result["command_count"] == 2
    assert len(result["bug_ids"]) == 1
    with get_conn() as conn:
        row = conn.execute(
            "SELECT title FROM bug_reports WHERE id=?",
            (result["bug_ids"][0],),
        ).fetchone()
    assert row is not None
    assert "Local maintenance check failed: cmd_fail" in str(row["title"])


def test_record_maintenance_bug_dedupes_open_issues(monkeypatch, tmp_path: Path) -> None:
    first = maintenance_tasks._record_maintenance_bug(
        {
            "command": "make lint",
            "ok": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "x",
            "timed_out": False,
        },
        tmp_path,
    )
    second = maintenance_tasks._record_maintenance_bug(
        {
            "command": "make lint",
            "ok": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "x",
            "timed_out": False,
        },
        tmp_path,
    )
    assert first is not None
    assert second is None


def test_maintenance_heartbeat() -> None:
    result = maintenance_tasks.maintenance_heartbeat()
    assert result["ok"] is True
    assert str(result["trace_id"]).startswith("trc_")
    assert "timestamp" in result
