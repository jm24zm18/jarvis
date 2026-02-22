"""Ralph autonomous improvement loop task.

Picks the next task from the ## Ralph Sprint section of docs/PLAN.md,
dispatches it to the feature_builder agent via the existing agent_step
pipeline, validates the outcome through smoke gates, and commits on success.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_thread,
    ensure_channel,
    now_iso,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id

logger = logging.getLogger(__name__)

RALPH_NEVER_EDIT_PATHS = (
    "src/jarvis/selfupdate/pipeline.py",
    "src/jarvis/selfupdate/ralph_plan.py",
    "src/jarvis/selfupdate/ralph_engine.py",
    "agents/feature_builder/identity.md",
    "src/jarvis/policy/",
    "src/jarvis/auth/",
)

_RALPH_INSTRUCTION_TEMPLATE = """\
You are executing a Ralph autonomous improvement iteration.

## Your Task

{task_text}

{accept_section}
## Requirements

- Implement the task completely following established codebase patterns.
- Run `uv run jarvis test-gates --fail-fast` and fix **all** failures before finishing.
- Commit your changes locally to branch `ralph/{slug}-{timestamp}` (do NOT push or open a PR).
- Do NOT modify any of the following protected paths:
{never_edit_lines}

## Terminal Signal

End your final response with **exactly one** of these lines:

    RALPH_SUCCESS: <one-line summary of what was implemented>
    RALPH_FAIL: <one-line reason why you could not complete the task>

Do not include any other text after the terminal signal line.
"""

_PROGRESS_FILE = "docs/ralph/progress.json"
_HISTORY_FILE = "docs/ralph/history.md"

# Poll interval and timeout for waiting on agent completion.
_POLL_INTERVAL_S = 3.0
_SETTLE_SECONDS = 20.0


def _emit_ralph_event(
    *,
    conn,
    trace_id: str,
    thread_id: str | None,
    event_type: str,
    payload: dict[str, object],
) -> None:
    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id,
            event_type=event_type,
            component="ralph",
            actor_type="system",
            actor_id="ralph",
            payload_json=json.dumps(payload),
            payload_redacted_json=json.dumps(redact_payload(payload)),
        ),
    )


def read_ralph_progress(repo_path: str = ".") -> dict[str, object]:
    """Read the Ralph progress state from docs/ralph/progress.json."""
    p = Path(repo_path) / _PROGRESS_FILE
    if not p.exists():
        return {"iteration": 0, "failures": 0, "last_task": None, "last_run_at": None}
    return json.loads(p.read_text(encoding="utf-8"))


def write_ralph_progress(data: dict[str, object], repo_path: str = ".") -> None:
    """Write Ralph progress state atomically."""
    import os
    import tempfile

    p = Path(repo_path) / _PROGRESS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".ralph_progress_tmp_")
    try:
        os.write(fd, json.dumps(data, indent=2).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, p)


def append_ralph_history(entry: str, repo_path: str = ".") -> None:
    """Append an entry to docs/ralph/history.md."""
    p = Path(repo_path) / _HISTORY_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(entry + "\n")


def _latest_assistant_message(
    thread_id: str, after_ts: str
) -> tuple[str, str, str] | None:
    """Return (id, content, created_at) of the latest assistant message after after_ts."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, content, created_at FROM messages "
            "WHERE thread_id=? AND role='assistant' AND created_at>=? "
            "ORDER BY created_at DESC LIMIT 1",
            (thread_id, after_ts),
        ).fetchone()
    if row is None:
        return None
    return str(row["id"]), str(row["content"]), str(row["created_at"])


def _run_gates_on_working_tree(repo_path: str) -> tuple[bool, str]:
    """Run lint + typecheck + tests directly on the working tree.

    Returns (ok, output_summary).
    """
    commands = [
        ["uv", "run", "ruff", "check", "src", "tests"],
        ["uv", "run", "mypy", "src"],
        ["uv", "run", "pytest", "tests/unit", "-q", "--tb=short"],
    ]
    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or f"{cmd[0]} failed").strip()
                return False, f"{' '.join(cmd[:2])} failed: {detail[:500]}"
        except subprocess.TimeoutExpired:
            return False, f"{' '.join(cmd[:2])} timed out"
    return True, "lint + typecheck + tests passed"


