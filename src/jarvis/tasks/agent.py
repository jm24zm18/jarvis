"""Agent task handlers."""

import asyncio
import json
import logging
import re
import shlex
import sqlite3
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jarvis.logging import bind_context, clear_context
from jarvis.tasks import get_task_runner

logger = logging.getLogger(__name__)
from jarvis.config import get_settings  # noqa: E402
from jarvis.db.connection import get_conn  # noqa: E402
from jarvis.db.queries import (  # noqa: E402
    create_feature_request,
    finalize_feature_build_run_by_trace,
    get_attempt_initial_dirty_files,
    get_feature_build_run_by_trace,
    get_latest_feature_build_run_for_thread,
    insert_message,
    now_iso,
    update_feature_build_run,
)
from jarvis.events.models import EventInput  # noqa: E402
from jarvis.events.writer import emit_event, redact_payload  # noqa: E402
from jarvis.ids import new_id  # noqa: E402
from jarvis.memory.skills import SkillsService  # noqa: E402
from jarvis.orchestrator.step import run_agent_step  # noqa: E402
from jarvis.plugins.base import PluginContext  # noqa: E402
from jarvis.plugins.loader import get_loaded_plugins  # noqa: E402
from jarvis.providers.factory import build_fallback_provider, build_primary_provider  # noqa: E402
from jarvis.providers.router import ProviderRouter  # noqa: E402
from jarvis.selfupdate.pipeline import PROTECTED_PATH_PATTERNS  # noqa: E402
from jarvis.tasks.agent_attempts import (  # noqa: E402
    active_running_attempt,
    classify_failure,
    compute_retry_delay_seconds,
    finish_attempt,
    get_success_message_id,
    is_retryable_failure,
    next_attempt_number,
    set_next_retry,
    start_attempt,
    touch_attempt,
)
from jarvis.tasks.feature_build import (  # noqa: E402
    _build_attempt_capsule,
    _capsule_stable_hash,
    _collect_tools_used_from_trace,
    _collect_top_errors_from_trace,
    get_previous_capsule,
    save_capsule,
)
from jarvis.tasks.human_escalation import request_human_escalation  # noqa: E402
from jarvis.tools.host import execute_host_command  # noqa: E402
from jarvis.tools.persona import update_persona  # noqa: E402
from jarvis.tools.registry import ToolRegistry  # noqa: E402
from jarvis.tools.runtime import ToolRuntime  # noqa: E402
from jarvis.tools.session import session_history, session_list, session_send  # noqa: E402
from jarvis.tools.thread_logs import summarize_thread_logs  # noqa: E402
from jarvis.tools.web_search import web_search  # noqa: E402

_DEFAULT_EXEC_HOST_TIMEOUT_S = 120
_BUILD_TEST_GATES_TIMEOUT_S = 600
_BUILD_TEST_GATES_COMMAND = "uv run jarvis test-gates --fail-fast"
_DEGRADED_RESPONSE_PREFIX = "I hit an internal response issue while processing that request."
_TERMINAL_PLACEHOLDER_PREFIX = (
    "I completed tool execution but could not synthesize a final summary."
)
_NEEDS_USER_GUIDANCE_PREFIX = "NEEDS_USER_GUIDANCE:"
_BUILD_OUTPUT_CORRECTION_PREFIX = "BUILD_OUTPUT_CORRECTION:"
_MANUAL_BUILD_RETRY_PHRASES = frozenset(
    {
        "continue",
        "continue please",
        "retry",
        "retry please",
        "try again",
        "go ahead",
        "go ahead please",
        "again",
        "rerun",
        "re run",
    }
)
_WRITE_COMMAND_MARKERS = (
    ">>",
    " > ",
    " touch ",
    " mkdir ",
    "cat <<",
    " apply_patch",
    " sed -i",
    " perl -pi",
    " mv ",
    " cp ",
    " rm ",
)
_GIT_DIFF_TIMEOUT_S = 30
_FEATURE_BUILD_NEVER_EDIT_PATHS = (
    "src/jarvis/selfupdate/pipeline.py",
    "agents/feature_builder/identity.md",
    "src/jarvis/policy/",
    "src/jarvis/auth/",
)


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _command_may_write(command: str) -> bool:
    lowered = f" {command.lower()} "
    return any(marker in lowered for marker in _WRITE_COMMAND_MARKERS)


def _extract_command_paths(command: str) -> list[str]:
    tokens: list[str]
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    paths: list[str] = []
    redir_tokens = {">", ">>", "1>", "2>"}
    for idx, token in enumerate(tokens):
        candidate = token.strip()
        if not candidate:
            continue
        if candidate in redir_tokens and idx + 1 < len(tokens):
            target = tokens[idx + 1].strip()
            if target:
                paths.append(target)
            continue
        if any(candidate.startswith(prefix) for prefix in (">", "1>", "2>")):
            target = candidate.lstrip(">").lstrip("1>").lstrip("2>")
            target = target.strip()
            if target:
                paths.append(target)
            continue
        if candidate.startswith("-"):
            continue
        if "/" in candidate or candidate.startswith("."):
            paths.append(candidate)
    return paths


def _path_matches_never_edit(path: str, never_edit_path: str) -> bool:
    clean_path = path.strip().strip("'\"")
    rule = never_edit_path.strip().strip("'\"")
    if not clean_path or not rule:
        return False
    path_obj = Path(clean_path)
    if not path_obj.is_absolute():
        path_obj = (Path.cwd() / path_obj).resolve()
    absolute = str(path_obj)
    if rule.endswith("/"):
        rel_rule = rule.rstrip("/") + "/"
        return rel_rule in clean_path.replace("\\", "/") or f"/{rel_rule}" in absolute.replace(
            "\\", "/"
        )
    return rule in clean_path.replace("\\", "/") or absolute.replace("\\", "/").endswith(
        "/" + rule
    )


def _path_matches_protected_pattern(path: str) -> bool:
    clean = path.strip().strip("'\"")
    if not clean:
        return False
    path_obj = Path(clean)
    if not path_obj.is_absolute():
        path_obj = (Path.cwd() / path_obj).resolve()
    absolute = str(path_obj)
    return any(pattern.match(absolute) for pattern in PROTECTED_PATH_PATTERNS)


def _trace_attempted_protected_edits(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    never_edit_paths: list[str],
) -> list[str]:
    rows = conn.execute(
        "SELECT payload_json FROM events WHERE trace_id=? AND event_type='tool.call.start'",
        (trace_id,),
    ).fetchall()
    hits: list[str] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        tool = str(payload.get("tool", "")).strip()
        if tool != "exec_host":
            continue
        args = payload.get("arguments", {})
        if not isinstance(args, dict):
            continue
        command = str(args.get("command", "")).strip()
        if not command or not _command_may_write(command):
            continue
        for token in _extract_command_paths(command):
            if any(_path_matches_never_edit(token, item) for item in never_edit_paths) or (
                _path_matches_protected_pattern(token)
            ):
                hit = token.strip()
                if hit and hit not in hits:
                    hits.append(hit)
    return hits


def _has_explicit_noop_with_blockers(text: str) -> bool:
    lowered = text.lower()
    no_change = ("no-op" in lowered) or ("no changes" in lowered) or ("no code changes" in lowered)
    blocked = ("blocker" in lowered) or ("blocked" in lowered)
    return no_change and blocked


def _categorize_build_blocker(
    *,
    gate_checks: dict[str, object],
    top_errors: list[str],
) -> str:
    if str(gate_checks.get("git_diff_error", "")).strip():
        return "git_diff_error"
    if bool(gate_checks.get("message_is_needs_user_guidance")):
        return "needs_user_guidance"
    changed_files = list(gate_checks.get("changed_files") or [])
    if not changed_files:
        if bool(gate_checks.get("explicit_noop_with_blockers")):
            return "explicit_noop_blocked"
        return "no_repo_changes"
    lower_errors = [item.lower() for item in top_errors]
    if any(("policy_deny" in item) or ("permission denied" in item) for item in lower_errors):
        return "policy_denied"
    if top_errors:
        return "tool_error"
    return "unspecified"


