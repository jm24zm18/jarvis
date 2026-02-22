"""Agent task handlers."""

import asyncio
import json
import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.logging import bind_context, clear_context
from jarvis.tasks import get_task_runner

logger = logging.getLogger(__name__)
from jarvis.config import get_settings  # noqa: E402
from jarvis.db.connection import get_conn  # noqa: E402
from jarvis.db.queries import create_feature_request, now_iso  # noqa: E402
from jarvis.events.models import EventInput  # noqa: E402
from jarvis.events.writer import emit_event, redact_payload  # noqa: E402
from jarvis.ids import new_id  # noqa: E402
from jarvis.memory.skills import SkillsService  # noqa: E402
from jarvis.orchestrator.step import run_agent_step  # noqa: E402
from jarvis.plugins.base import PluginContext  # noqa: E402
from jarvis.plugins.loader import get_loaded_plugins  # noqa: E402
from jarvis.providers.factory import build_fallback_provider, build_primary_provider  # noqa: E402
from jarvis.providers.router import ProviderRouter  # noqa: E402
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
from jarvis.tools.host import execute_host_command  # noqa: E402
from jarvis.tools.persona import update_persona  # noqa: E402
from jarvis.tools.registry import ToolRegistry  # noqa: E402
from jarvis.tools.runtime import ToolRuntime  # noqa: E402
from jarvis.tools.session import session_history, session_list, session_send  # noqa: E402
from jarvis.tools.web_search import web_search  # noqa: E402

_DEFAULT_EXEC_HOST_TIMEOUT_S = 120
_BUILD_TEST_GATES_TIMEOUT_S = 600
_BUILD_TEST_GATES_COMMAND = "uv run jarvis test-gates --fail-fast"


def _is_build_test_gates_command(command: str) -> bool:
    normalized = " ".join(command.strip().split()).lower()
    return normalized == _BUILD_TEST_GATES_COMMAND


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
            start_attempt(
                conn,
                trace_id=trace_id,
                thread_id=thread_id,
                actor_id=actor_id,
                attempt=attempt,
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
