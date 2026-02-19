"""CLI build command: trigger Jarvis to self-improve its codebase."""

from __future__ import annotations

import time

import click

from jarvis.cli.chat import default_cli_user, resolve_thread
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_thread,
    ensure_channel,
    ensure_system_state,
    ensure_user,
    insert_message,
)
from jarvis.ids import new_id
from jarvis.tasks import get_task_runner

BUILD_PROMPT = """\
You are being asked to run a self-improvement build cycle on the Jarvis codebase.

## Instructions

1. Create a new git branch named `auto/build-{timestamp}` where `{timestamp}` is the current \
date/time in YYYYMMDD-HHMMSS format.

2. Execute the build cycle directly as **main** (do not delegate this flow to worker agents).
   a. Run `uv run jarvis test-gates --fail-fast` to check for lint, type, and test failures.
   b. Read any failures carefully.
   c. Fix all lint, typecheck, and test issues you find.
   d. Run the test gates again to verify your fixes pass.
   e. If fixes were made, commit them with a clear message, push the branch, \
and open a PR to `dev` using `gh pr create`.

3. If all gates already pass with no issues, report back: "All gates pass — nothing to fix."

4. Summarise what was found and fixed (or that everything was clean).
"""

# Settle time: after we see an assistant message, wait this long for a newer
# one before concluding the build is done.  This lets the delegation chain
# (main → coder → main) complete.
_SETTLE_SECONDS = 15.0


def _latest_assistant_message(thread_id: str, after_ts: str) -> tuple[str, str, str] | None:
    """Return (id, content, created_at) of the latest assistant message after *after_ts*."""
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


def _resolve_web_thread() -> str:
    """Create a new thread under the web_admin user with 'web' channel."""
    with get_conn() as conn:
        ensure_system_state(conn)
        uid = ensure_user(conn, "web_admin")
        cid = ensure_channel(conn, uid, "web")
        return create_thread(conn, uid, cid)


def run_build(
    *,
    thread_id: str | None = None,
    new_thread: bool = False,
    user_id: str | None = None,
    web: bool = False,
    enqueue: bool = True,
    timeout_s: float = 300.0,
    poll_interval_s: float = 2.0,
) -> None:
    """Send the build prompt to the main agent and print the result."""
    if web:
        thread_id = _resolve_web_thread()
    else:
        external_user_id = user_id or default_cli_user()
        thread_id = resolve_thread(external_user_id, thread_id=thread_id, new_thread=new_thread)
    click.echo(f"build thread: {thread_id}")

    # Insert the user message and record its timestamp for later polling.
    with get_conn() as conn:
        user_msg_id = insert_message(conn, thread_id, "user", BUILD_PROMPT)
        row = conn.execute(
            "SELECT created_at FROM messages WHERE id=?", (user_msg_id,)
        ).fetchone()
        user_msg_ts = str(row["created_at"])

    trace_id = new_id("trc")

    if enqueue:
        ok = get_task_runner().send_task(
            "jarvis.tasks.agent.agent_step",
            kwargs={"trace_id": trace_id, "thread_id": thread_id, "actor_id": "main"},
            queue="agent_priority",
        )
        if not ok:
            raise click.ClickException("failed to enqueue agent step")
    else:
        from jarvis.tasks.agent import agent_step

        agent_step(trace_id=trace_id, thread_id=thread_id, actor_id="main")

    click.echo("waiting for agent to complete build cycle...")

    # Poll for the *final* assistant message.  The delegation chain produces
    # multiple assistant messages (main delegates → coder works → main
    # summarises).  We keep polling until the latest assistant message hasn't
    # changed for _SETTLE_SECONDS.
    deadline = time.monotonic() + timeout_s
    last_seen_id: str | None = None
    last_seen_at: float = 0.0

    while time.monotonic() < deadline:
        result = _latest_assistant_message(thread_id, user_msg_ts)
        if result is not None:
            msg_id, content, _ = result
            if msg_id != last_seen_id:
                last_seen_id = msg_id
                last_seen_at = time.monotonic()
            elif time.monotonic() - last_seen_at >= _SETTLE_SECONDS:
                # No newer message for _SETTLE_SECONDS — treat as final.
                click.echo(content)
                return
        time.sleep(poll_interval_s)

    # Timed out — print whatever we have.
    if last_seen_id is not None:
        result = _latest_assistant_message(thread_id, user_msg_ts)
        if result is not None:
            click.echo(result[1])
            return
    raise click.ClickException(
        f"timed out waiting for build result after {timeout_s:.0f}s "
        "(is API running?)"
    )