def _is_manual_build_retry_intent(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    normalized = " ".join(normalized.split())
    return normalized in _MANUAL_BUILD_RETRY_PHRASES


def _maybe_trigger_manual_feature_build_retry(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    thread_id: str,
    actor_id: str,
) -> str | None:
    if actor_id != "main":
        return None
    # If this trace is already tied to a build run, continue normal flow.
    if get_feature_build_run_by_trace(conn, trace_id):
        return None
    user_row = conn.execute(
        (
            "SELECT id, content FROM messages WHERE thread_id=? AND role='user' "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        (thread_id,),
    ).fetchone()
    if user_row is None:
        return None
    user_message_id = str(user_row["id"])
    user_text = str(user_row["content"] or "")
    if not _is_manual_build_retry_intent(user_text):
        return None

    latest_run = get_latest_feature_build_run_for_thread(conn, thread_id)
    if latest_run is None:
        return None
    if str(latest_run.get("status") or "") != "failed":
        return None
    if str(latest_run.get("retry_state") or "") != "exhausted":
        return None

    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id,
            event_type="feature.build.retry.manual_requested",
            component="feature_build",
            actor_type="system",
            actor_id="feature_build",
            payload_json=json.dumps(
                {
                    "thread_id": thread_id,
                    "previous_run_id": str(latest_run.get("id") or ""),
                    "feature_id": str(latest_run.get("feature_id") or ""),
                    "user_message_id": user_message_id,
                    "user_intent": "manual_retry",
                }
            ),
            payload_redacted_json=json.dumps(
                redact_payload(
                    {
                        "thread_id": thread_id,
                        "previous_run_id": str(latest_run.get("id") or ""),
                        "feature_id": str(latest_run.get("feature_id") or ""),
                        "user_message_id": user_message_id,
                        "user_intent": "manual_retry",
                    }
                )
            ),
        ),
    )

    feature_id = str(latest_run.get("feature_id") or "")
    created_by = str(latest_run.get("created_by") or "").strip() or actor_id
    title = str(latest_run.get("feature_title") or "").strip() or feature_id
    try:
        from jarvis.services.feature_requests import enqueue_feature_build

        result = enqueue_feature_build(
            conn,
            feature_id,
            actor_id=created_by,
            task_runner=get_task_runner(),
        )
    except Exception as exc:
        message_id = insert_message(
            conn,
            thread_id,
            "assistant",
            (
                "I tried to enqueue a manual retry for the exhausted feature build, "
                f"but it failed: {exc.__class__.__name__}: {exc}"
            ),
        )
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="feature.build.retry.manual_enqueue_failed",
                component="feature_build",
                actor_type="system",
                actor_id="feature_build",
                payload_json=json.dumps(
                    {
                        "thread_id": thread_id,
                        "previous_run_id": str(latest_run.get("id") or ""),
                        "feature_id": feature_id,
                        "error": f"{exc.__class__.__name__}: {exc}",
                        "response_message_id": message_id,
                    }
                ),
                payload_redacted_json=json.dumps(
                    redact_payload(
                        {
                            "thread_id": thread_id,
                            "previous_run_id": str(latest_run.get("id") or ""),
                            "feature_id": feature_id,
                            "error": f"{exc.__class__.__name__}: {exc}",
                            "response_message_id": message_id,
                        }
                    )
                ),
            ),
        )
        return message_id

    new_run_id = str(result.get("run_id") or "")
    new_trace_id = str(result.get("trace_id") or "")
    queued = bool(result.get("queued"))
    if queued:
        message = (
            f"Queued manual retry for feature build `{feature_id}` ({title}). "
            f"New run `{new_run_id}` trace `{new_trace_id}`."
        )
        event_type = "feature.build.retry.manual_enqueued"
    else:
        message = (
            f"Manual retry for feature build `{feature_id}` was requested, but enqueue failed. "
            f"Run `{new_run_id}` trace `{new_trace_id}`."
        )
        event_type = "feature.build.retry.manual_enqueue_failed"
    message_id = insert_message(conn, thread_id, "assistant", message)
    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id,
            event_type=event_type,
            component="feature_build",
            actor_type="system",
            actor_id="feature_build",
            payload_json=json.dumps(
                {
                    "thread_id": thread_id,
                    "feature_id": feature_id,
                    "previous_run_id": str(latest_run.get("id") or ""),
                    "new_run_id": new_run_id,
                    "new_trace_id": new_trace_id,
                    "queued": queued,
                    "response_message_id": message_id,
                }
            ),
            payload_redacted_json=json.dumps(
                redact_payload(
                    {
                        "thread_id": thread_id,
                        "feature_id": feature_id,
                        "previous_run_id": str(latest_run.get("id") or ""),
                        "new_run_id": new_run_id,
                        "new_trace_id": new_trace_id,
                        "queued": queued,
                        "response_message_id": message_id,
                    }
                )
            ),
        ),
    )
    return message_id


def _git_changed_files(baseline: set[str] | None = None) -> tuple[list[str], str | None]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
            timeout=_GIT_DIFF_TIMEOUT_S,
            check=False,
        )
    except Exception as exc:
        return [], f"git diff failed: {exc.__class__.__name__}: {exc}"
    if proc.returncode != 0:
        return [], f"git diff failed: {proc.stderr.strip() or proc.stdout.strip()}"
    files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if baseline:
        files = [path for path in files if path not in baseline]
    return files, None


def _capture_dirty_files_snapshot() -> tuple[set[str], str | None]:
    files, err = _git_changed_files()
    return set(files), err


def _serialize_dirty_files(files: set[str]) -> str | None:
    try:
        return json.dumps(sorted(files))
    except Exception:
        return None


def _is_placeholder_terminal_message(text: str) -> bool:
    clean = text.strip()
    if not clean:
        return True
    return clean.startswith(_TERMINAL_PLACEHOLDER_PREFIX)


def _evaluate_feature_build_deliverable_gate(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    message_id: str | None,
    settings,
) -> tuple[bool, str | None, dict[str, object]]:
    checks: dict[str, object] = {}
    never_edit_paths = list(_FEATURE_BUILD_NEVER_EDIT_PATHS)
    protected_hits = _trace_attempted_protected_edits(
        conn,
        trace_id=trace_id,
        never_edit_paths=never_edit_paths,
    )
    checks["protected_path_edit_attempts"] = protected_hits
    if protected_hits:
        return False, "protected_path_edit_attempted", checks

    message_text = ""
    if message_id:
        row = conn.execute(
            "SELECT content FROM messages WHERE id=? LIMIT 1",
            (message_id,),
        ).fetchone()
        if row is not None:
            message_text = str(row["content"] or "").strip()
    checks["message_present"] = bool(message_text)
    checks["message_is_placeholder"] = _is_placeholder_terminal_message(message_text)
    if not message_text or _is_placeholder_terminal_message(message_text):
        return False, "insufficient_deliverable_evidence", checks

    # Agent explicitly requests human guidance — treat as terminal pass so it doesn't loop.
    checks["message_is_needs_user_guidance"] = message_text.startswith(
        _NEEDS_USER_GUIDANCE_PREFIX
    )
    if bool(checks["message_is_needs_user_guidance"]):
        return True, "needs_user_guidance", checks

    baseline_list = get_attempt_initial_dirty_files(conn, trace_id=trace_id)
    baseline_set = set(baseline_list or [])
    changed_files, diff_error = _git_changed_files(baseline=baseline_set)
    checks["git_diff_error"] = diff_error or ""
    checks["changed_files"] = changed_files
    checks["explicit_noop_with_blockers"] = _has_explicit_noop_with_blockers(message_text)
    if diff_error:
        return False, "insufficient_deliverable_evidence", checks

    allowed_changes: list[str] = []
    for path in changed_files:
        if any(_path_matches_never_edit(path, item) for item in never_edit_paths):
            continue
        if _path_matches_protected_pattern(path):
            continue
        allowed_changes.append(path)
    checks["allowed_scope_changes"] = allowed_changes
    if allowed_changes:
        if int(settings.feature_build_require_test_gates) == 1:
            tg_ran = _test_gates_executed_in_trace(conn, trace_id)
            checks["test_gates_executed"] = tg_ran
            if not tg_ran:
                return False, "test_gates_not_executed", checks
        return True, None, checks
    if bool(checks["explicit_noop_with_blockers"]):
        return True, None, checks
    return False, "insufficient_deliverable_evidence", checks


