"""Host command execution tool with safety controls."""

import json
import os
import re
import shlex
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from jarvis.config import get_settings
from jarvis.db.queries import (
    consume_approval,
    get_agent_governance,
    get_system_state,
    record_exec_host_result,
    trigger_lockdown,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id

_DEFAULT_MAX_CAPTURE_BYTES = 32 * 1024
FALLBACK_LOG_DIR = Path("/tmp/jarvis_exec")
PROTECTED_CWD_PREFIXES = (
    Path("/etc"),
    Path("/root"),
    Path("/etc/systemd/system"),
    Path("/etc/sudoers.d"),
    Path("/etc/ssh"),
)
DENY_PATTERNS = (
    re.compile(r"\brm\s+-rf\s+/(\s|$)"),
    re.compile(r"\bmkfs(\.|$)"),
    re.compile(r":\(\)\s*\{"),  # fork bomb
)
PRIVILEGED_CLASSES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("host.exec.sudo", re.compile(r"(^|\s)sudo(\s|$)")),
    ("host.exec.systemctl", re.compile(r"(^|\s)systemctl(\s|$)")),
    ("host.exec.protected_path", re.compile(r"/etc/systemd/system/|/etc/ssh/|/root/")),
)
PROTECTED_PATH_PATTERN = re.compile(
    r"/etc/systemd/system/|/etc/sudoers(\.d)?/|/etc/ssh/|/etc/[^ ]*iptables|/etc/nftables|/root/"
)


def _is_subpath(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _truncate_text(value: str, max_bytes: int = _DEFAULT_MAX_CAPTURE_BYTES) -> tuple[str, bool]:
    encoded = value.encode("utf-8", errors="ignore")
    if len(encoded) <= max_bytes:
        return value, False
    clipped = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return clipped, True


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return value


def _sanitize_env(user_env: dict[str, Any] | None) -> dict[str, str]:
    settings = get_settings()
    allow = {item.strip() for item in settings.exec_host_env_allowlist.split(",") if item.strip()}
    clean: dict[str, str] = {}
    for key in allow:
        val = os.environ.get(key)
        if val is not None:
            clean[key] = val
    if user_env:
        for key, value in user_env.items():
            if key in allow and isinstance(value, str):
                clean[key] = value
    return clean


def _resolve_cwd(cwd: str | None) -> tuple[Path | None, str | None]:
    if cwd is None:
        return None, None
    candidate = Path(cwd).expanduser().resolve()
    if not candidate.exists() or not candidate.is_dir():
        return None, f"cwd is not a directory: {candidate}"
    for protected in PROTECTED_CWD_PREFIXES:
        if _is_subpath(candidate, protected):
            return None, f"cwd is protected: {candidate}"
    settings = get_settings()
    prefixes = [
        Path(item.strip()).expanduser().resolve()
        for item in settings.exec_host_allowed_cwd_prefixes.split(",")
        if item.strip()
    ]
    if prefixes and not any(_is_subpath(candidate, prefix) for prefix in prefixes):
        return None, f"cwd outside allowlist: {candidate}"
    return candidate, None


def _allowed_prefixes_for_caller(conn: sqlite3.Connection, caller_id: str) -> list[Path]:
    governance = get_agent_governance(conn, caller_id)
    if governance is None:
        return []
    raw_obj = governance.get("allowed_paths", [])
    raw = raw_obj if isinstance(raw_obj, list) else []
    return [
        Path(str(item)).expanduser().resolve()
        for item in raw
        if isinstance(item, str) and item.strip()
    ]


def _validate_caller_paths(
    conn: sqlite3.Connection,
    caller_id: str,
    command: str,
    cwd: Path | None,
) -> str | None:
    prefixes = _allowed_prefixes_for_caller(conn, caller_id)
    if not prefixes:
        return None
    if cwd is not None and not any(_is_subpath(cwd, prefix) for prefix in prefixes):
        return f"cwd outside caller governance allowlist: {cwd}"
    try:
        tokens = shlex.split(command)
    except ValueError:
        return "command parse failure for governance allowlist"
    for token in tokens:
        if not token.startswith("/"):
            continue
        target = Path(token).expanduser().resolve()
        if any(_is_subpath(target, prefix) for prefix in prefixes):
            continue
        return f"path outside caller governance allowlist: {target}"
    return None


def _write_full_log(start_event_id: str, stdout: str, stderr: str) -> str:
    settings = get_settings()
    preferred = Path(settings.exec_host_log_dir)
    for base in (preferred, FALLBACK_LOG_DIR):
        try:
            base.mkdir(parents=True, exist_ok=True)
            path = base / f"{start_event_id}.log"
            path.write_text(f"[stdout]\n{stdout}\n\n[stderr]\n{stderr}\n")
            return str(path)
        except OSError:
            continue
    return ""


def _emit(
    conn: sqlite3.Connection,
    trace_id: str,
    thread_id: str | None,
    event_type: str,
    payload: dict[str, object],
    parent_span_id: str | None = None,
) -> str:
    return emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=parent_span_id,
            thread_id=thread_id,
            event_type=event_type,
            component="tools.host",
            actor_type="agent",
            actor_id="host",
            payload_json=json.dumps(payload),
            payload_redacted_json=json.dumps(redact_payload(payload)),
        ),
    )


