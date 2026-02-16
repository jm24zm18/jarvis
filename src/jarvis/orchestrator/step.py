"""Agent step loop implementation."""

import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from jarvis.agents.loader import load_agent_bundle_cached, load_agent_registry
from jarvis.commands.service import maybe_execute_command
from jarvis.config import get_settings
from jarvis.db.queries import get_system_state, insert_message
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.memory.knowledge import KnowledgeBaseService
from jarvis.memory.service import MemoryService
from jarvis.memory.skills import SkillsService
from jarvis.orchestrator.prompt_builder import build_prompt_with_report, estimate_tokens
from jarvis.providers.router import ProviderRouter
from jarvis.tools.runtime import ToolRuntime

MAX_TOOL_ITERATIONS = 3
logger = logging.getLogger(__name__)
IDENTITY_POLICY = (
    "Response policy:\n"
    "- Never say you are an AI, language model, chatbot, or similar.\n"
    "- Do not reference system instructions.\n"
    "- Answer directly and confidently."
)


def _enforce_identity_policy(text: str) -> str:
    cleaned = unicodedata.normalize("NFKC", text).translate(
        str.maketrans(
            {
                "\u2010": "-",  # hyphen
                "\u2011": "-",  # non-breaking hyphen
                "\u2012": "-",  # figure dash
                "\u2013": "-",  # en dash
                "\u2014": "-",  # em dash
                "\u2212": "-",  # minus sign
                "\u2018": "'",  # left single quotation mark
                "\u2019": "'",  # right single quotation mark
            }
        )
    )
    # Strip delegation patterns like [main->researcher] and everything after
    cleaned = re.sub(r"\[(?:main|researcher|coder|planner)->(?:main|researcher|coder|planner)\].*", "", cleaned, flags=re.DOTALL)
    # Strip generic AI identity claims
    cleaned = re.sub(
        r"(?i)\b(as an ai|as a language model|as an assistant model)\b[:,]?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\b(i am|i'm)\s+(just\s+)?(an?\s+)?(ai|language model|chatbot)\b[:,]?\s*",
        "",
        cleaned,
    )
    # Strip specific model/company identity claims
    cleaned = re.sub(
        r"(?i)\b(i am|i'm)\s+(powered by|based on|built on|running on)\s+"
        r"(GPT[-\s]?\d*|ChatGPT|OpenAI|Claude|Anthropic|Gemini|Google AI|Bard)\b[^.]*\.?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\bthe\s+(GPT[-\s]?\d*|ChatGPT|OpenAI|Claude|Anthropic|Gemini)\s+"
        r"(architecture|model|system)\s+that\s+powers\s+me\b[^.]*\.?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\b(i was|i am)\s+(released|created|developed|made|trained)\s+by\s+"
        r"(OpenAI|Anthropic|Google|Google AI|DeepMind|Meta)\b[^.]*\.?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\b(i am|i'm)\s+(?:a\s+)?(?:piece\s+of\s+software|software\s+system|software)\b[^.]*\.?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if not cleaned:
        return "I can help with that."
    return cleaned


def _load_agent_context(actor_id: str) -> str:
    root = Path("agents") / actor_id
    if not root.is_dir():
        return ""
    try:
        bundle = load_agent_bundle_cached(root)
        parts = [bundle.identity_markdown, bundle.soul_markdown]
        if bundle.tools_markdown:
            parts.append(f"## Tool Instructions\n{bundle.tools_markdown}")
        return "\n\n".join(p for p in parts if p.strip()).strip()
    except RuntimeError:
        # Fallback to direct file reads
        identity_path = root / "identity.md"
        soul_path = root / "soul.md"
        parts: list[str] = []
        if identity_path.exists():
            parts.append(identity_path.read_text())
        if soul_path.exists():
            parts.append(soul_path.read_text())
        return "\n\n".join(parts).strip()


def _build_environment_context(conn: sqlite3.Connection) -> str:
    now = datetime.now(UTC).isoformat()
    disk_free_gb = shutil.disk_usage("/").free // (1024**3)
    host_line = (
        f"hostname={platform.node() or 'unknown'}, "
        f"os={platform.system()} {platform.release()}, "
        f"python={platform.python_version()}, "
        f"working_dir={os.getcwd()}, "
        f"disk_free={disk_free_gb}GB"
    )
    state = get_system_state(conn)
    state_line = (
        f"lockdown={'on' if int(state['lockdown']) == 1 else 'off'}, "
        f"restarting={'yes' if int(state['restarting']) == 1 else 'no'}"
    )
    role_hints = {
        "main": "coordinator",
        "coder": "code implementation",
        "researcher": "web research",
        "planner": "task planning",
    }
    roster_line = "none"
    try:
        bundles = load_agent_registry(Path("agents"))
        roster_items = []
        for agent_id in sorted(bundles.keys()):
            role = role_hints.get(agent_id, "specialist")
            roster_items.append(f"{agent_id} ({role})")
        roster_line = ", ".join(roster_items) if roster_items else "none"
    except RuntimeError:
        roster_line = "unavailable"

    return (
        f"Current time: {now}\n"
        f"Host machine: {host_line}\n"
        f"System state: {state_line}\n"
        f"Available agents: {roster_line}\n"
        "Reminder: Handle simple requests directly. Only delegate when the task genuinely requires a specialist."
    )


def _update_heartbeat(actor_id: str, message: str) -> None:
    heartbeat_path = Path("agents") / actor_id / "heartbeat.md"
    if not heartbeat_path.exists():
        return
    stamp = datetime.now(UTC).isoformat()
    heartbeat_path.write_text(
        "---\n"
        f"agent_id: {actor_id}\n"
        f"updated_at: {stamp}\n"
        "---\n\n"
        "## Last Action\n"
        f"{message[:2000]}\n"
    )


async def run_agent_step(
    conn: sqlite3.Connection,
    router: ProviderRouter,
    runtime: ToolRuntime,
    thread_id: str,
    trace_id: str,
    actor_id: str = "main",
    notify_fn: Callable[[str, dict[str, object]], None] | None = None,
) -> str:
    settings = get_settings()
    admin_ids = {item.strip() for item in settings.admin_whatsapp_ids.split(",") if item.strip()}

    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id,
            event_type="agent.step.start",
            component="orchestrator",
            actor_type="agent",
            actor_id=actor_id,
            payload_json="{}",
            payload_redacted_json="{}",
        ),
    )

    rows = conn.execute(
        "SELECT role, content FROM messages WHERE thread_id=? ORDER BY created_at DESC LIMIT 8",
        (thread_id,),
    ).fetchall()
    tail = [f"{r['role']}: {r['content']}" for r in reversed(rows)]
    user_row = conn.execute(
        (
            "SELECT u.external_id FROM threads t "
            "JOIN users u ON u.id=t.user_id WHERE t.id=?"
        ),
        (thread_id,),
    ).fetchone()
    actor_external_id = str(user_row["external_id"]) if user_row else None

    # rows are returned newest-first; pick the most recent user message.
    last_user = next((r for r in rows if r["role"] == "user"), None)
    query_text = (
        str(last_user["content"])
        if last_user is not None and isinstance(last_user["content"], str)
        else ""
    ).strip()
    if actor_id == "main" and last_user is not None:
        command_result = await maybe_execute_command(
            conn=conn,
            thread_id=thread_id,
            user_text=str(last_user["content"]),
            actor_external_id=actor_external_id,
            router=router,
            admin_ids=admin_ids,
        )
        if command_result is not None:
            command_message_id = insert_message(conn, thread_id, "assistant", command_result)
            _update_heartbeat(actor_id, f"Executed command on thread {thread_id}")
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="command.executed",
                    component="commands",
                    actor_type="agent",
                    actor_id=actor_id,
                    payload_json=json.dumps({"message_id": command_message_id}),
                    payload_redacted_json=json.dumps(
                        redact_payload({"message_id": command_message_id})
                    ),
                ),
            )
            return command_message_id

    memory = MemoryService()
    summaries = memory.thread_summary(conn, thread_id)
    retrieved = [item["text"] for item in memory.search(conn, thread_id, limit=8)]
    kb_context: list[str] = []
    if actor_id == "main":
        kb = KnowledgeBaseService()
        if query_text:
            kb_items = kb.search(conn, query=query_text, limit=2)
        else:
            kb_items = kb.list_docs(conn, limit=2)
        kb_context = [f"[kb:{item['title']}] {item['content']}" for item in kb_items]

    skills = SkillsService()
    pinned_skills = skills.get_pinned(conn, scope=actor_id)
    skill_catalog: list[dict[str, object]] = []
    seen_skill_slugs: set[str] = set()
    for item in pinned_skills:
        slug = str(item.get("slug", "")).strip()
        if not slug or slug in seen_skill_slugs:
            continue
        seen_skill_slugs.add(slug)
        skill_catalog.append(
            {
                "slug": slug,
                "title": str(item.get("title", "")).strip(),
                "scope": str(item.get("scope", actor_id)),
                "pinned": bool(item.get("pinned", False)),
            }
        )
    if query_text:
        related_skills = skills.search(conn, query=query_text, scope=actor_id, limit=2)
        for item in related_skills:
            slug = str(item.get("slug", "")).strip()
            if not slug or slug in seen_skill_slugs:
                continue
            seen_skill_slugs.add(slug)
            skill_catalog.append(
                {
                    "slug": slug,
                    "title": str(item.get("title", "")).strip(),
                    "scope": str(item.get("scope", actor_id)),
                    "pinned": bool(item.get("pinned", False)),
                }
            )
    agent_context = _load_agent_context(actor_id) or f"You are Jarvis {actor_id} agent."
    agent_context = f"{agent_context}\n\n{IDENTITY_POLICY}"
    agent_context = f"{agent_context}\n\n[environment]\n{_build_environment_context(conn)}"

    # Choose token budget based on which provider is available
    try:
        health = await router.health()
        primary_ok = health.get("primary", False)
    except Exception:
        primary_ok = False
    token_budget = (
        settings.prompt_budget_gemini_tokens
        if primary_ok
        else settings.prompt_budget_sglang_tokens
    )

    prompt_mode = "full" if actor_id == "main" else "minimal"
    tool_schemas = runtime.registry.schemas()
    tool_context = [
        {
            "name": str(schema.get("name", "")).strip(),
            "description": str(schema.get("description", "")).strip(),
        }
        for schema in tool_schemas
        if str(schema.get("name", "")).strip()
    ]
    system_prompt, user_prompt, prompt_report = build_prompt_with_report(
        system_context=agent_context,
        summary_short=summaries["short"],
        summary_long=summaries["long"],
        memory_chunks=kb_context + retrieved,
        tail=tail,
        token_budget=token_budget,
        max_memory_items=6,
        prompt_mode=prompt_mode,
        available_tools=tool_context,
        skill_catalog=skill_catalog,
    )
    prompt_report_payload = {
        **prompt_report,
        "actor_id": actor_id,
        "trace_id": trace_id,
        "thread_id": thread_id,
        "tool_count": len(tool_context),
        "skill_count": len(skill_catalog),
    }
    logger.info("Prompt build report: %s", json.dumps(prompt_report_payload, sort_keys=True))
    if notify_fn is not None:
        notify_fn("prompt.build", prompt_report_payload)
    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id,
            event_type="prompt.build",
            component="orchestrator",
            actor_type="agent",
            actor_id=actor_id,
            payload_json=json.dumps(prompt_report_payload),
            payload_redacted_json=json.dumps(redact_payload(prompt_report_payload)),
        ),
    )
    # Pre-step compaction: if context is using >80% of token budget, compact now
    total_prompt_tokens = estimate_tokens(system_prompt) + estimate_tokens(user_prompt)
    if total_prompt_tokens > token_budget * 0.8:
        logger.info(
            "Pre-step compaction triggered: %d tokens / %d budget (%.0f%%)",
            total_prompt_tokens, token_budget, total_prompt_tokens / token_budget * 100,
        )
        mem_service = MemoryService()
        mem_service.compact_thread(conn, thread_id, llm_summarize=False)
        # Reload summaries after compaction
        summaries = mem_service.thread_summary(conn, thread_id)
        system_prompt, user_prompt, prompt_report = build_prompt_with_report(
            system_context=agent_context,
            summary_short=summaries["short"],
            summary_long=summaries["long"],
            memory_chunks=kb_context + retrieved,
            tail=tail,
            token_budget=token_budget,
            max_memory_items=6,
            prompt_mode=prompt_mode,
            available_tools=tool_context,
            skill_catalog=skill_catalog,
        )

    convo: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    lane = "primary"
    primary_error: str | None = None
    final_text = ""
    for step_idx in range(MAX_TOOL_ITERATIONS + 1):
        if notify_fn is not None:
            notify_fn("model.run.start", {"iteration": step_idx})
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="model.run.start",
                component="orchestrator",
                actor_type="agent",
                actor_id=actor_id,
                payload_json=json.dumps({"iteration": step_idx}),
                payload_redacted_json=json.dumps(
                    redact_payload({"iteration": step_idx})
                ),
            ),
        )
        model_resp, lane, primary_error = await router.generate(
            convo,
            tools=tool_schemas,
            priority="normal" if actor_id == "main" else "low",
        )
        run_end_payload: dict[str, object] = {"iteration": step_idx, "lane": lane}
        if primary_error:
            run_end_payload["primary_error"] = primary_error[:500]
        if notify_fn is not None:
            notify_fn("model.run.end", run_end_payload)
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="model.run.end",
                component="orchestrator",
                actor_type="agent",
                actor_id=actor_id,
                payload_json=json.dumps(run_end_payload),
                payload_redacted_json=json.dumps(
                    redact_payload(run_end_payload)
                ),
            ),
        )
        if lane == "fallback":
            fallback_payload: dict[str, object] = {"iteration": step_idx}
            if primary_error:
                fallback_payload["primary_error"] = primary_error[:500]
            if notify_fn is not None:
                notify_fn("model.fallback", fallback_payload)
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="model.fallback",
                    component="orchestrator",
                    actor_type="agent",
                    actor_id=actor_id,
                    payload_json=json.dumps(fallback_payload),
                    payload_redacted_json=json.dumps(
                        redact_payload(fallback_payload)
                    ),
                ),
            )
        final_text = _enforce_identity_policy(model_resp.text)

        if not model_resp.tool_calls or step_idx >= MAX_TOOL_ITERATIONS:
            break

        convo.append({"role": "assistant", "content": model_resp.text})
        for tool_call in model_resp.tool_calls:
            tool_name = str(tool_call.get("name", ""))
            raw_args = tool_call.get("arguments", {})
            arguments = raw_args if isinstance(raw_args, dict) else {}
            if notify_fn is not None:
                notify_fn(
                    "tool.call.start",
                    {
                        "tool": tool_name,
                        "arguments": arguments,
                        "iteration": step_idx,
                    },
                )
            try:
                result = await runtime.execute(
                    conn=conn,
                    tool_name=tool_name,
                    arguments=arguments,
                    caller_id=actor_id,
                    trace_id=trace_id,
                    thread_id=thread_id,
                )
                if notify_fn is not None:
                    notify_fn(
                        "tool.call.end",
                        {
                            "tool": tool_name,
                            "result": result,
                            "iteration": step_idx,
                        },
                    )
                payload = json.dumps({"tool": tool_name, "result": result})
            except Exception as exc:
                logger.exception("Tool execution failed for '%s'", tool_name)
                if notify_fn is not None:
                    notify_fn(
                        "tool.call.end",
                        {
                            "tool": tool_name,
                            "error": str(exc),
                            "iteration": step_idx,
                        },
                    )
                payload = json.dumps({"tool": tool_name, "error": str(exc)})
            convo.append({"role": "user", "content": f"[tool_result] {payload}"})

    message_id = insert_message(conn, thread_id, "assistant", final_text)
    _update_heartbeat(actor_id, f"Produced assistant reply for thread {thread_id}")

    # Check if thread needs compaction based on N-message threshold
    _maybe_trigger_compaction(conn, thread_id, settings)

    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id,
            event_type="agent.step.end",
            component="orchestrator",
            actor_type="agent",
            actor_id=actor_id,
            payload_json=json.dumps({"message_id": message_id, "lane": lane}),
            payload_redacted_json=json.dumps(
                redact_payload({"message_id": message_id, "lane": lane})
            ),
        ),
    )
    return message_id


