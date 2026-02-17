"""System lifecycle and admin utility tasks."""

import json
import secrets
import subprocess
from pathlib import Path

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_system_state
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.tasks import get_task_runner


def _emit(trace_id: str, event_type: str, payload: dict[str, object]) -> None:
    with get_conn() as conn:
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=None,
                event_type=event_type,
                component="system",
                actor_type="system",
                actor_id="system",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )


def rotate_unlock_code(trace_id: str | None = None) -> dict[str, str]:
    settings = get_settings()
    code = f"{secrets.randbelow(1_000_000):06d}"
    code_path = Path(settings.admin_unlock_code_path)
    code_path.parent.mkdir(parents=True, exist_ok=True)
    code_path.write_text(code)
    use_trace = trace_id or new_id("trc")
    _emit(use_trace, "lockdown.code_rotated", {"path": str(code_path)})
    return {"status": "rotated"}


def system_restart(trace_id: str) -> dict[str, str]:
    settings = get_settings()
    db_flush_payload: dict[str, str]
    with get_conn() as conn:
        ensure_system_state(conn)
        conn.execute(
            "UPDATE system_state SET restarting=1, updated_at=datetime('now') WHERE id='singleton'"
        )
        try:
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            checkpoint = tuple(row) if row is not None else tuple()
            db_flush_payload = {"status": "ok", "checkpoint": str(checkpoint)}
        except Exception as exc:
            db_flush_payload = {"status": "failed", "error": str(exc)}
    _emit(trace_id, "system.restart.db_flush", db_flush_payload)
    _emit(trace_id, "system.restart.start", {"status": "draining"})
    timeout_s = float(settings.task_runner_shutdown_timeout_seconds)
    drained = True
    try:
        import asyncio

        asyncio.run(get_task_runner().shutdown(timeout_s=timeout_s))
    except Exception:
        drained = False
    _emit(
        trace_id,
        "system.restart.drain",
        {"drained": drained, "timeout_s": timeout_s},
    )
    restart_cmd = settings.restart_command.strip() or (
        "systemctl restart jarvis-api"
    )
    try:
        proc = subprocess.run(
            ["/bin/bash", "-lc", restart_cmd],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        exit_code = int(proc.returncode)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = (
            exc.stdout.decode("utf-8", errors="ignore")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="ignore")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        if "timed out" not in stderr:
            stderr = f"{stderr}\nrestart command timed out".strip()

    _emit(
        trace_id,
        "system.restart.exec",
        {
            "command": restart_cmd,
            "exit_code": exit_code,
            "stdout": stdout[:2048],
            "stderr": stderr[:2048],
        },
    )
    with get_conn() as conn:
        conn.execute(
            "UPDATE system_state SET restarting=0, updated_at=datetime('now') WHERE id='singleton'"
        )
    _emit(trace_id, "system.restart.complete", {"status": "ready"})
    return {"status": "restarted"}


def enqueue_restart(trace_id: str) -> bool:
    return get_task_runner().send_task(
        "jarvis.tasks.system.system_restart",
        kwargs={"trace_id": trace_id},
        queue="agent_default",
    )


def reload_settings_cache() -> dict[str, str]:
    get_settings.cache_clear()
    _ = get_settings()
    return {"status": "reloaded"}


def enqueue_settings_reload() -> bool:
    return get_task_runner().send_task(
        "jarvis.tasks.system.reload_settings_cache",
        kwargs={},
        queue="agent_default",
    )


def db_optimize() -> dict[str, str]:
    """Run PRAGMA optimize daily to maintain query planner statistics."""
    trace_id = new_id("trc")
    with get_conn() as conn:
        conn.execute("PRAGMA optimize")
    _emit(trace_id, "system.db_maintenance", {"action": "optimize", "status": "ok"})
    return {"action": "optimize", "status": "ok"}


def db_integrity_check() -> dict[str, str]:
    """Run PRAGMA integrity_check weekly to detect corruption."""
    trace_id = new_id("trc")
    with get_conn() as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        result = str(row[0]) if row else "unknown"
    status = "ok" if result == "ok" else "failed"
    _emit(
        trace_id,
        "system.db_maintenance",
        {"action": "integrity_check", "status": status, "result": result},
    )
    return {"action": "integrity_check", "status": status, "result": result}


def db_vacuum() -> dict[str, str]:
    """Run VACUUM monthly to reclaim disk space and defragment."""
    trace_id = new_id("trc")
    with get_conn() as conn:
        conn.execute("VACUUM")
    _emit(trace_id, "system.db_maintenance", {"action": "vacuum", "status": "ok"})
    return {"action": "vacuum", "status": "ok"}
