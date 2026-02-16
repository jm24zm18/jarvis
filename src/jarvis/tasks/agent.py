"""Agent Celery tasks."""

import asyncio
import json
import logging
import sqlite3
from typing import Any

from kombu.exceptions import OperationalError

from jarvis.celery_app import celery_app
from jarvis.logging import bind_context, clear_context

logger = logging.getLogger(__name__)
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import now_iso
from jarvis.memory.skills import SkillsService
from jarvis.orchestrator.step import run_agent_step
from jarvis.providers.factory import build_primary_provider
from jarvis.providers.router import ProviderRouter
from jarvis.providers.sglang import SGLangProvider
from jarvis.tools.host import execute_host_command
from jarvis.tools.persona import update_persona
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.runtime import ToolRuntime
from jarvis.tools.session import session_history, session_list, session_send
from jarvis.plugins.base import PluginContext
from jarvis.plugins.loader import get_loaded_plugins
from jarvis.tools.web_search import web_search


@celery_app.task(name="jarvis.tasks.agent.agent_step")
def agent_step(trace_id: str, thread_id: str, actor_id: str = "main") -> str:
    clear_context()
    bind_context(trace_id=trace_id, thread_id=thread_id, actor_id=actor_id)
    settings = get_settings()

    router = ProviderRouter(
        build_primary_provider(settings),
        SGLangProvider(settings.sglang_model),
    )

    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
                "VALUES(?,?,?,?)"
            ),
            (
                thread_id,
                "agent.thinking",
                json.dumps({"thread_id": thread_id, "agent_id": actor_id}),
                now_iso(),
            ),
        )

    with get_conn() as conn:
        def notify_trace(event_type: str, payload: dict[str, object]) -> None:
            _notify_trace_event(
                conn=conn,
                thread_id=thread_id,
                trace_id=trace_id,
                event_type=event_type,
                payload=payload,
            )

        registry = _build_registry(conn, trace_id, thread_id, actor_id)
        runtime = ToolRuntime(registry)
        message_id = asyncio.run(
            run_agent_step(
                conn=conn,
                router=router,
                runtime=runtime,
                thread_id=thread_id,
                trace_id=trace_id,
                actor_id=actor_id,
                notify_fn=notify_trace,
            )
        )
        conn.execute(
            (
                "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
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
                "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
                "VALUES(?,?,?,?)"
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
            channel_type = str(channel_row["channel_type"]) if channel_row is not None else ""
            if channel_type and channel_type != "web":
                try:
                    celery_app.send_task(
                        "jarvis.tasks.channel.send_channel_message",
                        kwargs={
                            "thread_id": thread_id,
                            "message_id": message_id,
                            "channel_type": channel_type,
                        },
                        queue="tools_io",
                    )
                except OperationalError as exc:
                    logger.error("Failed to dispatch %s send task: %s", channel_type, exc)
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
                try:
                    celery_app.send_task(
                        "jarvis.tasks.agent.agent_step",
                        kwargs={"trace_id": trace_id, "thread_id": thread_id, "actor_id": "main"},
                        queue="agent_priority",
                    )
                except OperationalError as exc:
                    logger.error("Failed to dispatch main agent reply task: %s", exc)
    return message_id


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
                "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
                "VALUES(?,?,?,?)"
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
        try:
            celery_app.send_task(
                "jarvis.tasks.agent.agent_step",
                kwargs={"trace_id": trace_id, "thread_id": session_id, "actor_id": to_agent_id},
                queue=queue,
            )
        except OperationalError as exc:
            logger.error("Failed to dispatch sub-agent task for %s: %s", to_agent_id, exc)
        return {"event_id": event_id}

    async def tool_exec_host(args: dict[str, object]) -> dict[str, object]:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return {"exit_code": 2, "stdout": "", "stderr": "command is required"}
        raw_cwd = args.get("cwd")
        cwd = str(raw_cwd) if isinstance(raw_cwd, str) else None
        raw_timeout = args.get("timeout_s", 120)
        try:
            timeout_s = int(raw_timeout) if isinstance(raw_timeout, int | float | str) else 120
        except (TypeError, ValueError):
            timeout_s = 120
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
        conn=conn, actor_id=actor_id, trace_id=trace_id, thread_id=thread_id,
    )
    for plugin in get_loaded_plugins():
        if plugin.enabled_for_agent(actor_id):
            try:
                plugin.register_tools(registry, plugin_ctx)
            except Exception:
                logger.warning("Plugin %s failed to register tools", plugin.name, exc_info=True)

    return registry