def _git_rollback(repo_path: str) -> None:
    """Reset working tree to HEAD (discard uncommitted changes)."""
    subprocess.run(
        ["git", "-C", repo_path, "reset", "--hard", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    subprocess.run(
        ["git", "-C", repo_path, "clean", "-fd"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _git_commit_ralph(
    repo_path: str, task_slug: str, task_text: str, run_id: str
) -> tuple[bool, str]:
    """Stage all changes and commit to a Ralph branch."""
    from datetime import datetime

    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    branch = f"ralph/{task_slug[:30]}-{timestamp}"

    checkout = subprocess.run(
        ["git", "-C", repo_path, "checkout", "-B", branch],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if checkout.returncode != 0:
        return False, checkout.stderr.strip() or "branch create failed"

    add = subprocess.run(
        ["git", "-C", repo_path, "add", "-A"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if add.returncode != 0:
        return False, add.stderr.strip() or "git add failed"

    # Check if there's anything to commit.
    status = subprocess.run(
        ["git", "-C", repo_path, "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if not status.stdout.strip():
        return True, f"no changes to commit (branch: {branch})"

    short_task = task_text[:72]
    message = f"ralph: {short_task}\n\nRun-ID: {run_id}"
    commit = subprocess.run(
        ["git", "-C", repo_path, "commit", "-m", message],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if commit.returncode != 0:
        return False, commit.stderr.strip() or "git commit failed"

    ref = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    short_ref = ref.stdout.strip() if ref.returncode == 0 else "unknown"
    return True, f"committed {short_ref} on {branch}"


def _build_instruction(
    task_text: str,
    accept: str | None,
    slug: str,
    timestamp: str,
) -> str:
    accept_section = (
        f"## Acceptance Criteria\n\n{accept}\n\n" if accept else ""
    )
    never_edit_lines = "\n".join(f"  - {p}" for p in RALPH_NEVER_EDIT_PATHS)
    return _RALPH_INSTRUCTION_TEMPLATE.format(
        task_text=task_text,
        accept_section=accept_section,
        slug=slug,
        timestamp=timestamp,
        never_edit_lines=never_edit_lines,
    )


def run_ralph_iteration(
    run_id: str,
    task_text: str,
    task_slug: str,
    accept_criteria: str | None,
    trace_id: str,
    dry_run: bool = False,
    actor_id: str = "feature_builder",
    repo_path: str = ".",
    timeout_s: float = 3600.0,
) -> dict[str, object]:
    """Execute one Ralph improvement iteration.

    1. Create/reuse a web thread for actor_id.
    2. Insert the Ralph instruction prompt as a user message.
    3. Enqueue agent_step to process it.
    4. Poll until the agent produces a settled response.
    5. Inspect for RALPH_SUCCESS / RALPH_FAIL markers.
    6. On RALPH_SUCCESS: run gates on working tree; commit or rollback.
    7. Update progress.json and history.md.
    8. Emit ralph.* events.

    In dry_run mode, skips gate execution and git operations.
    """
    from jarvis.tasks import get_task_runner

    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    thread_id: str | None = None

    try:
        with get_conn() as conn:
            # Find or create a web channel thread for this actor.
            row = conn.execute(
                (
                    "SELECT t.id FROM threads t "
                    "JOIN channels c ON c.id=t.channel_id "
                    "WHERE t.user_id=? AND c.channel_type='web' AND t.status='open' "
                    "ORDER BY t.updated_at DESC LIMIT 1"
                ),
                (actor_id,),
            ).fetchone()
            if row is not None:
                thread_id = str(row["id"])
            else:
                channel_id = ensure_channel(conn, actor_id, "web")
                thread_id = create_thread(conn, actor_id, channel_id)

            # Insert the instruction message.
            msg_id = new_id("msg")
            now = now_iso()
            instruction = _build_instruction(task_text, accept_criteria, task_slug, timestamp)
            conn.execute(
                "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES(?,?,?,?,?)",
                (msg_id, thread_id, "user", instruction, now),
            )

            _emit_ralph_event(
                conn=conn,
                trace_id=trace_id,
                thread_id=thread_id,
                event_type="ralph.iteration.start",
                payload={
                    "run_id": run_id,
                    "task_text": task_text[:200],
                    "task_slug": task_slug,
                    "dry_run": dry_run,
                    "actor_id": actor_id,
                },
            )

        # Record the timestamp of our user message for polling.
        with get_conn() as conn:
            row = conn.execute(
                "SELECT created_at FROM messages WHERE id=?", (msg_id,)
            ).fetchone()
            user_msg_ts = str(row["created_at"]) if row else now

        if dry_run:
            logger.info("ralph dry-run: would dispatch agent_step for task=%r", task_text[:80])
            return {
                "run_id": run_id,
                "thread_id": thread_id,
                "trace_id": trace_id,
                "status": "dry_run",
                "task_text": task_text,
                "task_slug": task_slug,
            }

        # Enqueue the agent step.
        runner = get_task_runner()
        queued = runner.send_task(
            "jarvis.tasks.agent.agent_step",
            kwargs={"thread_id": thread_id, "trace_id": trace_id, "actor_id": actor_id},
            queue="default",
        )
        if not queued:
            with get_conn() as conn:
                _emit_ralph_event(
                    conn=conn,
                    trace_id=trace_id,
                    thread_id=thread_id,
                    event_type="ralph.iteration.fail",
                    payload={
                        "run_id": run_id,
                        "task_text": task_text[:200],
                        "reason": "agent_step could not be enqueued",
                    },
                )
            return {
                "run_id": run_id,
                "thread_id": thread_id,
                "trace_id": trace_id,
                "status": "failed",
                "reason": "agent_step could not be enqueued",
            }

        # Poll for settled agent response.
        final_content = _poll_for_agent_response(
            thread_id=thread_id,
            after_ts=user_msg_ts,
            timeout_s=timeout_s,
        )

        if final_content is None:
            with get_conn() as conn:
                _emit_ralph_event(
                    conn=conn,
                    trace_id=trace_id,
                    thread_id=thread_id,
                    event_type="ralph.iteration.fail",
                    payload={
                        "run_id": run_id,
                        "task_text": task_text[:200],
                        "reason": f"agent timed out after {timeout_s:.0f}s",
                    },
                )
            return {
                "run_id": run_id,
                "thread_id": thread_id,
                "trace_id": trace_id,
                "status": "failed",
                "reason": f"agent timed out after {timeout_s:.0f}s",
            }

        return _finalize_ralph_run(
            run_id=run_id,
            trace_id=trace_id,
            thread_id=thread_id,
            task_text=task_text,
            task_slug=task_slug,
            final_content=final_content,
            repo_path=repo_path,
        )

    except Exception as exc:
        logger.exception("ralph iteration crashed: run_id=%s", run_id)
        if thread_id is not None:
            try:
                with get_conn() as conn:
                    _emit_ralph_event(
                        conn=conn,
                        trace_id=trace_id,
                        thread_id=thread_id,
                        event_type="ralph.iteration.fail",
                        payload={
                            "run_id": run_id,
                            "task_text": task_text[:200],
                            "reason": f"crash: {exc.__class__.__name__}: {exc}",
                        },
                    )
            except Exception:
                pass
        return {
            "run_id": run_id,
            "thread_id": thread_id,
            "trace_id": trace_id,
            "status": "failed",
            "reason": f"crash: {exc.__class__.__name__}: {exc}",
        }


def _poll_for_agent_response(
    thread_id: str,
    after_ts: str,
    timeout_s: float,
) -> str | None:
    """Poll until the agent's last assistant message has settled.

    Returns the final message content, or None on timeout.
    """
    deadline = time.monotonic() + timeout_s
    last_seen_id: str | None = None
    last_seen_at: float = 0.0

    while time.monotonic() < deadline:
        result = _latest_assistant_message(thread_id, after_ts)
        if result is not None:
            msg_id, content, _ = result
            if msg_id != last_seen_id:
                last_seen_id = msg_id
                last_seen_at = time.monotonic()
            elif time.monotonic() - last_seen_at >= _SETTLE_SECONDS:
                return content
        time.sleep(_POLL_INTERVAL_S)

    # Return whatever we have on timeout.
    result = _latest_assistant_message(thread_id, after_ts)
    return result[1] if result else None


def _finalize_ralph_run(
    *,
    run_id: str,
    trace_id: str,
    thread_id: str,
    task_text: str,
    task_slug: str,
    final_content: str,
    repo_path: str,
) -> dict[str, object]:
    """Inspect the agent's response and commit or rollback."""
    # Extract terminal signal.
    lines = final_content.splitlines()
    outcome: str | None = None
    outcome_detail = ""
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.upper().startswith("RALPH_SUCCESS:"):
            outcome = "success"
            outcome_detail = stripped[len("RALPH_SUCCESS:"):].strip()
            break
        if stripped.upper().startswith("RALPH_FAIL:"):
            outcome = "fail"
            outcome_detail = stripped[len("RALPH_FAIL:"):].strip()
            break

    if outcome is None:
        # No terminal signal found — treat as failure.
        outcome = "fail"
        outcome_detail = "no RALPH_SUCCESS/RALPH_FAIL terminal signal in agent response"

    now_utc = datetime.now(UTC).isoformat()

    if outcome == "fail":
        _git_rollback(repo_path)
        # Update progress counters.
        progress = read_ralph_progress(repo_path)
        progress["failures"] = int(progress.get("failures") or 0) + 1  # type: ignore[arg-type]
        progress["last_task"] = task_text[:200]
        progress["last_run_at"] = now_utc
        write_ralph_progress(progress, repo_path)
        append_ralph_history(
            f"\n## {now_utc} — FAIL\nTask: {task_text[:120]}\nReason: {outcome_detail[:300]}\n",
            repo_path,
        )
        with get_conn() as conn:
            _emit_ralph_event(
                conn=conn,
                trace_id=trace_id,
                thread_id=thread_id,
                event_type="ralph.iteration.fail",
                payload={
                    "run_id": run_id,
                    "task_text": task_text[:200],
                    "reason": outcome_detail[:300],
                },
            )
        return {
            "run_id": run_id,
            "thread_id": thread_id,
            "trace_id": trace_id,
            "status": "failed",
            "reason": outcome_detail,
        }

    # RALPH_SUCCESS path: run gates on the working tree.
    gates_ok, gates_detail = _run_gates_on_working_tree(repo_path)
    if not gates_ok:
        _git_rollback(repo_path)
        progress = read_ralph_progress(repo_path)
        progress["failures"] = int(progress.get("failures") or 0) + 1  # type: ignore[arg-type]
        progress["last_task"] = task_text[:200]
        progress["last_run_at"] = now_utc
        write_ralph_progress(progress, repo_path)
        append_ralph_history(
            f"\n## {now_utc} — GATE FAIL\nTask: {task_text[:120]}\nGates: {gates_detail[:300]}\n",
            repo_path,
        )
        with get_conn() as conn:
            _emit_ralph_event(
                conn=conn,
                trace_id=trace_id,
                thread_id=thread_id,
                event_type="ralph.iteration.gate_fail",
                payload={
                    "run_id": run_id,
                    "task_text": task_text[:200],
                    "gate_detail": gates_detail[:500],
                    "rollback": True,
                },
            )
        return {
            "run_id": run_id,
            "thread_id": thread_id,
            "trace_id": trace_id,
            "status": "gate_fail",
            "gate_detail": gates_detail,
        }

    # Gates passed — commit.
    commit_ok, commit_detail = _git_commit_ralph(
        repo_path, task_slug, task_text, run_id
    )
    if not commit_ok:
        _git_rollback(repo_path)
        progress = read_ralph_progress(repo_path)
        progress["failures"] = int(progress.get("failures") or 0) + 1  # type: ignore[arg-type]
        progress["last_task"] = task_text[:200]
        progress["last_run_at"] = now_utc
        write_ralph_progress(progress, repo_path)
        append_ralph_history(
            f"\n## {now_utc} — COMMIT FAIL\n"
            f"Task: {task_text[:120]}\n"
            f"Reason: {commit_detail[:300]}\n",
            repo_path,
        )
        with get_conn() as conn:
            _emit_ralph_event(
                conn=conn,
                trace_id=trace_id,
                thread_id=thread_id,
                event_type="ralph.iteration.fail",
                payload={
                    "run_id": run_id,
                    "task_text": task_text[:200],
                    "reason": f"commit failed: {commit_detail}",
                },
            )
        return {
            "run_id": run_id,
            "thread_id": thread_id,
            "trace_id": trace_id,
            "status": "failed",
            "reason": f"commit failed: {commit_detail}",
        }

    # Full success — update progress and history.
    progress = read_ralph_progress(repo_path)
    progress["iteration"] = int(progress.get("iteration") or 0) + 1  # type: ignore[arg-type]
    progress["last_task"] = task_text[:200]
    progress["last_run_at"] = now_utc
    write_ralph_progress(progress, repo_path)
    append_ralph_history(
        f"\n## {now_utc} — SUCCESS\n"
        f"Task: {task_text[:120]}\n"
        f"Summary: {outcome_detail[:200]}\n"
        f"Commit: {commit_detail}\n"
        f"Gates: {gates_detail}\n",
        repo_path,
    )
    with get_conn() as conn:
        _emit_ralph_event(
            conn=conn,
            trace_id=trace_id,
            thread_id=thread_id,
            event_type="ralph.iteration.success",
            payload={
                "run_id": run_id,
                "task_text": task_text[:200],
                "outcome_detail": outcome_detail[:300],
                "gate_detail": gates_detail,
                "commit_detail": commit_detail,
            },
        )

    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "trace_id": trace_id,
        "status": "success",
        "outcome_detail": outcome_detail,
        "gate_detail": gates_detail,
        "commit_detail": commit_detail,
    }