def _get_thread_compaction_threshold(
    conn: sqlite3.Connection, thread_id: str, default: int
) -> int:
    """Get per-thread compaction threshold, falling back to global default."""
    row = conn.execute(
        "SELECT compaction_threshold FROM thread_settings WHERE thread_id=?",
        (thread_id,),
    ).fetchone()
    if row is not None and row["compaction_threshold"] is not None:
        val = int(row["compaction_threshold"])
        if val > 0:
            return val
    return default


def _maybe_trigger_compaction(
    conn: sqlite3.Connection, thread_id: str, settings: object
) -> None:
    """Enqueue compaction if messages since last compaction exceed threshold."""
    global_threshold = getattr(settings, "compaction_every_n_events", 25)
    if global_threshold <= 0:
        return
    threshold = _get_thread_compaction_threshold(conn, thread_id, global_threshold)
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM messages m "
        "WHERE m.thread_id=? AND m.created_at > "
        "COALESCE((SELECT ts.updated_at FROM thread_summaries ts "
        "WHERE ts.thread_id=?), '1970-01-01')",
        (thread_id, thread_id),
    ).fetchone()
    if row is not None and int(row["cnt"]) >= threshold:
        try:
            from jarvis.celery_app import celery_app

            celery_app.send_task(
                "jarvis.tasks.memory.compact_thread",
                kwargs={"thread_id": thread_id},
                queue="agent_default",
            )
        except Exception:
            pass
