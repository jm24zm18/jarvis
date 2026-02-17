"""Local maintenance tasks (lint/typecheck/test checks)."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import now_iso
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id

_MAX_CAPTURE_CHARS = 4000


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _truncate(text: str, max_chars: int = _MAX_CAPTURE_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...[truncated]"


def _commands_from_settings(raw: str) -> list[str]:
    normalized = raw.replace("\\n", "\n")
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def _run_command(command: str, *, cwd: Path, timeout_s: int) -> dict[str, object]:
    try:
        proc = subprocess.run(
            ["/bin/bash", "-lc", command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=max(1, timeout_s),
            check=False,
        )
        return {
            "command": command,
            "ok": proc.returncode == 0,
            "exit_code": int(proc.returncode),
            "stdout": _truncate(proc.stdout or ""),
            "stderr": _truncate(proc.stderr or ""),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        err = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "command": command,
            "ok": False,
            "exit_code": 124,
            "stdout": _truncate(out),
            "stderr": _truncate(err),
            "timed_out": True,
        }


def _recent_open_bug_exists(conn, title: str, *, within_hours: int = 24) -> bool:
    row = conn.execute(
        "SELECT created_at FROM bug_reports WHERE title=? AND status IN ('open', 'in_progress') "
        "ORDER BY created_at DESC LIMIT 1",
        (title,),
    ).fetchone()
    if row is None:
        return False
    raw_created = str(row["created_at"])
    try:
        created = datetime.fromisoformat(raw_created)
    except ValueError:
        return False
    return created >= datetime.now(UTC) - timedelta(hours=within_hours)


def _record_maintenance_bug(command_result: dict[str, object], workdir: Path) -> str | None:
    title = f"Local maintenance check failed: {command_result.get('command', '')}"
    with get_conn() as conn:
        if _recent_open_bug_exists(conn, title):
            return None
        bug_id = new_id("bug")
        now = now_iso()
        conn.execute(
            (
                "INSERT INTO bug_reports(id, title, description, status, priority, "
                "reporter_id, assignee_agent, thread_id, trace_id, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                bug_id,
                title,
                json.dumps(
                    {
                        "source": "local_maintenance",
                        "workdir": str(workdir),
                        "result": command_result,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                "open",
                "medium",
                None,
                "release_ops",
                None,
                None,
                now,
                now,
            ),
        )
    return bug_id


def run_local_maintenance() -> dict[str, object]:
    settings = get_settings()
    if int(settings.maintenance_enabled) != 1:
        return {"ok": True, "skipped": "maintenance_disabled"}

    commands = _commands_from_settings(settings.maintenance_commands)
    if not commands:
        return {"ok": True, "skipped": "no_commands"}

    cwd = (
        Path(settings.maintenance_workdir).expanduser().resolve()
        if settings.maintenance_workdir.strip()
        else _repo_root()
    )
    timeout_s = int(settings.maintenance_timeout_seconds)

    results: list[dict[str, object]] = []
    bug_ids: list[str] = []
    for command in commands:
        result = _run_command(command, cwd=cwd, timeout_s=timeout_s)
        results.append(result)
        if not bool(result.get("ok")) and int(settings.maintenance_create_bugs) == 1:
            bug_id = _record_maintenance_bug(result, cwd)
            if bug_id:
                bug_ids.append(bug_id)

    ok = all(bool(item.get("ok")) for item in results)
    return {
        "ok": ok,
        "workdir": str(cwd),
        "command_count": len(results),
        "results": results,
        "bug_ids": bug_ids,
    }


def maintenance_heartbeat() -> dict[str, object]:
    settings = get_settings()
    payload = {
        "source": "maintenance.heartbeat",
        "maintenance_enabled": int(settings.maintenance_enabled) == 1,
        "maintenance_interval_seconds": int(settings.maintenance_interval_seconds),
    }
    trace_id = new_id("trc")
    with get_conn() as conn:
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=None,
                event_type="maintenance.heartbeat",
                component="maintenance",
                actor_type="system",
                actor_id="maintenance",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )
    return {"ok": True, "trace_id": trace_id, "timestamp": now_iso()}
