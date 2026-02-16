"""CLI chat helpers for talking to the main agent."""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass

import click
from kombu.exceptions import OperationalError

from jarvis.celery_app import celery_app
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_thread,
    ensure_channel,
    ensure_open_thread,
    ensure_system_state,
    ensure_user,
    insert_message,
)
from jarvis.ids import new_id
from jarvis.tasks.agent import agent_step


@dataclass(frozen=True)
class AssistantReply:
    thread_id: str
    user_message_id: str
    assistant_message_id: str
    assistant_text: str


def default_cli_user() -> str:
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    host = socket.gethostname() or "local"
    return f"cli:{user}@{host}"


def resolve_thread(user_external_id: str, thread_id: str | None, new_thread: bool) -> str:
    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, user_external_id)
        channel_id = ensure_channel(conn, user_id, "cli")
        if thread_id:
            row = conn.execute("SELECT id FROM threads WHERE id=? LIMIT 1", (thread_id,)).fetchone()
            if row is None:
                raise click.ClickException(f"thread not found: {thread_id}")
            return str(row["id"])
        if new_thread:
            return create_thread(conn, user_id, channel_id)
        return ensure_open_thread(conn, user_id, channel_id)


def _assistant_message(message_id: str) -> tuple[str, str] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, content FROM messages WHERE id=? AND role='assistant' LIMIT 1",
            (message_id,),
        ).fetchone()
    if row is None:
        return None
    return str(row["id"]), str(row["content"])


def _assistant_message_after(thread_id: str, user_message_id: str) -> tuple[str, str] | None:
    with get_conn() as conn:
        user_row = conn.execute(
            "SELECT created_at FROM messages WHERE id=? AND thread_id=? LIMIT 1",
            (user_message_id, thread_id),
        ).fetchone()
        if user_row is None:
            return None
        created_at = str(user_row["created_at"])
        row = conn.execute(
            (
                "SELECT id, content FROM messages "
                "WHERE thread_id=? AND role='assistant' AND created_at>=? "
                "ORDER BY created_at ASC LIMIT 1"
            ),
            (thread_id, created_at),
        ).fetchone()
    if row is None:
        return None
    return str(row["id"]), str(row["content"])


def send_and_wait(
    thread_id: str,
    message: str,
    enqueue: bool,
    timeout_s: float,
    poll_interval_s: float,
) -> AssistantReply:
    with get_conn() as conn:
        user_message_id = insert_message(conn, thread_id, "user", message)

    trace_id = new_id("trc")
    if enqueue:
        try:
            celery_app.send_task(
                "jarvis.tasks.agent.agent_step",
                kwargs={"trace_id": trace_id, "thread_id": thread_id, "actor_id": "main"},
                queue="agent_priority",
            )
        except OperationalError as exc:
            raise click.ClickException(f"failed to enqueue agent step: {exc}") from exc

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            row = _assistant_message_after(thread_id, user_message_id)
            if row is not None:
                assistant_message_id, assistant_text = row
                return AssistantReply(
                    thread_id=thread_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    assistant_text=assistant_text,
                )
            time.sleep(poll_interval_s)
        raise click.ClickException(
            f"timed out waiting for assistant reply after {timeout_s:.1f}s "
            "(is worker running?)"
        )

    assistant_message_id = agent_step(trace_id=trace_id, thread_id=thread_id, actor_id="main")
    row = _assistant_message(assistant_message_id)
    if row is None:
        raise click.ClickException(
            f"assistant reply not found for message id: {assistant_message_id}"
        )
    _, assistant_text = row
    return AssistantReply(
        thread_id=thread_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        assistant_text=assistant_text,
    )


def format_reply(reply: AssistantReply, json_output: bool) -> str:
    if not json_output:
        return reply.assistant_text
    return json.dumps(
        {
            "thread_id": reply.thread_id,
            "user_message_id": reply.user_message_id,
            "assistant_message_id": reply.assistant_message_id,
            "assistant": reply.assistant_text,
        }
    )