def _emit_lockdown_triggered(
    conn: sqlite3.Connection,
    trace_id: str,
    thread_id: str | None,
    caller_id: str,
    reason: str,
) -> None:
    _ = emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id,
            event_type="lockdown.triggered",
            component="tools.host",
            actor_type="agent",
            actor_id=caller_id,
            payload_json=json.dumps({"reason": reason}),
            payload_redacted_json=json.dumps(redact_payload({"reason": reason})),
        ),
    )


def execute_host_command(
    conn: sqlite3.Connection,
    *,
    command: str,
    trace_id: str,
    caller_id: str,
    thread_id: str | None = None,
    cwd: str | None = None,
    env: dict[str, Any] | None = None,
    timeout_s: int = 120,
) -> dict[str, object]:
    settings = get_settings()
    state = get_system_state(conn)
    pre_lockdown = state["lockdown"] == 1
    bounded_timeout = max(1, min(int(timeout_s), settings.exec_host_timeout_max_seconds))
    start_payload: dict[str, object] = {
        "caller_id": caller_id,
        "command": command,
        "cwd": cwd,
        "timeout_s": bounded_timeout,
    }
    start_event_id = _emit(conn, trace_id, thread_id, "host.exec.start", start_payload)

    for pattern in DENY_PATTERNS:
        if pattern.search(command):
            stderr = "command denied by safety policy"
            locked = record_exec_host_result(
                conn,
                ok=False,
                threshold_count=settings.lockdown_exec_host_fail_threshold,
                window_minutes=settings.lockdown_exec_host_fail_window_minutes,
            )
            if not pre_lockdown and locked:
                _emit_lockdown_triggered(
                    conn, trace_id, thread_id, caller_id, "exec_host_failure_rate"
                )
            end_payload = {
                "start_event_id": start_event_id,
                "exit_code": 126,
                "stdout": "",
                "stderr": stderr,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "log_path": "",
            }
            _ = _emit(conn, trace_id, thread_id, "host.exec.end", end_payload)
            return {"exit_code": 126, "stdout": "", "stderr": stderr}

    if PROTECTED_PATH_PATTERN.search(command):
        trigger_lockdown(conn, "protected_path_attempt")
        _emit_lockdown_triggered(conn, trace_id, thread_id, caller_id, "protected_path_attempt")
        stderr = "command references protected path; lockdown triggered"
        _ = record_exec_host_result(
            conn,
            ok=False,
            threshold_count=settings.lockdown_exec_host_fail_threshold,
            window_minutes=settings.lockdown_exec_host_fail_window_minutes,
        )
        end_payload = {
            "start_event_id": start_event_id,
            "exit_code": 126,
            "stdout": "",
            "stderr": stderr,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "log_path": "",
        }
        _ = _emit(conn, trace_id, thread_id, "host.exec.end", end_payload)
        return {"exit_code": 126, "stdout": "", "stderr": stderr}

    required = _required_approval_action(command)
    governance = get_agent_governance(conn, caller_id)
    if required is not None and governance is not None:
        can_request = bool(governance.get("can_request_privileged_change", False))
        if not can_request:
            stderr = "privileged host command denied for caller governance profile"
            end_payload = {
                "start_event_id": start_event_id,
                "exit_code": 126,
                "stdout": "",
                "stderr": stderr,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "log_path": "",
            }
            _ = _emit(conn, trace_id, thread_id, "host.exec.end", end_payload)
            return {"exit_code": 126, "stdout": "", "stderr": stderr}
    if required is not None and not consume_approval(conn, required, trace_id=trace_id):
        stderr = f"{required} requires admin approval record"
        _ = emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="policy.decision",
                component="policy",
                actor_type="agent",
                actor_id=caller_id,
                payload_json=json.dumps(
                    {
                        "tool": "exec_host",
                        "allowed": False,
                        "reason": "missing approval",
                        "required_action": required,
                    }
                ),
                payload_redacted_json=json.dumps(
                    redact_payload(
                        {
                            "tool": "exec_host",
                            "allowed": False,
                            "reason": "missing approval",
                            "required_action": required,
                        }
                    )
                ),
            ),
        )
        end_payload = {
            "start_event_id": start_event_id,
            "exit_code": 126,
            "stdout": "",
            "stderr": stderr,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "log_path": "",
        }
        locked = record_exec_host_result(
            conn,
            ok=False,
            threshold_count=settings.lockdown_exec_host_fail_threshold,
            window_minutes=settings.lockdown_exec_host_fail_window_minutes,
        )
        if not pre_lockdown and locked:
            _emit_lockdown_triggered(conn, trace_id, thread_id, caller_id, "exec_host_failure_rate")
        _ = _emit(conn, trace_id, thread_id, "host.exec.end", end_payload)
        return {"exit_code": 126, "stdout": "", "stderr": stderr}

    resolved_cwd, cwd_error = _resolve_cwd(cwd)
    if cwd_error is not None:
        end_payload = {
            "start_event_id": start_event_id,
            "exit_code": 2,
            "stdout": "",
            "stderr": cwd_error,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "log_path": "",
        }
        locked = record_exec_host_result(
            conn,
            ok=False,
            threshold_count=settings.lockdown_exec_host_fail_threshold,
            window_minutes=settings.lockdown_exec_host_fail_window_minutes,
        )
        if not pre_lockdown and locked:
            _emit_lockdown_triggered(conn, trace_id, thread_id, caller_id, "exec_host_failure_rate")
        _ = _emit(conn, trace_id, thread_id, "host.exec.end", end_payload)
        return {"exit_code": 2, "stdout": "", "stderr": cwd_error}
    caller_path_error = _validate_caller_paths(conn, caller_id, command, resolved_cwd)
    if caller_path_error is not None:
        end_payload = {
            "start_event_id": start_event_id,
            "exit_code": 126,
            "stdout": "",
            "stderr": caller_path_error,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "log_path": "",
        }
        locked = record_exec_host_result(
            conn,
            ok=False,
            threshold_count=settings.lockdown_exec_host_fail_threshold,
            window_minutes=settings.lockdown_exec_host_fail_window_minutes,
        )
        if not pre_lockdown and locked:
            _emit_lockdown_triggered(conn, trace_id, thread_id, caller_id, "exec_host_failure_rate")
        _ = _emit(conn, trace_id, thread_id, "host.exec.end", end_payload)
        return {"exit_code": 126, "stdout": "", "stderr": caller_path_error}

    sanitized_env = _sanitize_env(env)

    # Resource limits via ulimit prefix when sandbox mode is not 'none'
    max_output = settings.exec_host_max_output_bytes
    max_mem_mb = settings.exec_host_max_memory_mb
    max_cpu_s = settings.exec_host_max_cpu_seconds
    sandbox_mode = settings.exec_host_sandbox.strip().lower()

    if sandbox_mode == "docker":
        # Wrap command in a docker container with resource limits
        docker_cmd = (
            f"docker run --rm --network=none "
            f"--memory={max_mem_mb}m --cpus=1 "
            f"--pids-limit=128 "
            f"-w /workspace "
            f"ubuntu:22.04 /bin/bash -c {shlex.quote(command)}"
        )
        exec_cmd = ["/bin/bash", "-lc", docker_cmd]
    else:
        # Apply resource limits via ulimit (best-effort without Docker)
        ulimit_prefix = (
            f"ulimit -v {max_mem_mb * 1024} 2>/dev/null; "
            f"ulimit -t {max_cpu_s} 2>/dev/null; "
        )
        exec_cmd = ["/bin/bash", "-lc", f"{ulimit_prefix}{command}"]

    try:
        proc = subprocess.run(
            exec_cmd,
            cwd=str(resolved_cwd) if resolved_cwd is not None else None,
            env=sanitized_env,
            capture_output=True,
            text=True,
            timeout=bounded_timeout,
            check=False,
        )
        exit_code = int(proc.returncode)
        full_stdout = proc.stdout or ""
        full_stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        full_stdout = _to_text(exc.stdout)
        full_stderr = _to_text(exc.stderr)
        if "timed out" not in full_stderr:
            full_stderr = f"{full_stderr}\ncommand timed out".strip()

    capture_limit = min(max_output, _DEFAULT_MAX_CAPTURE_BYTES)
    stdout, out_truncated = _truncate_text(full_stdout, capture_limit)
    stderr, err_truncated = _truncate_text(full_stderr, capture_limit)
    log_path = _write_full_log(start_event_id, full_stdout, full_stderr)
    end_payload = {
        "start_event_id": start_event_id,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": out_truncated,
        "stderr_truncated": err_truncated,
        "log_path": log_path,
    }
    _ = _emit(conn, trace_id, thread_id, "host.exec.end", end_payload)
    locked = record_exec_host_result(
        conn,
        ok=exit_code == 0,
        threshold_count=settings.lockdown_exec_host_fail_threshold,
        window_minutes=settings.lockdown_exec_host_fail_window_minutes,
    )
    if not pre_lockdown and exit_code != 0 and locked:
        _emit_lockdown_triggered(conn, trace_id, thread_id, caller_id, "exec_host_failure_rate")
    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "log_path": log_path,
        "stdout_truncated": out_truncated,
        "stderr_truncated": err_truncated,
    }


def _required_approval_action(command: str) -> str | None:
    for action, pattern in PRIVILEGED_CLASSES:
        if pattern.search(command):
            return action
    return None