def _terminal_outcome_reason(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    message_id: str | None,
) -> str | None:
    # Check explicit events first — they carry the most specific reason.
    row = conn.execute(
        (
            "SELECT event_type, payload_json FROM events "
            "WHERE trace_id=? AND event_type IN ("
            "'agent.response.leak_blocked', 'agent.response.degraded', 'agent.response.incomplete'"
            ") "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        (trace_id,),
    ).fetchone()
    if row is not None:
        event_type = str(row["event_type"])
        if event_type == "agent.response.leak_blocked":
            return "final_output_leak_guard"
        if event_type == "agent.response.incomplete":
            return "incomplete_terminal_response"
        if event_type == "agent.response.degraded":
            reason = "unknown"
            try:
                payload = json.loads(str(row["payload_json"]))
                reason = str(payload.get("reason") or "unknown")
            except Exception:
                reason = "unknown"
            return reason

    # Fall back to message-prefix detection when no explicit event was emitted.
    if message_id:
        msg_row = conn.execute(
            "SELECT content FROM messages WHERE id=? LIMIT 1",
            (message_id,),
        ).fetchone()
        if msg_row is not None:
            message_text = str(msg_row["content"] or "").strip()
            if message_text.startswith(_DEGRADED_RESPONSE_PREFIX):
                return "degraded_message_prefix"

    return None


def _is_build_test_gates_command(command: str) -> bool:
    normalized = " ".join(command.strip().split()).lower()
    return normalized == _BUILD_TEST_GATES_COMMAND


def _test_gates_executed_in_trace(conn: sqlite3.Connection, trace_id: str) -> bool:
    """Return True if test-gates was called via exec_host in this trace."""
    rows = conn.execute(
        "SELECT payload_json FROM events "
        "WHERE trace_id=? AND event_type='tool.call.start' LIMIT 200",
        (trace_id,),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
            if payload.get("tool") != "exec_host":
                continue
            cmd = str(payload.get("arguments", {}).get("command", "")).strip()
            if _is_build_test_gates_command(cmd):
                return True
        except Exception:
            continue
    return False


def _apply_capsule_repeat_fail_fast(
    *,
    conn: sqlite3.Connection,
    run_id: str,
    trace_id: str,
    attempt_count: int,
    gate_checks: dict[str, Any],
    message_id: str | None,
    settings: Any,
    emit_build_event: Any,
    max_attempts: int,
) -> bool:
    """Create an attempt capsule, check for hash repeat, and deny retry if stuck.

    Returns True if the retry should be denied (repeat fail-fast triggered),
    False if the retry should proceed normally.
    """
    try:
        changed_files: list[str] = list(gate_checks.get("changed_files") or [])
        tools_used = _collect_tools_used_from_trace(conn, trace_id)
        top_errors = _collect_top_errors_from_trace(conn, trace_id)

        # Extract blockers summary from message text.
        blockers_summary = ""
        message_text = ""
        if message_id:
            msg_row = conn.execute(
                "SELECT content FROM messages WHERE id=? LIMIT 1",
                (message_id,),
            ).fetchone()
            if msg_row is not None:
                message_text = str(msg_row["content"] or "").strip()
                # Use message tail as blockers context (up to 300 chars).
                blockers_summary = (
                    message_text[-300:] if len(message_text) > 300 else message_text
                )
        blocker_category = _categorize_build_blocker(
            gate_checks=gate_checks,
            top_errors=top_errors,
        )

        capsule = _build_attempt_capsule(
            run_id=run_id,
            trace_id=trace_id,
            attempt=attempt_count,
            reason="insufficient_deliverable_evidence",
            changed_files=changed_files,
            tools_used=tools_used,
            top_errors=top_errors,
            blockers_summary=blockers_summary,
            blocker_category=blocker_category,
            next_action="retry",
        )
        current_hash = _capsule_stable_hash(capsule)

        # Check previous capsule for repeat.
        prev_capsule = get_previous_capsule(conn, run_id)
        prev_hash = ""
        if prev_capsule is not None:
            try:
                prev_hash = _capsule_stable_hash(prev_capsule)
            except Exception:
                prev_hash = ""

        repeat_limit = max(1, int(settings.feature_build_repeat_limit))
        if prev_hash and prev_hash == current_hash and attempt_count >= repeat_limit:
            # Identical situation: stop retrying.
            update_feature_build_run(
                conn,
                run_id,
                status="failed",
                retry_state="exhausted",
                next_retry_at="",
                summary=(
                    f"Build stopped after {attempt_count} attempts with identical outcome "
                    f"(repeat fail-fast): insufficient_deliverable_evidence."
                ),
                last_failure_reason="insufficient_deliverable_evidence",
                active_attempt=attempt_count,
                last_progress_at=now_iso(),
                last_event_type="feature.build.retry.denied",
                last_trace_id=trace_id,
                terminal_reason="FAILED_REPEAT",
            )
            emit_build_event(
                "feature.build.retry.denied",
                {
                    "run_id": run_id,
                    "attempt": attempt_count,
                    "max_attempts": max_attempts,
                    "reason": "insufficient_deliverable_evidence",
                    "policy_action": "repeat_fail_fast",
                    "capsule_hash": current_hash,
                },
            )
            # Save capsule even on denial so context is preserved.
            save_capsule(conn, run_id, capsule, current_hash)
            return True

        # Save capsule for the next attempt.
        save_capsule(conn, run_id, capsule, current_hash)
        emit_build_event(
            "feature.build.evidence.logged",
            {
                "run_id": run_id,
                "attempt": attempt_count,
                "capsule_hash": current_hash,
                "changed_files_count": len(changed_files),
                "tools_used_count": len(tools_used),
                "top_errors_count": len(top_errors),
            },
        )
    except Exception:
        logger.exception(
            "capsule repeat fail-fast check failed; allowing retry: run_id=%s trace_id=%s",
            run_id,
            trace_id,
        )
    return False


def _finalize_feature_build_run_from_trace_result(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    message_id: str | None = None,
    failure_kind: str | None = None,
    failure_error: str | None = None,
) -> None:
    """Finalize feature-build run (if any) linked to trace_id."""
    run = get_feature_build_run_by_trace(conn, trace_id)
    if run is None:
        return
    run_id = str(run["id"])
    thread_id = str(run.get("thread_id") or "") or None
    attempt_count = max(1, int(run.get("attempt_count", 1)))
    max_attempts = max(attempt_count, int(run.get("max_attempts", attempt_count)))
    previous_reason = str(run.get("last_failure_reason") or "").strip()
    settings = get_settings()

    def _emit_build_event(event_type: str, payload: dict[str, object]) -> None:
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type=event_type,
                component="feature_build",
                actor_type="system",
                actor_id="feature_build",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )

    def _retry_delay_seconds(next_attempt: int) -> int:
        raw = str(settings.feature_build_retry_backoff_seconds).strip()
        values: list[int] = []
        for part in raw.split(","):
            item = part.strip()
            if not item:
                continue
            try:
                values.append(max(1, int(item)))
            except ValueError:
                continue
        if not values:
            values = [30, 120, 300, 600]
        idx = max(0, min(len(values) - 1, next_attempt - 2))
        return values[idx]

    def _schedule_retry(reason: str, summary: str) -> bool:
        consecutive_reason_count = 2 if previous_reason and previous_reason == reason else 1
        if (
            reason == "placeholder_response_after_tool_loop"
            and int(settings.feature_build_fail_fast_placeholder_repeat) == 1
            and consecutive_reason_count >= 2
        ):
            update_feature_build_run(
                conn,
                run_id,
                status="failed",
                retry_state="exhausted",
                next_retry_at="",
                summary=f"Build failed after repeated placeholder degradation: {summary}",
                last_failure_reason=reason,
                active_attempt=attempt_count,
                last_progress_at=now_iso(),
                last_event_type="feature.build.retry.denied",
                last_trace_id=trace_id,
                terminal_reason=reason,
            )
            _emit_build_event(
                "feature.build.retry.denied",
                {
                    "run_id": run_id,
                    "attempt": attempt_count,
                    "max_attempts": max_attempts,
                    "reason": reason,
                    "policy_action": "fail_fast",
                    "consecutive_reason_count": consecutive_reason_count,
                },
            )
            return False

        next_attempt = attempt_count + 1
        if next_attempt > max_attempts:
            update_feature_build_run(
                conn,
                run_id,
                status="failed",
                retry_state="exhausted",
                next_retry_at="",
                summary=f"Build failed after {attempt_count} attempts: {summary}",
                last_failure_reason=reason,
                active_attempt=attempt_count,
                last_progress_at=now_iso(),
                last_event_type="feature.build.retry.exhausted",
                last_trace_id=trace_id,
                terminal_reason=reason,
            )
            _emit_build_event(
                "feature.build.retry.exhausted",
                {
                    "run_id": run_id,
                    "attempt_count": attempt_count,
                    "max_attempts": max_attempts,
                    "reason": reason,
                },
            )
            return False

        delay = _retry_delay_seconds(next_attempt)
        next_retry_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
        update_feature_build_run(
            conn,
            run_id,
            status="running",
            attempt_count=next_attempt,
            retry_state="scheduled",
            next_retry_at=next_retry_at,
            summary=(
                f"Retry scheduled ({next_attempt}/{max_attempts}) in {delay}s "
                f"after degraded outcome: {summary}"
            ),
            last_failure_reason=reason,
            active_attempt=next_attempt,
            last_progress_at=now_iso(),
            last_event_type="feature.build.retry.scheduled",
            last_trace_id=trace_id,
            terminal_reason=reason,
        )
        _emit_build_event(
            "feature.build.retry.scheduled",
            {
                "run_id": run_id,
                "attempt_count": next_attempt,
                "max_attempts": max_attempts,
                "reason": reason,
                "next_retry_at": next_retry_at,
            },
        )
        return True

    def _emit_build_output_correction(
        *,
        prior_message_id: str,
        verification_failures: list[str],
        changed_files_count: int,
        retry_state: str,
    ) -> None:
        if thread_id is None:
            return
        exists = conn.execute(
            (
                "SELECT id FROM messages WHERE thread_id=? AND role='system' "
                "AND content LIKE ? ORDER BY created_at DESC LIMIT 1"
            ),
            (thread_id, f"{_BUILD_OUTPUT_CORRECTION_PREFIX}%{prior_message_id}%"),
        ).fetchone()
        if exists is not None:
            return
        correction_id = new_id("msg")
        correction_text = (
            f"{_BUILD_OUTPUT_CORRECTION_PREFIX} previous_message_id={prior_message_id}\n"
            "Build output could not be verified against repository evidence. "
            "The prior completion claim is not accepted for this run.\n"
            f"verification_failures={','.join(verification_failures)}\n"
            f"changed_files_count={changed_files_count}\n"
            f"retry_state={retry_state}"
        )
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
            (correction_id, thread_id, "system", correction_text, now_iso()),
        )
        _emit_build_event(
            "feature.build.output.corrected",
            {
                "run_id": run_id,
                "attempt": attempt_count,
                "prior_message_id": prior_message_id,
                "correction_message_id": correction_id,
                "verification_failures": verification_failures,
                "changed_files_count": changed_files_count,
                "retry_state": retry_state,
            },
        )

    if failure_kind is not None:
        detail = str(failure_error or "").strip()
        if detail:
            summary = f"Build failed: agent step {failure_kind}: {detail}"
        else:
            summary = f"Build failed: agent step {failure_kind}."
        finalize_feature_build_run_by_trace(conn, trace_id, status="failed", summary=summary)
        update_feature_build_run(
            conn,
            run_id,
            last_progress_at=now_iso(),
            last_event_type="feature.build.terminal_synthesis",
            last_trace_id=trace_id,
            terminal_reason=f"agent_step_{failure_kind}",
        )
        _emit_build_event(
            "feature.build.terminal_synthesis",
            {
                "run_id": run_id,
                "attempt": attempt_count,
                "reason": f"agent_step_{failure_kind}",
                "deliverable_passed": False,
            },
        )
        return

    quota_row = conn.execute(
        (
            "SELECT 1 FROM events WHERE trace_id=? AND event_type='model.fallback' "
            "AND json_extract(payload_json, '$.primary_failure_kind')='quota_retryable' LIMIT 1"
        ),
        (trace_id,),
    ).fetchone()
    terminal_reason = _terminal_outcome_reason(conn, trace_id=trace_id, message_id=message_id)
    gate_passed = False
    gate_reason: str | None = None
    gate_checks: dict[str, object] = {}
    message_text = ""
    if message_id:
        row = conn.execute(
            "SELECT content FROM messages WHERE id=? LIMIT 1", (message_id,)
        ).fetchone()
        if row is not None:
            message_text = str(row["content"] or "").strip()
    timeout_count = int(
        conn.execute(
            (
                "SELECT COUNT(*) AS n FROM events WHERE trace_id=? "
                "AND event_type='state.extraction.failed' "
                "AND json_extract(payload_json, '$.primary_failure_kind')='timeout'"
            ),
            (trace_id,),
        ).fetchone()["n"]
    )
    if timeout_count > 0:
        _emit_build_event(
            "feature.build.state_extraction.timeout_observed",
            {
                "run_id": run_id,
                "attempt": attempt_count,
                "timeout_failure_count": timeout_count,
                "non_blocking": True,
            },
        )

    if (
        terminal_reason is None
        and int(settings.feature_build_deliverable_gate_enabled) == 1
    ):
        gate_passed, gate_reason, gate_checks = _evaluate_feature_build_deliverable_gate(
            conn,
            trace_id=trace_id,
            message_id=message_id,
            settings=settings,
        )
        if gate_passed and gate_reason == "needs_user_guidance":
            # Agent explicitly escalated — stop retrying, notify user.
            _needs_guidance_text = ""
            if message_id:
                _ng_row = conn.execute(
                    "SELECT content FROM messages WHERE id=? LIMIT 1", (message_id,)
                ).fetchone()
                if _ng_row is not None:
                    _needs_guidance_text = str(_ng_row["content"] or "").strip()
            finalize_feature_build_run_by_trace(
                conn,
                trace_id,
                status="failed",
                summary=(
                    "Build stopped: agent requested human guidance.\n"
                    + _needs_guidance_text[:500]
                ),
            )
            update_feature_build_run(
                conn,
                run_id,
                status="failed",
                retry_state="exhausted",
                next_retry_at="",
                last_progress_at=now_iso(),
                last_event_type="feature.build.needs_user_guidance",
                last_trace_id=trace_id,
                terminal_reason="needs_user_guidance",
            )
            _emit_build_event(
                "feature.build.needs_user_guidance",
                {
                    "run_id": run_id,
                    "attempt": attempt_count,
                    "message": _needs_guidance_text[:500],
                },
            )
            return
        if not gate_passed and gate_reason is not None:
            terminal_reason = gate_reason
            _emit_build_event(
                "feature.build.deliverable_gate.failed",
                {
                    "run_id": run_id,
                    "attempt": attempt_count,
                    "reason": gate_reason,
                    "checks": gate_checks,
                },
            )

    if terminal_reason is not None:
        retryable_reasons = {
            "placeholder_response_after_tool_loop",
            "provider_error_terminal_synthesis",
            "placeholder_response_after_terminal_synthesis",
            "final_output_leak_guard",
            "incomplete_terminal_response",
            "degraded_message_prefix",
            "quota_retryable",
            "insufficient_deliverable_evidence",
            "test_gates_not_executed",
        }
        retryable_reason: str | None = (
            terminal_reason if terminal_reason in retryable_reasons else None
        )
        if quota_row is not None:
            retryable_reason = "quota_retryable"
        summary = f"Build failed: terminal response ({terminal_reason})."
        _emit_build_event(
            "feature.build.terminal_synthesis",
            {
                "run_id": run_id,
                "attempt": attempt_count,
                "reason": terminal_reason,
                "deliverable_passed": False,
            },
        )
        update_feature_build_run(
            conn,
            run_id,
            last_progress_at=now_iso(),
            last_event_type="feature.build.terminal_synthesis",
            last_trace_id=trace_id,
            terminal_reason=terminal_reason,
        )
        if int(settings.feature_build_retry_on_degraded) == 1 and retryable_reason is not None:
            # --- Capsule-based repeat fail-fast (insufficient_deliverable_evidence) ---
            if (
                retryable_reason == "insufficient_deliverable_evidence"
                and int(settings.feature_build_attempt_capsules_enabled) == 1
            ):
                _capsule_deny = _apply_capsule_repeat_fail_fast(
                    conn=conn,
                    run_id=run_id,
                    trace_id=trace_id,
                    attempt_count=attempt_count,
                    gate_checks=gate_checks,
                    message_id=message_id,
                    settings=settings,
                    emit_build_event=_emit_build_event,
                    max_attempts=max_attempts,
                )
                if _capsule_deny:
                    if (
                        message_id
                        and message_text
                        and not _is_placeholder_terminal_message(message_text)
                    ):
                        _emit_build_output_correction(
                            prior_message_id=message_id,
                            verification_failures=[
                                "insufficient_deliverable_evidence",
                                "no_repo_changes",
                            ],
                            changed_files_count=len(list(gate_checks.get("changed_files") or [])),
                            retry_state="exhausted",
                        )
                    return
            scheduled = _schedule_retry(retryable_reason, summary)
            if (
                message_id
                and message_text
                and not _is_placeholder_terminal_message(message_text)
                and retryable_reason == "insufficient_deliverable_evidence"
            ):
                failures: list[str] = ["insufficient_deliverable_evidence"]
                if not list(gate_checks.get("changed_files") or []):
                    failures.append("no_repo_changes")
                if not bool(gate_checks.get("explicit_noop_with_blockers")):
                    failures.append("no_explicit_noop_blockers")
                _emit_build_output_correction(
                    prior_message_id=message_id,
                    verification_failures=failures,
                    changed_files_count=len(list(gate_checks.get("changed_files") or [])),
                    retry_state="scheduled" if scheduled else "exhausted",
                )
            return

        finalize_feature_build_run_by_trace(conn, trace_id, status="failed", summary=summary)
        if (
            message_id
            and message_text
            and not _is_placeholder_terminal_message(message_text)
            and terminal_reason == "insufficient_deliverable_evidence"
        ):
            _emit_build_output_correction(
                prior_message_id=message_id,
                verification_failures=[
                    "insufficient_deliverable_evidence",
                    "no_repo_changes",
                ],
                changed_files_count=len(list(gate_checks.get("changed_files") or [])),
                retry_state="exhausted",
            )
        if int(settings.feature_build_escalate_on_exhausted) == 1:
            thread_id_for_escalation = str(run.get("thread_id") or "").strip()
            if thread_id_for_escalation:
                request_human_escalation(
                    thread_id=thread_id_for_escalation,
                    trace_id=trace_id,
                    requested_by_actor_id="system",
                    source_agent_id="main",
                    reason=f"feature_build_{terminal_reason}",
                    message=(
                        "Feature build exhausted retries and needs human intervention.\n"
                        f"Run: {run_id}\nFeature: {run.get('feature_id')}\nTrace: {trace_id}\n"
                        f"Summary: {summary}"
                    ),
                    priority="high",
                )
        return

    finalize_feature_build_run_by_trace(
        conn,
        trace_id,
        status="succeeded",
        summary="Build completed successfully.",
    )
    update_feature_build_run(
        conn,
        run_id,
        last_progress_at=now_iso(),
        last_event_type="feature.build.terminal_synthesis",
        last_trace_id=trace_id,
        terminal_reason="ok",
    )
    _emit_build_event(
        "feature.build.terminal_synthesis",
        {
            "run_id": run_id,
            "attempt": attempt_count,
            "reason": "ok",
            "deliverable_passed": (
                gate_passed or int(settings.feature_build_deliverable_gate_enabled) == 0
            ),
        },
    )
    if attempt_count > 1:
        _emit_build_event(
            "feature.build.retry.succeeded_after_retry",
            {
                "run_id": run_id,
                "attempt_count": attempt_count,
                "max_attempts": max_attempts,
            },
        )


