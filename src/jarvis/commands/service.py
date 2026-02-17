"""Command execution service."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from jarvis.agents.loader import get_all_agent_ids
from jarvis.commands.handlers import parse_command
from jarvis.config import get_settings
from jarvis.db.queries import (
    create_approval,
    create_thread,
    get_system_state,
    set_thread_agents,
    set_thread_verbose,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.memory.knowledge import KnowledgeBaseService
from jarvis.memory.service import MemoryService
from jarvis.onboarding.service import reset_onboarding_state, start_onboarding_prompt
from jarvis.providers.router import ProviderRouter
from jarvis.scheduler.service import estimate_schedule_backlog
from jarvis.tasks import get_task_runner
from jarvis.tasks.system import enqueue_restart


def _send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
    try:
        return get_task_runner().send_task(name, kwargs=kwargs, queue=queue)
    except Exception:
        return False


def _is_admin(admin_ids: set[str], actor_external_id: str | None) -> bool:
    return actor_external_id is not None and actor_external_id in admin_ids


def _default_agents() -> list[str]:
    return sorted(get_all_agent_ids())


def _active_agents(conn: sqlite3.Connection, thread_id: str) -> list[str]:
    row = conn.execute(
        "SELECT active_agent_ids_json FROM thread_settings WHERE thread_id=?",
        (thread_id,),
    ).fetchone()
    if row is None:
        return _default_agents()
    raw = row["active_agent_ids_json"]
    if not isinstance(raw, str):
        return _default_agents()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return _default_agents()
    if isinstance(decoded, list):
        return [str(item) for item in decoded]
    return _default_agents()


def _thread_owner(conn: sqlite3.Connection, thread_id: str) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT user_id, channel_id FROM threads WHERE id=? LIMIT 1",
        (thread_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row["user_id"]), str(row["channel_id"])


def _fts_query(text: str) -> str:
    tokens = [token.strip() for token in text.replace('"', " ").split() if token.strip()]
    if not tokens:
        return ""
    return " OR ".join(tokens[:8])


async def _queue_depth() -> dict[str, int]:
    runner = get_task_runner()
    return {
        "in_flight": runner.in_flight,
        "max_concurrent": int(get_settings().task_runner_max_concurrent),
    }


async def maybe_execute_command(
    conn: sqlite3.Connection,
    thread_id: str,
    user_text: str,
    actor_external_id: str | None,
    router: ProviderRouter,
    admin_ids: set[str],
) -> str | None:
    settings = get_settings()
    parsed = parse_command(user_text)
    if parsed is None:
        return None

    command, args = parsed
    if command == "/verbose" and args and args[0] in {"on", "off"}:
        set_thread_verbose(conn, thread_id, args[0] == "on")
        return f"verbose set to {args[0]}"

    if command == "/group" and len(args) >= 2 and args[0] in {"on", "off"}:
        known_agents = get_all_agent_ids()
        agent = args[1]
        if agent not in known_agents:
            return f"unknown agent: {agent}"
        if agent == "main" and args[0] == "off":
            return "cannot disable main agent"
        current = _active_agents(conn, thread_id)
        if args[0] == "off":
            current = [a for a in current if a != agent]
        elif agent not in current:
            current.append(agent)
        current = [a for a in current if a in get_all_agent_ids()]
        if "main" not in current:
            current.insert(0, "main")
        set_thread_agents(conn, thread_id, current)
        return f"group updated: {','.join(current)}"

    if command == "/new":
        owner = _thread_owner(conn, thread_id)
        if owner is None:
            return "thread not found"
        user_id, channel_id = owner
        conn.execute(
            "UPDATE threads SET status='closed', updated_at=datetime('now') WHERE id=?",
            (thread_id,),
        )
        new_thread_id = create_thread(conn, user_id, channel_id)
        return f"new thread created: {new_thread_id}"

    if command == "/compact":
        ok = _send_task(
            "jarvis.tasks.memory.compact_thread",
            kwargs={"thread_id": thread_id},
            queue="tools_io",
        )
        if not ok:
            return "compaction unavailable"
        return "compaction enqueued"

    if command == "/onboarding" and len(args) == 1 and args[0] == "reset":
        owner = _thread_owner(conn, thread_id)
        if owner is None:
            return "thread not found"
        user_id, _ = owner
        reset_onboarding_state(conn, user_id, thread_id)
        first_question = await start_onboarding_prompt(conn, router, user_id, thread_id)
        if first_question:
            return f"Onboarding reset.\n\n{first_question}"
        return "onboarding state reset"

    if command == "/status":
        providers = await router.health()
        queue_depth = await _queue_depth()
        active_agents = _active_agents(conn, thread_id)
        scheduler_backlog = estimate_schedule_backlog(
            conn, default_max_catchup=settings.scheduler_max_catchup
        )
        worker_health: dict[str, object] = {
            "reachable": True,
            "workers": ["in_process_runner"],
            "in_flight": get_task_runner().in_flight,
        }
        return json.dumps(
            {
                "providers": providers,
                "queues": queue_depth,
                "active_agents": active_agents,
                "scheduler": scheduler_backlog,
                "workers": worker_health,
            }
        )

    if command == "/logs" and len(args) >= 2 and args[0] == "trace":
        trace_id = args[1]
        rows = conn.execute(
            (
                "SELECT event_type, component, created_at FROM events "
                "WHERE trace_id=? ORDER BY created_at ASC"
            ),
            (trace_id,),
        ).fetchall()
        payload = [dict(r) for r in rows]
        return json.dumps({"trace_id": trace_id, "events": payload})

    if command == "/logs" and len(args) >= 2 and args[0] == "search":
        query = " ".join(args[1:]).strip()
        if not query:
            return json.dumps({"query": "", "events": []})
        semantic_rows = MemoryService().search_events(conn, query=query, limit=20)
        if semantic_rows:
            return json.dumps({"query": query, "events": semantic_rows})
        fts_rows: list[sqlite3.Row] = []
        fts_query = _fts_query(query)
        if fts_query:
            try:
                fts_rows = conn.execute(
                    (
                        "SELECT e.event_type, e.component, e.created_at, ef.redacted_text "
                        "FROM event_fts ef "
                        "JOIN events e ON e.id=ef.event_id "
                        "WHERE event_fts MATCH ? "
                        "ORDER BY bm25(event_fts), e.created_at DESC LIMIT 20"
                    ),
                    (fts_query,),
                ).fetchall()
            except sqlite3.OperationalError:
                fts_rows = []
        if fts_rows:
            payload = [dict(r) for r in fts_rows]
            return json.dumps({"query": query, "events": payload})
        if not fts_rows:
            like_query = f"%{query}%"
            rows = conn.execute(
                (
                    "SELECT e.event_type, e.component, e.created_at, et.redacted_text "
                    "FROM event_text et "
                    "JOIN events e ON e.id=et.event_id "
                    "WHERE et.redacted_text LIKE ? "
                    "ORDER BY e.created_at DESC LIMIT 20"
                ),
                (like_query,),
            ).fetchall()
        payload = [dict(r) for r in rows]
        return json.dumps({"query": query, "events": payload})

    if command == "/kb":
        kb = KnowledgeBaseService()
        if not args:
            return (
                "usage: /kb add <title> :: <content> | /kb search <query> | "
                "/kb list [limit] | /kb get <id-or-title>"
            )
        action = args[0].strip().lower()
        if action == "add":
            raw = " ".join(args[1:]).strip()
            if "::" not in raw:
                return "usage: /kb add <title> :: <content>"
            title, content = raw.split("::", 1)
            title = title.strip()
            content = content.strip()
            if not title or not content:
                return "usage: /kb add <title> :: <content>"
            try:
                saved = kb.put(conn, title=title, content=content)
            except ValueError as exc:
                return str(exc)
            return f"saved kb doc: {saved['id']} ({saved['title']})"
        if action == "list":
            raw_limit = args[1] if len(args) >= 2 else "10"
            try:
                limit = int(raw_limit)
            except ValueError:
                limit = 10
            items = kb.list_docs(conn, limit=limit)
            return json.dumps({"items": items})
        if action == "search":
            query = " ".join(args[1:]).strip()
            if not query:
                return "usage: /kb search <query>"
            items = kb.search(conn, query=query, limit=10)
            return json.dumps({"query": query, "items": items})
        if action == "get":
            ref = " ".join(args[1:]).strip()
            if not ref:
                return "usage: /kb get <id-or-title>"
            item = kb.get(conn, ref)
            if item is None:
                return "kb document not found"
            return json.dumps(item)
        return "unknown kb action"

    if command == "/unlock" and len(args) == 1:
        if not _is_admin(admin_ids, actor_external_id):
            return "admin required"
        code_path = Path(settings.admin_unlock_code_path)
        if not code_path.exists():
            return "unlock unavailable"
        age_seconds = datetime.now(UTC).timestamp() - code_path.stat().st_mtime
        if age_seconds > settings.admin_unlock_code_ttl_minutes * 60:
            return "unlock code expired"
        expected = code_path.read_text().strip()
        if args[0].strip() != expected:
            return "invalid unlock code"
        conn.execute(
            "UPDATE system_state SET lockdown=0, updated_at=datetime('now') WHERE id='singleton'"
        )
        emit_event(
            conn,
            EventInput(
                trace_id=new_id("trc"),
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="lockdown.cleared",
                component="commands",
                actor_type="user",
                actor_id=actor_external_id or "admin",
                payload_json=json.dumps({"source": "unlock_command"}),
                payload_redacted_json=json.dumps(redact_payload({"source": "unlock_command"})),
            ),
        )
        code_path.write_text("")
        return "lockdown cleared"

    if command == "/restart":
        if not _is_admin(admin_ids, actor_external_id):
            return "admin required"
        state = get_system_state(conn)
        if state["lockdown"] == 1:
            return "restart blocked during lockdown"
        conn.execute(
            "UPDATE system_state SET restarting=1, updated_at=datetime('now') WHERE id='singleton'"
        )
        trace_id = f"trc_restart_{thread_id}"
        _ = enqueue_restart(trace_id)
        return "restart flag set"

    if command == "/approve" and len(args) >= 1:
        if not _is_admin(admin_ids, actor_external_id):
            return "admin required"
        action = args[0].strip().lower()
        allowed_actions = {
            "host.exec.sudo",
            "host.exec.systemctl",
            "host.exec.protected_path",
            "selfupdate.apply",
        }
        if action not in allowed_actions:
            return "invalid action"
        actor = actor_external_id or "admin"
        _ = create_approval(conn, action=action, actor_id=actor)
        return f"approval created: {action}"

    return "unknown command"
