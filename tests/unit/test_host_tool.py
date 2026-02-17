import os
from pathlib import Path

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