def agent_step(trace_id: str, thread_id: str, actor_id: str = "main") -> str:
    clear_context()
    bind_context(trace_id=trace_id, thread_id=thread_id, actor_id=actor_id)
    settings = get_settings()

    router = ProviderRouter(
        build_primary_provider(settings),
        build_fallback_provider(settings),
    )

    max_attempts = max(1, int(settings.agent_step_max_attempts))
    retry_base_seconds = max(1, int(settings.agent_step_retry_base_seconds))
    retry_max_seconds = max(retry_base_seconds, int(settings.agent_step_retry_max_seconds))

    with get_conn() as conn:
        existing_success = get_success_message_id(conn, trace_id=trace_id)
        if existing_success is not None:
            return existing_success

    attempt = 1
    while attempt <= max_attempts:
        with get_conn() as conn:
            existing_success = get_success_message_id(conn, trace_id=trace_id)
            if existing_success is not None:
                return existing_success
            running_attempt = active_running_attempt(conn, trace_id=trace_id)
            if running_attempt is not None:
                logger.warning(
                    "Trace %s already has running attempt=%d; skipping duplicate execution",
                    trace_id,
                    running_attempt,
                )
                raise RuntimeError(f"trace already running: {trace_id}")
            attempt = next_attempt_number(conn, trace_id=trace_id)
            baseline_files, _ = _capture_dirty_files_snapshot()
            baseline_json = _serialize_dirty_files(baseline_files)
            start_attempt(
                conn,
                trace_id=trace_id,
                thread_id=thread_id,
                actor_id=actor_id,
                attempt=attempt,
                initial_dirty_files=baseline_json,
            )
            conn.execute(
                (
                    "INSERT INTO web_notifications("
                    "thread_id, event_type, payload_json, created_at"
                    ") VALUES(?,?,?,?)"
                ),
                (
                    thread_id,
                    "agent.thinking",
                    json.dumps({"thread_id": thread_id, "agent_id": actor_id, "attempt": attempt}),
                    now_iso(),
                ),
            )

        try:
            with get_conn() as conn:
                attempt_no = attempt

                def notify_trace(
                    event_type: str,
                    payload: dict[str, object],
                    _attempt: int = attempt_no,
                ) -> None:
                    phase = None
                    if event_type.startswith("model.run") or event_type == "model.fallback":
                        phase = "model.run"
                    elif event_type.startswith("tool.call"):
                        phase = "tool.exec"
                    elif event_type.startswith("state.extraction"):
                        phase = "state.extract"
                    elif event_type.startswith("agent.response"):
                        phase = "finalize"
                    if phase is not None:
                        touch_attempt(conn, trace_id=trace_id, attempt=_attempt, phase=phase)
                    else:
                        touch_attempt(conn, trace_id=trace_id, attempt=_attempt)
                    _notify_trace_event(
                        conn=conn,
                        thread_id=thread_id,
                        trace_id=trace_id,
                        event_type=event_type,
                        payload=payload,
                    )

                def progress_trace(
                    event_type: str,
                    payload: dict[str, object],
                    _attempt: int = attempt_no,
                ) -> None:
                    del event_type
                    phase = str(payload.get("phase", "")).strip() or "init"
                    touch_attempt(conn, trace_id=trace_id, attempt=_attempt, phase=phase)

                registry = _build_registry(conn, trace_id, thread_id, actor_id)
                runtime = ToolRuntime(registry)
                touch_attempt(conn, trace_id=trace_id, attempt=attempt, phase="init")
                manual_retry_message_id = _maybe_trigger_manual_feature_build_retry(
                    conn,
                    trace_id=trace_id,
                    thread_id=thread_id,
                    actor_id=actor_id,
                )
                if manual_retry_message_id:
                    finish_attempt(
                        conn,
                        trace_id=trace_id,
                        attempt=attempt_no,
                        status="succeeded",
                        final_message_id=manual_retry_message_id,
                    )
                    _notify_trace_event(
                        conn=conn,
                        thread_id=thread_id,
                        trace_id=trace_id,
                        event_type="agent.step.end",
                        payload={
                            "attempt": attempt_no,
                            "message_id": manual_retry_message_id,
                            "manual_feature_build_retry": True,
                        },
                    )
                    return manual_retry_message_id
                message_id = asyncio.run(
                    run_agent_step(
                        conn=conn,
                        router=router,
                        runtime=runtime,
                        thread_id=thread_id,
                        trace_id=trace_id,
                        actor_id=actor_id,
                        notify_fn=notify_trace,
                        progress_fn=progress_trace,
                    )
                )

                existing_success = get_success_message_id(conn, trace_id=trace_id)
                if existing_success is not None and existing_success != message_id:
                    finish_attempt(
                        conn,
                        trace_id=trace_id,
                        attempt=attempt_no,
                        status="abandoned",
                        failure_kind="duplicate_guard",
                        failure_message="trace already completed by another attempt",
                    )
                    _notify_trace_event(
                        conn=conn,
                        thread_id=thread_id,
                        trace_id=trace_id,
                        event_type="agent.step.failed",
                        payload={
                            "attempt": attempt_no,
                            "failure_kind": "duplicate_guard",
                            "error": "trace already completed by another attempt",
                        },
                    )
                    _finalize_feature_build_run_from_trace_result(
                        conn,
                        trace_id=trace_id,
                        message_id=existing_success,
                    )
                    return existing_success

                finish_attempt(
                    conn,
                    trace_id=trace_id,
                    attempt=attempt_no,
                    status="succeeded",
                    final_message_id=message_id,
                )
                _notify_trace_event(
                    conn=conn,
                    thread_id=thread_id,
                    trace_id=trace_id,
                    event_type="agent.step.end",
                    payload={"attempt": attempt_no, "message_id": message_id},
                )
                _finalize_feature_build_run_from_trace_result(
                    conn,
                    trace_id=trace_id,
                    message_id=message_id,
                )

                if actor_id == "main":
                    conn.execute(
                        (
                            "INSERT INTO web_notifications("
                            "thread_id, event_type, payload_json, created_at"
                            ") "
                            "VALUES(?,?,?,?)"
                        ),
                        (
                            thread_id,
                            "message.new",
                            json.dumps({"message_id": message_id, "agent_id": actor_id}),
                            now_iso(),
                        ),
                    )
                conn.execute(
                    (
                        "INSERT INTO web_notifications("
                        "thread_id, event_type, payload_json, created_at"
                        ") VALUES(?,?,?,?)"
                    ),
                    (
                        thread_id,
                        "agent.done",
                        json.dumps({"thread_id": thread_id, "agent_id": actor_id}),
                        now_iso(),
                    ),
                )
                if actor_id == "main":
                    channel_row = conn.execute(
                        (
                            "SELECT c.channel_type FROM threads t "
                            "JOIN channels c ON c.id=t.channel_id WHERE t.id=? LIMIT 1"
                        ),
                        (thread_id,),
                    ).fetchone()
                    channel_type = (
                        str(channel_row["channel_type"]) if channel_row is not None else ""
                    )
                    if channel_type and channel_type != "web":
                        def _emit(evt_type: str, evt_payload: dict[str, object]) -> None:
                            emit_event(
                                conn,
                                EventInput(
                                    trace_id=trace_id,
                                    span_id=new_id("spn"),
                                    parent_span_id=None,
                                    thread_id=thread_id,
                                    event_type=evt_type,
                                    component="agent",
                                    actor_type="system",
                                    actor_id="agent",
                                    payload_json=json.dumps(evt_payload),
                                    payload_redacted_json=json.dumps(redact_payload(evt_payload)),
                                ),
                            )

                        _emit(
                            "channel.dispatch.enqueue.start",
                            {
                                "message_id": message_id,
                                "channel_type": channel_type,
                            },
                        )

                        ok = get_task_runner().send_task(
                            "jarvis.tasks.channel.send_channel_message",
                            kwargs={
                                "thread_id": thread_id,
                                "message_id": message_id,
                                "channel_type": channel_type,
                            },
                            queue="tools_io",
                        )
                        if ok:
                            _emit(
                                "channel.dispatch.enqueue.end",
                                {
                                    "message_id": message_id,
                                    "channel_type": channel_type,
                                },
                            )
                        else:
                            logger.warning(
                                "Failed to dispatch %s send task "
                                "thread_id=%s message_id=%s trace_id=%s",
                                channel_type,
                                thread_id,
                                message_id,
                                trace_id,
                            )
                            _emit(
                                "channel.dispatch.enqueue.failed",
                                {
                                    "message_id": message_id,
                                    "channel_type": channel_type,
                                    "attempt": 1,
                                    "queue": "tools_io",
                                },
                            )
                            fallback_ok = get_task_runner().send_task(
                                "jarvis.tasks.channel.send_channel_message",
                                kwargs={
                                    "thread_id": thread_id,
                                    "message_id": message_id,
                                    "channel_type": channel_type,
                                },
                                queue="tools_io_retry",
                            )
                            if not fallback_ok:
                                logger.error(
                                    "Fallback dispatch to tools_io_retry failed for %s "
                                    "thread_id=%s message_id=%s trace_id=%s",
                                    channel_type,
                                    thread_id,
                                    message_id,
                                    trace_id,
                                )
                                _emit(
                                    "channel.dispatch.enqueue.failed",
                                    {
                                        "message_id": message_id,
                                        "channel_type": channel_type,
                                        "attempt": 2,
                                        "queue": "tools_io_retry",
                                    },
                                )
                                from jarvis.routes.health import increment_metric
                                increment_metric("task_runner_enqueue_failures_total")
                else:
                    # Worker auto-reply: send result back to main agent
                    row = conn.execute(
                        "SELECT content FROM messages WHERE id=?", (message_id,)
                    ).fetchone()
                    if row is not None:
                        result_text = str(row["content"])
                        session_send(
                            conn,
                            session_id=thread_id,
                            to_agent_id="main",
                            message=result_text,
                            trace_id=trace_id,
                            from_agent_id=actor_id,
                        )
                        ok = get_task_runner().send_task(
                            "jarvis.tasks.agent.agent_step",
                            kwargs={
                                "trace_id": trace_id,
                                "thread_id": thread_id,
                                "actor_id": "main",
                            },
                            queue="agent_priority",
                        )
                        if not ok:
                            logger.error("Failed to dispatch main agent reply task")
                return message_id
        except Exception as exc:
            failure_kind = classify_failure(exc)
            retryable = is_retryable_failure(failure_kind, exc) and attempt < max_attempts
            with get_conn() as conn:
                if retryable:
                    delay_s = compute_retry_delay_seconds(
                        retry_base_seconds,
                        retry_max_seconds,
                        attempt,
                    )
                    retry_at = datetime.now(UTC) + timedelta(seconds=delay_s)
                    set_next_retry(
                        conn,
                        trace_id=trace_id,
                        attempt=attempt,
                        next_retry_at=retry_at.isoformat(),
                    )
                    finish_attempt(
                        conn,
                        trace_id=trace_id,
                        attempt=attempt,
                        status="failed",
                        failure_kind=failure_kind,
                        failure_message=str(exc),
                    )
                    _notify_trace_event(
                        conn=conn,
                        thread_id=thread_id,
                        trace_id=trace_id,
                        event_type="agent.step.retried",
                        payload={
                            "attempt": attempt,
                            "failure_kind": failure_kind,
                            "error": str(exc)[:500],
                            "next_retry_at": retry_at.isoformat(),
                        },
                    )
                else:
                    status = "retry_exhausted" if attempt >= max_attempts else "failed"
                    finish_attempt(
                        conn,
                        trace_id=trace_id,
                        attempt=attempt,
                        status=status,
                        failure_kind=failure_kind,
                        failure_message=str(exc),
                    )
                    _notify_trace_event(
                        conn=conn,
                        thread_id=thread_id,
                        trace_id=trace_id,
                        event_type=(
                            "agent.step.retry_exhausted"
                            if status == "retry_exhausted"
                            else "agent.step.failed"
                        ),
                        payload={
                            "attempt": attempt,
                            "failure_kind": failure_kind,
                            "error": str(exc)[:500],
                        },
                    )
                    _finalize_feature_build_run_from_trace_result(
                        conn,
                        trace_id=trace_id,
                        failure_kind=failure_kind,
                        failure_error=str(exc),
                    )
            if not retryable:
                raise
            time.sleep(delay_s)
            attempt += 1

    raise RuntimeError(f"agent step exhausted retries trace={trace_id}")


