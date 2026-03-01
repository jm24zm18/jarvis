import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import create_approval, ensure_system_state, get_system_state
from jarvis.tools.host import _DEFAULT_MAX_CAPTURE_BYTES as MAX_CAPTURE_BYTES
from jarvis.tools.host import execute_host_command


def test_exec_host_success_writes_log(tmp_path: Path) -> None:
    os.environ["EXEC_HOST_LOG_DIR"] = str(tmp_path / "exec-logs")
    os.environ["EXEC_HOST_ALLOWED_CWD_PREFIXES"] = str(tmp_path)
    get_settings.cache_clear()
    try:
        with get_conn() as conn:
            ensure_system_state(conn)
            result = execute_host_command(
                conn,
                command="echo hello",
                cwd=str(tmp_path),
                trace_id="trc_host_1",
                caller_id="coder",
            )
        assert result["exit_code"] == 0
        assert "hello" in str(result["stdout"])
        assert Path(str(result["log_path"])).exists()
    finally:
        get_settings.cache_clear()


def test_exec_host_rejects_sudo(tmp_path: Path) -> None:
    os.environ["EXEC_HOST_ALLOWED_CWD_PREFIXES"] = str(tmp_path)
    get_settings.cache_clear()
    try:
        with get_conn() as conn:
            ensure_system_state(conn)
            result = execute_host_command(
                conn,
                command="sudo ls",
                cwd=str(tmp_path),
                trace_id="trc_host_2",
                caller_id="coder",
            )
        assert result["exit_code"] == 126
        assert "host.exec.sudo requires admin approval record" in str(result["stderr"])
    finally:
        get_settings.cache_clear()


def test_exec_host_sudo_requires_and_consumes_approval(tmp_path: Path) -> None:
    os.environ["EXEC_HOST_ALLOWED_CWD_PREFIXES"] = str(tmp_path)
    get_settings.cache_clear()
    try:
        with get_conn() as conn:
            ensure_system_state(conn)
            _ = create_approval(conn, action="host.exec.sudo", actor_id="admin_1")
            first = execute_host_command(
                conn,
                command="sudo -n true",
                cwd=str(tmp_path),
                trace_id="trc_host_4",
                caller_id="coder",
            )
            second = execute_host_command(
                conn,
                command="sudo -n true",
                cwd=str(tmp_path),
                trace_id="trc_host_5",
                caller_id="coder",
            )
        assert first["exit_code"] != 126
        assert second["exit_code"] == 126
    finally:
        get_settings.cache_clear()


def test_exec_host_truncates_large_output(tmp_path: Path) -> None:
    os.environ["EXEC_HOST_ALLOWED_CWD_PREFIXES"] = str(tmp_path)
    get_settings.cache_clear()
    try:
        with get_conn() as conn:
            ensure_system_state(conn)
            result = execute_host_command(
                conn,
                command="python3 - <<'PY'\nprint('x' * 50000)\nPY",
                cwd=str(tmp_path),
                trace_id="trc_host_3",
                caller_id="coder",
            )
        assert result["exit_code"] == 0
        stdout = str(result["stdout"])
        assert len(stdout.encode("utf-8")) <= MAX_CAPTURE_BYTES
        assert result["stdout_truncated"] is True
    finally:
        get_settings.cache_clear()


def test_exec_host_protected_path_triggers_lockdown(tmp_path: Path) -> None:
    os.environ["EXEC_HOST_ALLOWED_CWD_PREFIXES"] = str(tmp_path)
    get_settings.cache_clear()
    try:
        with get_conn() as conn:
            ensure_system_state(conn)
            result = execute_host_command(
                conn,
                command="cat /etc/ssh/sshd_config",
                cwd=str(tmp_path),
                trace_id="trc_host_6",
                caller_id="coder",
            )
            state = get_system_state(conn)
        assert result["exit_code"] == 126
        assert "protected path" in str(result["stderr"])
        assert state["lockdown"] == 1
    finally:
        get_settings.cache_clear()


def test_exec_host_failure_rate_emits_lockdown_triggered_event(tmp_path: Path) -> None:
    os.environ["EXEC_HOST_ALLOWED_CWD_PREFIXES"] = str(tmp_path)
    os.environ["LOCKDOWN_EXEC_HOST_FAIL_THRESHOLD"] = "1"
    get_settings.cache_clear()
    try:
        with get_conn() as conn:
            ensure_system_state(conn)
            result = execute_host_command(
                conn,
                command="false",
                cwd=str(tmp_path),
                trace_id="trc_host_fail_lock_1",
                caller_id="coder",
            )
            row = conn.execute(
                "SELECT payload_redacted_json FROM events "
                "WHERE event_type='lockdown.triggered' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            state = get_system_state(conn)
        assert result["exit_code"] != 0
        assert state["lockdown"] == 1
        assert row is not None
        assert "exec_host_failure_rate" in str(row["payload_redacted_json"])
    finally:
        get_settings.cache_clear()


def test_exec_host_none_sandbox_does_not_apply_ulimit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    os.environ["EXEC_HOST_ALLOWED_CWD_PREFIXES"] = str(tmp_path)
    os.environ["EXEC_HOST_SANDBOX"] = "none"
    get_settings.cache_clear()
    captured: dict[str, object] = {}

    def _fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        cmd = args[0]
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("jarvis.tools.host.subprocess.run", _fake_run)
    try:
        with get_conn() as conn:
            ensure_system_state(conn)
            result = execute_host_command(
                conn,
                command="echo ok",
                cwd=str(tmp_path),
                trace_id="trc_host_sandbox_none",
                caller_id="coder",
            )
        assert result["exit_code"] == 0
        assert captured["cmd"] == ["/bin/bash", "-lc", "echo ok"]
    finally:
        get_settings.cache_clear()


def test_exec_host_sqlite_preflight_hints_unknown_table(tmp_path: Path) -> None:
    os.environ["EXEC_HOST_ALLOWED_CWD_PREFIXES"] = str(tmp_path)
    get_settings.cache_clear()
    db_path = tmp_path / "sqlite-preflight.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE bug_reports(id TEXT PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE schema_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_migrations(name, applied_at) VALUES('001_initial.sql','2026-01-01')"
        )
    try:
        with get_conn() as conn:
            ensure_system_state(conn)
            result = execute_host_command(
                conn,
                command=f"sqlite3 {db_path} \"SELECT * FROM feature_requests LIMIT 1;\"",
                cwd=str(tmp_path),
                trace_id="trc_host_sqlite_preflight",
                caller_id="coder",
            )
        assert result["exit_code"] == 2
        assert "sqlite preflight" in str(result["stderr"])
        assert "feature_requests -> bug_reports" in str(result["stderr"])
    finally:
        get_settings.cache_clear()


def test_exec_host_workspace_write_denied_for_non_feature_builder(tmp_path: Path) -> None:
    os.environ["EXEC_HOST_ALLOWED_CWD_PREFIXES"] = str(tmp_path)
    os.environ["FEATURE_ISOLATION_TMP_PREFIX"] = "/tmp/jarvis-feature"
    get_settings.cache_clear()
    workspace_dir = Path("/tmp/jarvis-feature-bug_test-123")
    try:
        with get_conn() as conn:
            ensure_system_state(conn)
            result = execute_host_command(
                conn,
                command=f"touch {workspace_dir}/new.txt",
                cwd=str(tmp_path),
                trace_id="trc_host_workspace_guard",
                caller_id="coder",
            )
        assert result["exit_code"] == 126
        assert "workspace write denied" in str(result["stderr"])
    finally:
        get_settings.cache_clear()
