"""Agent run attempt lifecycle helpers."""

from __future__ import annotations

import asyncio
import math
import random
import sqlite3
from datetime import UTC, datetime

from jarvis.config import Settings
from jarvis.db.queries import now_iso
from jarvis.errors import PolicyError, ProviderError

TERMINAL_STATUSES = {"succeeded", "failed", "abandoned", "retry_exhausted"}


def start_attempt(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    thread_id: str,
    actor_id: str,
    attempt: int,
    initial_dirty_files: str | None = None,
) -> None:
    stamp = now_iso()
    conn.execute(
        (
            "INSERT INTO agent_run_attempts("
            "trace_id, thread_id, actor_id, attempt, status, phase, started_at, "
            "last_heartbeat_at, retry_count, initial_dirty_files"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)"
        ),
        (
            trace_id,
            thread_id,
            actor_id,
            attempt,
            "running",
            "init",
            stamp,
            stamp,
            max(0, attempt - 1),
            initial_dirty_files,
        ),
    )


def touch_attempt(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    attempt: int,
    phase: str | None = None,
) -> None:
    stamp = now_iso()
    if phase is None:
        conn.execute(
            (
                "UPDATE agent_run_attempts SET last_heartbeat_at=? "
                "WHERE trace_id=? AND attempt=? AND status='running'"
            ),
            (stamp, trace_id, attempt),
        )
        return
    conn.execute(
        (
            "UPDATE agent_run_attempts SET phase=?, last_heartbeat_at=? "
            "WHERE trace_id=? AND attempt=? AND status='running'"
        ),
        (phase, stamp, trace_id, attempt),
    )


def set_next_retry(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    attempt: int,
    next_retry_at: str,
) -> None:
    conn.execute(
        (
            "UPDATE agent_run_attempts SET next_retry_at=?, last_heartbeat_at=? "
            "WHERE trace_id=? AND attempt=? AND status='running'"
        ),
        (next_retry_at, now_iso(), trace_id, attempt),
    )


def finish_attempt(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    attempt: int,
    status: str,
    failure_kind: str | None = None,
    failure_message: str | None = None,
    final_message_id: str | None = None,
) -> None:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"unsupported terminal status: {status}")
    conn.execute(
        (
            "UPDATE agent_run_attempts SET status=?, ended_at=?, last_heartbeat_at=?, "
            "failure_kind=?, failure_message=?, final_message_id=?, next_retry_at=NULL "
            "WHERE trace_id=? AND attempt=?"
        ),
        (
            status,
            now_iso(),
            now_iso(),
            failure_kind,
            (failure_message or "")[:500],
            final_message_id,
            trace_id,
            attempt,
        ),
    )


def get_success_message_id(conn: sqlite3.Connection, *, trace_id: str) -> str | None:
    row = conn.execute(
        (
            "SELECT final_message_id FROM agent_run_attempts "
            "WHERE trace_id=? AND status='succeeded' AND final_message_id IS NOT NULL "
            "ORDER BY attempt DESC LIMIT 1"
        ),
        (trace_id,),
    ).fetchone()
    if row is None:
        return None
    value = str(row["final_message_id"] or "").strip()
    return value or None


def next_attempt_number(conn: sqlite3.Connection, *, trace_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(attempt), 0) AS max_attempt FROM agent_run_attempts WHERE trace_id=?",
        (trace_id,),
    ).fetchone()
    current = int(row["max_attempt"]) if row is not None and row["max_attempt"] is not None else 0
    return current + 1


def active_running_attempt(conn: sqlite3.Connection, *, trace_id: str) -> int | None:
    row = conn.execute(
        (
            "SELECT attempt FROM agent_run_attempts "
            "WHERE trace_id=? AND status='running' ORDER BY attempt DESC LIMIT 1"
        ),
        (trace_id,),
    ).fetchone()
    if row is None:
        return None
    return int(row["attempt"])


def classify_failure(exc: BaseException) -> str:
    if isinstance(exc, ProviderError):
        text = str(exc).lower()
        if "timeout" in text or "timed out" in text:
            return "timeout"
        return "provider"
    if isinstance(exc, PolicyError):
        return "policy"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return "timeout"
    return "runtime"


def is_retryable_failure(kind: str, exc: BaseException) -> bool:
    if kind in {"policy"}:
        return False
    if kind in {"timeout", "provider", "cancelled", "runtime"}:
        text = str(exc).lower()
        if "unknown tool" in text or "invalid" in text and "argument" in text:
            return False
        return True
    return False


def compute_retry_delay_seconds(base_seconds: int, max_seconds: int, retry_count: int) -> float:
    base = max(1, int(base_seconds))
    max_delay = max(base, int(max_seconds))
    exp = base * (2 ** max(0, retry_count - 1))
    jitter = random.uniform(0.05, 0.35)
    return float(min(max_delay, exp + jitter))


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def compute_phase_stale_seconds(phase: str, settings: Settings) -> int:
    phase_norm = (phase or "").strip().lower()
    if phase_norm == "model.run":
        provider_timeout = max(
            1,
            int(max(settings.openrouter_timeout_seconds, settings.sglang_timeout_seconds)),
        )
        dynamic = int(math.ceil(1.25 * provider_timeout) + 30)
        return max(int(settings.agent_run_model_stale_min_seconds), dynamic)
    if phase_norm == "tool.exec":
        dynamic = int(settings.exec_host_timeout_max_seconds) + 60
        return max(int(settings.agent_run_tool_stale_min_seconds), dynamic)
    if phase_norm in {"state.extract", "finalize"}:
        dynamic = int(settings.state_extraction_timeout_seconds) * 4
        return max(int(settings.agent_run_finalize_stale_min_seconds), dynamic)
    return max(120, int(settings.agent_run_finalize_stale_min_seconds))


def is_attempt_stale(
    row: sqlite3.Row,
    *,
    now: datetime,
    settings: Settings,
) -> bool:
    heartbeat_dt = _parse_ts(str(row["last_heartbeat_at"]))
    started_dt = _parse_ts(str(row["started_at"]))
    if heartbeat_dt is None:
        return False
    phase = str(row["phase"] or "init")
    age_s = (now - heartbeat_dt).total_seconds()
    if age_s >= float(compute_phase_stale_seconds(phase, settings)):
        return True
    if started_dt is None:
        return False
    runtime_s = (now - started_dt).total_seconds()
    return runtime_s >= float(max(300, int(settings.agent_run_stale_hard_cap_seconds)))