def _notify_trace_event(
    conn: sqlite3.Connection,
    thread_id: str,
    trace_id: str,
    event_type: str,
    payload: dict[str, object],
) -> None:
    created_at = now_iso()
    enriched_payload = dict(payload)
    enriched_payload["trace_id"] = trace_id
    enriched_payload["created_at"] = created_at
    conn.execute(
        "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
        "VALUES(?,?,?,?)",
        (
            thread_id,
            f"trace.{event_type}",
            json.dumps(enriched_payload),
            created_at,
        ),
    )
    conn.commit()


def _build_registry(
    conn: sqlite3.Connection, trace_id: str, thread_id: str, actor_id: str
) -> ToolRegistry:
    registry = ToolRegistry()
    skills = SkillsService()

    async def noop(args: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "args": args}

    async def tool_session_list(args: dict[str, object]) -> dict[str, Any]:
        agent_id = str(args["agent_id"]) if isinstance(args.get("agent_id"), str) else None
        status = str(args["status"]) if isinstance(args.get("status"), str) else None
        items = session_list(conn, agent_id=agent_id, status=status)
        return {"sessions": items}

    async def tool_session_history(args: dict[str, object]) -> dict[str, Any]:
        raw_session_id = args.get("session_id")
        session_id = str(raw_session_id) if isinstance(raw_session_id, str) else thread_id
        raw_limit = args.get("limit")
        try:
            limit = int(raw_limit) if isinstance(raw_limit, int | float | str) else 200
        except (TypeError, ValueError):
            limit = 200
        before = str(args["before"]) if isinstance(args.get("before"), str) else None
        items = session_history(conn, session_id=session_id, limit=limit, before=before)
        return {"items": items}

    async def tool_session_send(args: dict[str, object]) -> dict[str, str]:
        raw_session_id = args.get("session_id")
        session_id = str(raw_session_id) if isinstance(raw_session_id, str) else thread_id
        to_agent_id = str(args.get("to_agent_id", "")).strip()
        if not to_agent_id:
            return {"error": "to_agent_id is required"}
        message = str(args.get("message", ""))
        priority = str(args.get("priority", "default")).lower()
        event_id = session_send(
            conn,
            session_id=session_id,
            to_agent_id=to_agent_id,
            message=message,
            trace_id=trace_id,
            from_agent_id=actor_id,
        )
        conn.execute(
            (
                "INSERT INTO web_notifications("
                "thread_id, event_type, payload_json, created_at"
                ") VALUES(?,?,?,?)"
            ),
            (
                session_id,
                "agent.delegated",
                json.dumps(
                    {
                        "thread_id": session_id,
                        "from_agent": actor_id,
                        "to_agent": to_agent_id,
                        "trace_id": trace_id,
                        "created_at": now_iso(),
                    }
                ),
                now_iso(),
            ),
        )
        queue = "agent_priority" if priority == "high" else "agent_default"
        ok = get_task_runner().send_task(
            "jarvis.tasks.agent.agent_step",
            kwargs={"trace_id": trace_id, "thread_id": session_id, "actor_id": to_agent_id},
            queue=queue,
        )
        if not ok:
            logger.error("Failed to dispatch sub-agent task for %s", to_agent_id)
        return {"event_id": event_id}

    async def tool_exec_host(args: dict[str, object]) -> dict[str, object]:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return {"exit_code": 2, "stdout": "", "stderr": "command is required"}
        raw_cwd = args.get("cwd")
        cwd = str(raw_cwd) if isinstance(raw_cwd, str) else None
        if actor_id == "feature_builder":
            run = get_feature_build_run_by_trace(conn, trace_id)
            if run is None and thread_id:
                run = get_latest_feature_build_run_for_thread(conn, thread_id)
            workspace = str(run.get("workspace_path", "")).strip() if run else ""
            if workspace:
                workspace_path = Path(workspace).expanduser().resolve()
                if cwd is None:
                    cwd = str(workspace_path)
                else:
                    requested = Path(cwd).expanduser().resolve()
                    if requested != workspace_path and workspace_path not in requested.parents:
                        return {
                            "exit_code": 2,
                            "stdout": "",
                            "stderr": (
                                "cwd outside isolated feature workspace; "
                                f"expected under {workspace_path}"
                            ),
                        }
        has_explicit_timeout = "timeout_s" in args
        raw_timeout = args.get("timeout_s", _DEFAULT_EXEC_HOST_TIMEOUT_S)
        try:
            timeout_s = (
                int(raw_timeout)
                if isinstance(raw_timeout, int | float | str)
                else _DEFAULT_EXEC_HOST_TIMEOUT_S
            )
        except (TypeError, ValueError):
            timeout_s = _DEFAULT_EXEC_HOST_TIMEOUT_S
        if (
            actor_id == "main"
            and not has_explicit_timeout
            and _is_build_test_gates_command(command)
        ):
            timeout_s = _BUILD_TEST_GATES_TIMEOUT_S
        raw_env = args.get("env")
        env = raw_env if isinstance(raw_env, dict) else None
        return execute_host_command(
            conn,
            command=command,
            cwd=cwd,
            env=env,
            timeout_s=timeout_s,
            trace_id=trace_id,
            caller_id=actor_id,
            thread_id=thread_id,
        )

    async def tool_update_persona(args: dict[str, object]) -> dict[str, object]:
        target_agent_id = str(args.get("agent_id", actor_id))
        soul_md = str(args.get("soul_md", ""))
        return update_persona(agent_id=target_agent_id, soul_md=soul_md)

    async def tool_create_feature_request(args: dict[str, object]) -> dict[str, object]:
        raw_title = args.get("title")
        title = str(raw_title).strip() if isinstance(raw_title, str) else ""
        if not title:
            return {"ok": False, "error": "title is required"}
        description = (
            str(args.get("description", "")).strip()
            if isinstance(args.get("description"), str)
            else ""
        )
        priority = (
            str(args.get("priority", "medium")).strip().lower()
            if isinstance(args.get("priority"), str)
            else "medium"
        )
        row = conn.execute(
            "SELECT user_id FROM threads WHERE id=? LIMIT 1",
            (thread_id,),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "thread not found"}
        reporter_id = str(row["user_id"])
        input_thread_id = (
            str(args.get("thread_id", "")).strip()
            if isinstance(args.get("thread_id"), str)
            else ""
        )
        target_thread_id = input_thread_id or thread_id
        input_trace_id = (
            str(args.get("trace_id", "")).strip()
            if isinstance(args.get("trace_id"), str)
            else ""
        )
        target_trace_id = input_trace_id or trace_id
        try:
            feature_id, created = create_feature_request(
                conn,
                title=title,
                description=description,
                priority=priority,
                reporter_id=reporter_id,
                thread_id=target_thread_id,
                trace_id=target_trace_id,
            )
        except Exception as exc:
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="roadmap.write.failed",
                    component="agent",
                    actor_type="agent",
                    actor_id=actor_id,
                    payload_json=json.dumps(
                        {
                            "status": "failed",
                            "error": str(exc),
                            "title": title,
                            "thread_id": target_thread_id,
                            "trace_id": target_trace_id,
                        }
                    ),
                    payload_redacted_json=json.dumps(
                        redact_payload(
                            {
                                "status": "failed",
                                "error": str(exc),
                                "title": title,
                                "thread_id": target_thread_id,
                                "trace_id": target_trace_id,
                            }
                        )
                    ),
                ),
            )
            return {"ok": False, "error": str(exc)}
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="roadmap.write.verified",
                component="agent",
                actor_type="agent",
                actor_id=actor_id,
                payload_json=json.dumps(
                    {
                        "status": "verified",
                        "id": feature_id,
                        "kind": "feature",
                        "created": created,
                        "idempotent_hit": not created,
                        "thread_id": target_thread_id,
                        "trace_id": target_trace_id,
                    }
                ),
                payload_redacted_json=json.dumps(
                    redact_payload(
                        {
                            "status": "verified",
                            "id": feature_id,
                            "kind": "feature",
                            "created": created,
                            "idempotent_hit": not created,
                            "thread_id": target_thread_id,
                            "trace_id": target_trace_id,
                        }
                    )
                ),
            ),
        )
        return {
            "ok": True,
            "id": feature_id,
            "kind": "feature",
            "created": created,
            "idempotent_hit": not created,
            "thread_id": target_thread_id,
            "trace_id": target_trace_id,
        }

    async def tool_thread_logs(args: dict[str, object]) -> dict[str, object]:
        raw_thread_id = args.get("thread_id")
        target_thread_id = (
            str(raw_thread_id).strip()
            if isinstance(raw_thread_id, str) and raw_thread_id.strip()
            else thread_id
        )
        summary = summarize_thread_logs(conn, target_thread_id)
        return {"summary": summary, "thread_id": target_thread_id}

    async def tool_skill_list(args: dict[str, object]) -> dict[str, Any]:
        scope = str(args["scope"]) if isinstance(args.get("scope"), str) else actor_id
        raw_pinned_only = args.get("pinned_only")
        pinned_only = bool(raw_pinned_only) if raw_pinned_only is not None else False
        items = skills.list_skills(conn, scope=scope, pinned_only=pinned_only, limit=100)
        return {"skills": items}

    async def tool_skill_read(args: dict[str, object]) -> dict[str, Any]:
        raw_slug = args.get("slug")
        slug = str(raw_slug).strip() if isinstance(raw_slug, str) else ""
        if not slug:
            return {"skill": None, "error": "slug is required"}
        scope = str(args["scope"]) if isinstance(args.get("scope"), str) else actor_id
        item = skills.get(conn, slug=slug, scope=scope)
        return {"skill": item}

    async def tool_skill_write(args: dict[str, object]) -> dict[str, Any]:
        raw_slug = args.get("slug")
        raw_title = args.get("title")
        raw_content = args.get("content")
        slug = str(raw_slug).strip() if isinstance(raw_slug, str) else ""
        title = str(raw_title).strip() if isinstance(raw_title, str) else ""
        content = str(raw_content).strip() if isinstance(raw_content, str) else ""
        if not slug:
            return {"error": "slug is required"}
        if not title:
            return {"error": "title is required"}
        if not content:
            return {"error": "content is required"}
        scope = str(args["scope"]) if isinstance(args.get("scope"), str) else "global"
        pinned = bool(args.get("pinned")) if args.get("pinned") is not None else False
        item = skills.put(
            conn,
            slug=slug,
            title=title,
            content=content,
            scope=scope,
            owner_id=actor_id,
            pinned=pinned,
            source="agent",
        )
        return {"skill": item}

    async def tool_request_human_escalation(args: dict[str, object]) -> dict[str, Any]:
        reason = str(args.get("reason", "")).strip()
        message = str(args.get("message", "")).strip()
        if not reason:
            return {"ok": False, "error": "reason is required"}
        if not message:
            return {"ok": False, "error": "message is required"}
        priority = (
            str(args.get("priority", "normal")).strip().lower()
            if isinstance(args.get("priority"), str)
            else "normal"
        )
        target_thread_id = (
            str(args.get("thread_id")).strip()
            if isinstance(args.get("thread_id"), str)
            else thread_id
        )
        return request_human_escalation(
            thread_id=target_thread_id,
            trace_id=trace_id,
            requested_by_actor_id=actor_id,
            source_agent_id=actor_id,
            reason=reason,
            message=message,
            priority=priority,
        )

    registry.register(
        "echo",
        "Echo arguments back for testing",
        noop,
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo back"},
            },
        },
    )
    registry.register(
        "session_list",
        "List sessions, optionally filtered by agent or status",
        tool_session_list,
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Filter by agent ID"},
                "status": {"type": "string", "description": "Filter by status (open, closed)"},
            },
        },
    )
    registry.register(
        "session_history",
        "Read message history from a session",
        tool_session_history,
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID to read (defaults to current thread)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max messages to return (default 200, max 500)",
                },
                "before": {"type": "string", "description": "ISO timestamp cursor for pagination"},
            },
        },
    )
    registry.register(
        "session_send",
        "Send a message to another agent in a session",
        tool_session_send,
        parameters={
            "type": "object",
            "properties": {
                "to_agent_id": {
                    "type": "string",
                    "description": "Target agent ID",
                },
                "message": {"type": "string", "description": "Message content to send"},
                "session_id": {
                    "type": "string",
                    "description": "Session ID (defaults to current thread)",
                },
                "priority": {
                    "type": "string",
                    "enum": ["default", "high"],
                    "description": "Task queue priority",
                },
            },
            "required": ["to_agent_id", "message"],
        },
    )
    registry.register(
        "exec_host",
        "Execute a shell command on the host with safety controls",
        tool_exec_host,
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {
                    "type": "string",
                    "description": "Working directory (must be in allowed prefixes)",
                },
                "timeout_s": {"type": "integer", "description": "Timeout in seconds (default 120)"},
                "env": {
                    "type": "object",
                    "description": "Environment variables (only allowlisted keys accepted)",
                },
            },
            "required": ["command"],
        },
    )
    registry.register(
        "skill_list",
        "List available skills",
        tool_skill_list,
        parameters={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "description": "Scope to search (agent ID or global)"},
                "pinned_only": {
                    "type": "boolean",
                    "description": "If true, return only pinned skills",
                },
            },
        },
    )
    registry.register(
        "skill_read",
        "Read a skill by slug",
        tool_skill_read,
        parameters={
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Skill slug"},
                "scope": {
                    "type": "string",
                    "description": "Scope to resolve (agent ID with global fallback)",
                },
            },
            "required": ["slug"],
        },
    )
    registry.register(
        "skill_write",
        "Create or update a skill",
        tool_skill_write,
        parameters={
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Skill slug"},
                "title": {"type": "string", "description": "Skill title"},
                "content": {"type": "string", "description": "Markdown skill content"},
                "scope": {"type": "string", "description": "Skill scope (default global)"},
                "pinned": {"type": "boolean", "description": "Pin skill into prompt context"},
            },
            "required": ["slug", "title", "content"],
        },
    )
    registry.register(
        "request_human_escalation",
        "Request that Jarvis notify a configured human contact channel",
        tool_request_human_escalation,
        parameters={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Short escalation reason"},
                "message": {"type": "string", "description": "Detailed human-facing message"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "Escalation priority",
                },
                "thread_id": {
                    "type": "string",
                    "description": "Optional source thread ID (defaults to current thread)",
                },
            },
            "required": ["reason", "message"],
        },
    )
    if actor_id == "main":
        registry.register(
            "update_persona",
            "Update an agent's soul markdown to persist speaking style/persona changes",
            tool_update_persona,
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Target agent ID",
                    },
                    "soul_md": {"type": "string", "description": "Full replacement markdown"},
                },
                "required": ["agent_id", "soul_md"],
            },
        )
        registry.register(
            "create_feature_request",
            "Create a roadmap feature request and return its ID",
            tool_create_feature_request,
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Feature title"},
                    "description": {"type": "string", "description": "Feature details"},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Feature priority",
                    },
                    "thread_id": {"type": "string", "description": "Optional thread scope"},
                    "trace_id": {"type": "string", "description": "Optional idempotency trace"},
                },
                "required": ["title"],
            },
        )
    registry.register(
        "thread_logs",
        "Summarize recent messages/events for a thread",
        tool_thread_logs,
        parameters={
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "Thread ID (defaults to current thread)",
                }
            },
        },
    )
    registry.register(
        "web_search",
        "Search the web using SearXNG and return results",
        web_search,
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query string"},
                "max_results": {
                    "type": "integer",
                    "description": "Max results to return (default 5, max 20)",
                },
                "categories": {
                    "type": "string",
                    "description": "Search categories (default: general)",
                },
            },
            "required": ["query"],
        },
    )

    # Load tools from plugins
    plugin_ctx = PluginContext(
        conn=conn,
        actor_id=actor_id,
        trace_id=trace_id,
        thread_id=thread_id,
    )
    for plugin in get_loaded_plugins():
        if plugin.enabled_for_agent(actor_id):
            try:
                plugin.register_tools(registry, plugin_ctx)
            except Exception:
                logger.warning("Plugin %s failed to register tools", plugin.name, exc_info=True)

    return registry
