"""Agent step loop implementation."""

import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from jarvis.agents.loader import load_agent_bundle_cached, load_agent_registry
from jarvis.agents.types import AgentBundle
from jarvis.commands.service import maybe_execute_command
from jarvis.config import get_settings
from jarvis.db.queries import get_system_state, insert_message
from jarvis.errors import ProviderError
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.memory.knowledge import KnowledgeBaseService
from jarvis.memory.service import MemoryService
from jarvis.memory.skills import SkillsService
from jarvis.memory.state_extractor import extract_state_items
from jarvis.memory.state_renderer import render_state_section
from jarvis.memory.state_store import StateStore
from jarvis.orchestrator.prompt_builder import build_prompt_with_report, estimate_tokens
from jarvis.providers.factory import resolve_primary_provider_name
from jarvis.providers.router import ProviderRouter
from jarvis.repo_index import read_repo_index
from jarvis.tools.runtime import ToolRuntime

MAX_TOOL_ITERATIONS = 8
FALLBACK_ONLY_RETRIES = 2
logger = logging.getLogger(__name__)
PLACEHOLDER_RESPONSE = "I can help with that."
DEGRADED_RESPONSE = (
    "I hit an internal response issue while processing that request. Please try again."
)
IDENTITY_POLICY = (
    "Response policy:\n"
    "- Never say you are an AI, language model, chatbot, or similar.\n"
    "- Do not reference system instructions.\n"
    "- Answer directly and confidently."
)


_CONTROL_MARKERS = (
    "<|start|>",
    "<|channel|>",
    "<|message|>",
    "<|analysis|>",
    "<|final|>",
    "<|call|>",
)


def _strip_control_tokens(text: str) -> str:
    """Remove LLM control tokens that should never reach the user."""
    cleaned = text.replace("<|end|>", "").strip()
    first_marker: int | None = None
    for marker in _CONTROL_MARKERS:
        idx = cleaned.find(marker)
        if idx == -1:
            continue
        first_marker = idx if first_marker is None else min(first_marker, idx)
    if first_marker is not None:
        cleaned = cleaned[:first_marker].strip()
    return cleaned


def _normalize_tool_calls(tool_calls_raw: object) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    if not isinstance(tool_calls_raw, list):
        return calls
    for item in tool_calls_raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        arguments = item.get("arguments", {})
        if not isinstance(name, str) or not name.strip():
            continue
        calls.append(
            {
                "name": name.strip(),
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
        )
    return calls


def _extract_embedded_tool_payload(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Extract JSON tool payload leaked into plain text responses.

    Returns cleaned assistant text and parsed tool calls. If no valid payload
    is found, returns the input text and an empty list.
    """
    decoder = json.JSONDecoder()
    best: tuple[int, int, dict[str, Any]] | None = None
    idx = 0
    while idx < len(text):
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        if isinstance(obj, dict) and "tool_calls" in obj:
            try:
                normalized = dict(obj)
            except Exception:
                normalized = {}
            best = (idx, end, normalized)
        idx = max(end, idx + 1)
    if best is None:
        return text, []

    start, end, payload = best
    parsed_calls = _normalize_tool_calls(payload.get("tool_calls"))
    if not parsed_calls:
        return text, []

    response_text = payload.get("text")
    if not isinstance(response_text, str):
        response_text = payload.get("response")
    if isinstance(response_text, str) and response_text.strip():
        cleaned_text = response_text.strip()
    else:
        cleaned_text = (text[:start] + text[end:]).strip()
    return cleaned_text, parsed_calls


def _extract_primary_failure_fields(primary_error: str) -> dict[str, object]:
    text = (primary_error or "").strip()
    if not text:
        return {}

    lower = text.lower()
    kind = "generic"
    if "timed out" in lower or "timeout" in lower:
        kind = "timeout"
    elif "quota exhausted (terminal)" in lower:
        kind = "quota_terminal"
    elif (
        "quota exceeded" in lower
        or "rate limit" in lower
        or "resource_exhausted" in lower
        or "429" in lower
    ):
        kind = "quota_retryable"
    elif "auth/permission error" in lower:
        kind = "auth_or_permission"
    elif "validation required" in lower:
        kind = "validation_required"
    elif "model unavailable" in lower or "not found" in lower:
        kind = "model_not_found"
    elif "invalid argument" in lower:
        kind = "invalid_argument"
    elif (
        "temporary failure in name resolution" in lower
        or "name or service not known" in lower
        or "nodename nor servname provided" in lower
        or "getaddrinfo failed" in lower
    ):
        kind = "dns_resolution"
    elif (
        "connecterror" in lower
        or "connection refused" in lower
        or "failed to establish a new connection" in lower
        or "connection reset" in lower
        or "network is unreachable" in lower
    ):
        kind = "transport_unavailable"

    status_code: int | None = None
    status_match = re.search(r"\b([1-5]\d{2})\b", text)
    if status_match:
        try:
            status_code = int(status_match.group(1))
        except ValueError:
            status_code = None

    retry_seconds: int | None = None
    retry_match = re.search(r"retry(?:[-\s]*after| in)\s+(\d+(?:\.\d+)?)", lower)
    if retry_match:
        try:
            retry_seconds = max(1, int(float(retry_match.group(1))))
        except ValueError:
            retry_seconds = None

    request_id: str | None = None
    req_match = re.search(r"\b(req_[a-z0-9]+)\b", lower)
    if req_match:
        request_id = req_match.group(1)

    payload: dict[str, object] = {"primary_failure_kind": kind}
    if status_code is not None:
        payload["primary_status_code"] = status_code
    if retry_seconds is not None:
        payload["primary_retry_seconds"] = retry_seconds
    if request_id is not None:
        payload["primary_request_id"] = request_id
    return payload


def _enforce_identity_policy(text: str) -> str:
    _translate_table: dict[int, str | int | None] = {
        0x2010: "-",  # hyphen
        0x2011: "-",  # non-breaking hyphen
        0x2012: "-",  # figure dash
        0x2013: "-",  # en dash
        0x2014: "-",  # em dash
        0x2212: "-",  # minus sign
        0x2018: "'",  # left single quotation mark
        0x2019: "'",  # right single quotation mark
    }
    cleaned = unicodedata.normalize("NFKC", text).translate(
        str.maketrans(_translate_table)
    )
    # Strip delegation patterns like [main->researcher] and everything after
    cleaned = re.sub(r"\[\w+->\w+\].*", "", cleaned, flags=re.DOTALL)
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
        r"(?i)\b(i am|i'm)\s+(?:a\s+)?"
        r"(?:piece\s+of\s+software|software\s+system|software)\b[^.]*\.?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    # Guard against degenerate outputs like "." after aggressive stripping.
    if not cleaned or not re.search(r"[A-Za-z0-9]", cleaned):
        return PLACEHOLDER_RESPONSE
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
        fallback_parts: list[str] = []
        if identity_path.exists():
            fallback_parts.append(identity_path.read_text())
        if soul_path.exists():
            fallback_parts.append(soul_path.read_text())
        return "\n\n".join(fallback_parts).strip()


def _load_agent_bundle(actor_id: str) -> AgentBundle | None:
    root = Path("agents") / actor_id
    if not root.is_dir():
        return None
    try:
        return load_agent_bundle_cached(root)
    except RuntimeError:
        return None


def _repo_index_context() -> str:
    payload = read_repo_index(Path.cwd())
    if not isinstance(payload, dict):
        return ""
    entrypoints = payload.get("entrypoints")
    protected = payload.get("protected_modules")
    invariants = payload.get("invariant_checks")
    lines = ["[repo_index]"]
    if isinstance(entrypoints, list) and entrypoints:
        lines.append("entrypoints: " + ", ".join(str(item) for item in entrypoints[:8]))
    if isinstance(protected, list) and protected:
        lines.append("protected_modules: " + ", ".join(str(item) for item in protected[:10]))
    if isinstance(invariants, list) and invariants:
        lines.append("invariants: " + ", ".join(str(item) for item in invariants[:10]))
    return "\n".join(lines)


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
        "tester": "test quality",
        "lintfixer": "lint & typecheck fixes",
        "api_guardian": "API contracts & auth",
        "data_migrator": "database migrations",
        "web_builder": "frontend UI",
        "security_reviewer": "security audits",
        "docs_keeper": "documentation",
        "release_ops": "release operations",
        "dependency_steward": "dependency management",
        "release_candidate": "release readiness",
        "user_simulator": "user-story simulation",
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
        "Reminder: Handle simple requests directly. "
        "Only delegate when the task genuinely requires a specialist."
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


def _enqueue_memory_index(
    *,
    trace_id: str,
    thread_id: str,
    text: str,
    metadata: dict[str, object],
) -> None:
    try:
        from jarvis.tasks import get_task_runner

        get_task_runner().send_task(
            "jarvis.tasks.memory.index_event",
            kwargs={
                "trace_id": trace_id,
                "thread_id": thread_id,
                "text": text,
                "metadata": metadata,
            },
            queue="tools_io",
        )
    except Exception:
        logger.debug("failed to enqueue assistant memory indexing", exc_info=True)


def _memory_text(payload: dict[str, object]) -> str:
    return json.dumps(redact_payload(payload), ensure_ascii=True, sort_keys=True)


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
            _enqueue_memory_index(
                trace_id=trace_id,
                thread_id=thread_id,
                text=command_result,
                metadata={
                    "role": "assistant",
                    "actor_id": actor_id,
                    "message_id": command_message_id,
                    "source": "command.executed",
                },
            )
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
    state_store = StateStore()
    if int(settings.state_extraction_enabled) == 1:
        try:
            extraction_result = await extract_state_items(
                conn=conn,
                thread_id=thread_id,
                router=router,
                memory=memory,
                actor_id=actor_id,
            )
            extraction_payload = {
                "thread_id": thread_id,
                "actor_id": actor_id,
                "items_extracted": extraction_result.items_extracted,
                "items_merged": extraction_result.items_merged,
                "items_conflicted": extraction_result.items_conflicted,
                "items_dropped": extraction_result.items_dropped,
                "duration_ms": extraction_result.duration_ms,
                "skipped_reason": extraction_result.skipped_reason,
            }
            logger.info(
                "State extraction result: %s",
                json.dumps(extraction_payload, sort_keys=True),
            )
            if notify_fn is not None:
                notify_fn("state.extraction.complete", extraction_payload)
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="state.extraction.complete",
                    component="memory",
                    actor_type="agent",
                    actor_id=actor_id,
                    payload_json=json.dumps(extraction_payload),
                    payload_redacted_json=json.dumps(redact_payload(extraction_payload)),
                ),
            )
        except Exception as exc:
            extraction_failure_payload: dict[str, object] = {
                "thread_id": thread_id,
                "actor_id": actor_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
            extraction_failure_payload.update(
                _extract_primary_failure_fields(str(extraction_failure_payload["error"]))
            )
            logger.warning(
                "Structured state extraction failed thread=%s error=%s",
                thread_id,
                extraction_failure_payload["error"],
            )
            if notify_fn is not None:
                notify_fn("state.extraction.failed", extraction_failure_payload)
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="state.extraction.failed",
                    component="memory",
                    actor_type="agent",
                    actor_id=actor_id,
                    payload_json=json.dumps(extraction_failure_payload),
                    payload_redacted_json=json.dumps(redact_payload(extraction_failure_payload)),
                ),
            )
    active_state_items = state_store.get_active_items(
        conn, thread_id, limit=max(1, int(settings.state_max_active_items))
    )
    structured_state = render_state_section(active_state_items)
    retrieved = [str(item.get("text", "")) for item in memory.search(conn, thread_id, limit=8)]
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
    bundle = _load_agent_bundle(actor_id)
    agent_context = _load_agent_context(actor_id) or f"You are Jarvis {actor_id} agent."
    max_actions_per_step = bundle.max_actions_per_step if bundle is not None else 6
    action_calls_used = 0
    agent_context = f"{agent_context}\n\n{IDENTITY_POLICY}"
    agent_context = f"{agent_context}\n\n[environment]\n{_build_environment_context(conn)}"
    repo_idx = _repo_index_context()
    if repo_idx:
        agent_context = f"{agent_context}\n\n{repo_idx}"

    primary_provider = resolve_primary_provider_name(settings)
    token_budget = (
        settings.prompt_budget_gemini_tokens
        if primary_provider == "gemini"
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
        structured_state=structured_state,
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
        active_state_items = state_store.get_active_items(
            conn, thread_id, limit=max(1, int(settings.state_max_active_items))
        )
        structured_state = render_state_section(active_state_items)
        system_prompt, user_prompt, prompt_report = build_prompt_with_report(
            system_context=agent_context,
            summary_short=summaries["short"],
            summary_long=summaries["long"],
            structured_state=structured_state,
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
        try:
            model_resp, lane, primary_error = await router.generate(
                convo,
                tools=tool_schemas,
                priority="normal" if actor_id == "main" else "low",
            )
        except ProviderError as exc:
            run_error_payload: dict[str, object] = {
                "iteration": step_idx,
                "error": str(exc),
            }
            run_error_payload.update(_extract_primary_failure_fields(str(exc)))
            if notify_fn is not None:
                notify_fn("model.run.error", run_error_payload)
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="model.run.error",
                    component="orchestrator",
                    actor_type="agent",
                    actor_id=actor_id,
                    payload_json=json.dumps(run_error_payload),
                    payload_redacted_json=json.dumps(redact_payload(run_error_payload)),
                ),
            )
            final_text = DEGRADED_RESPONSE
            lane = "degraded"
            break
        run_end_payload: dict[str, object] = {"iteration": step_idx, "lane": lane}
        if primary_error:
            run_end_payload["primary_error"] = primary_error[:500]
            run_end_payload.update(_extract_primary_failure_fields(primary_error))
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
                fallback_payload.update(_extract_primary_failure_fields(primary_error))
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
        stripped_text = _strip_control_tokens(model_resp.text)
        stripped_text, embedded_tool_calls = _extract_embedded_tool_payload(stripped_text)
        reasoning_text_raw = getattr(model_resp, "reasoning_text", "")
        reasoning_text = (
            _strip_control_tokens(reasoning_text_raw)
            if isinstance(reasoning_text_raw, str)
            else ""
        ).strip()
        reasoning_parts_raw = getattr(model_resp, "reasoning_parts", [])
        reasoning_parts = reasoning_parts_raw if isinstance(reasoning_parts_raw, list) else []
        parsed_tool_calls = (
            _normalize_tool_calls(model_resp.tool_calls)
            if model_resp.tool_calls
            else embedded_tool_calls
        )
        thought_text = reasoning_text or stripped_text
        thought_payload: dict[str, object] = {
            "iteration": step_idx,
            "lane": lane,
            "text": thought_text,
            "thought_source": (
                "provider_reasoning" if reasoning_text else "assistant_text_fallback"
            ),
            "tool_call_count": len(parsed_tool_calls),
            "tool_calls_preview": [
                str(item.get("name", ""))
                for item in parsed_tool_calls
                if isinstance(item, dict) and str(item.get("name", "")).strip()
            ],
        }
        if reasoning_parts:
            thought_payload["reasoning_parts"] = reasoning_parts
        if notify_fn is not None:
            notify_fn("agent.thought", thought_payload)
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="agent.thought",
                component="orchestrator",
                actor_type="agent",
                actor_id=actor_id,
                payload_json=json.dumps(thought_payload),
                payload_redacted_json=json.dumps(redact_payload(thought_payload)),
            ),
        )
        thought_memory_text = _memory_text(
            {
                "type": "agent.thought",
                "actor_id": actor_id,
                "iteration": step_idx,
                "lane": lane,
                "thought_source": thought_payload.get("thought_source", ""),
                "text": thought_text,
                "reasoning_parts": reasoning_parts,
                "tool_calls_preview": thought_payload.get("tool_calls_preview", []),
            }
        )
        _enqueue_memory_index(
            trace_id=trace_id,
            thread_id=thread_id,
            text=thought_memory_text,
            metadata={
                "role": "system",
                "actor_id": actor_id,
                "source": "agent.thought",
                "iteration": step_idx,
                "lane": lane,
                "thought_source": str(thought_payload.get("thought_source", "")),
                "thought_sha256": sha256(thought_memory_text.encode("utf-8")).hexdigest(),
                "thought_char_count": len(thought_memory_text),
            },
        )
        final_text = _strip_control_tokens(_enforce_identity_policy(stripped_text))

        if not parsed_tool_calls or step_idx >= MAX_TOOL_ITERATIONS:
            break

        convo.append({"role": "assistant", "content": stripped_text})
        for tool_call in parsed_tool_calls:
            if action_calls_used >= max_actions_per_step:
                deny_payload = {
                    "tool": str(tool_call.get("name", "")),
                    "allowed": False,
                    "reason": "governance.max_actions_per_step",
                    "max_actions_per_step": max_actions_per_step,
                }
                emit_event(
                    conn,
                    EventInput(
                        trace_id=trace_id,
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=thread_id,
                        event_type="policy.decision",
                        component="policy",
                        actor_type="agent",
                        actor_id=actor_id,
                        payload_json=json.dumps(deny_payload),
                        payload_redacted_json=json.dumps(redact_payload(deny_payload)),
                    ),
                )
                break
            action_calls_used += 1
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
                tool_memory_text = _memory_text(
                    {
                        "type": "tool.call.end",
                        "status": "success",
                        "tool": tool_name,
                        "iteration": step_idx + 1,
                        "result": result,
                    }
                )
                _enqueue_memory_index(
                    trace_id=trace_id,
                    thread_id=thread_id,
                    text=tool_memory_text,
                    metadata={
                        "role": "system",
                        "actor_id": actor_id,
                        "source": "tool.call.end",
                        "tool": tool_name,
                        "status": "success",
                        "iteration": step_idx,
                        "result_sha256": sha256(tool_memory_text.encode("utf-8")).hexdigest(),
                        "result_char_count": len(tool_memory_text),
                    },
                )
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
                tool_error_memory_text = _memory_text(
                    {
                        "type": "tool.call.end",
                        "status": "error",
                        "tool": tool_name,
                        "iteration": step_idx + 1,
                        "error": str(exc),
                    }
                )
                _enqueue_memory_index(
                    trace_id=trace_id,
                    thread_id=thread_id,
                    text=tool_error_memory_text,
                    metadata={
                        "role": "system",
                        "actor_id": actor_id,
                        "source": "tool.call.end",
                        "tool": tool_name,
                        "status": "error",
                        "iteration": step_idx,
                        "result_sha256": sha256(
                            tool_error_memory_text.encode("utf-8")
                        ).hexdigest(),
                        "result_char_count": len(tool_error_memory_text),
                    },
                )
            convo.append({"role": "user", "content": f"[tool_result] {payload}"})

    if lane == "fallback" and final_text.strip() == PLACEHOLDER_RESPONSE:
        for retry_idx in range(FALLBACK_ONLY_RETRIES):
            synthetic_iteration = MAX_TOOL_ITERATIONS + 1 + retry_idx
            start_payload: dict[str, object] = {
                "iteration": synthetic_iteration,
                "fallback_only": True,
            }
            if notify_fn is not None:
                notify_fn("model.run.start", start_payload)
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
                    payload_json=json.dumps(start_payload),
                    payload_redacted_json=json.dumps(redact_payload(start_payload)),
                ),
            )
            try:
                retry_resp, retry_lane, retry_primary_error = await router.generate(
                    convo,
                    tools=None,
                    priority="normal" if actor_id == "main" else "low",
                )
            except ProviderError as exc:
                retry_error_payload: dict[str, object] = {
                    "iteration": synthetic_iteration,
                    "fallback_only": True,
                    "error": str(exc),
                }
                retry_error_payload.update(_extract_primary_failure_fields(str(exc)))
                if notify_fn is not None:
                    notify_fn("model.run.error", retry_error_payload)
                emit_event(
                    conn,
                    EventInput(
                        trace_id=trace_id,
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=thread_id,
                        event_type="model.run.error",
                        component="orchestrator",
                        actor_type="agent",
                        actor_id=actor_id,
                        payload_json=json.dumps(retry_error_payload),
                        payload_redacted_json=json.dumps(redact_payload(retry_error_payload)),
                    ),
                )
                final_text = DEGRADED_RESPONSE
                lane = "degraded"
                break
            run_end_payload = {
                "iteration": synthetic_iteration,
                "lane": retry_lane,
                "fallback_only": True,
            }
            if retry_primary_error:
                run_end_payload["primary_error"] = retry_primary_error[:500]
                run_end_payload.update(_extract_primary_failure_fields(retry_primary_error))
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
                    payload_redacted_json=json.dumps(redact_payload(run_end_payload)),
                ),
            )
            if retry_lane == "fallback":
                fallback_retry_payload: dict[str, object] = {
                    "iteration": synthetic_iteration,
                    "fallback_only": True,
                }
                if retry_primary_error:
                    fallback_retry_payload["primary_error"] = retry_primary_error[:500]
                    fallback_retry_payload.update(
                        _extract_primary_failure_fields(retry_primary_error)
                    )
                if notify_fn is not None:
                    notify_fn("model.fallback", fallback_retry_payload)
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
                        payload_json=json.dumps(fallback_retry_payload),
                        payload_redacted_json=json.dumps(
                            redact_payload(fallback_retry_payload)
                        ),
                    ),
                )
            retry_text = _strip_control_tokens(
                _enforce_identity_policy(_strip_control_tokens(retry_resp.text))
            )
            retry_reasoning_raw = getattr(retry_resp, "reasoning_text", "")
            retry_reasoning = (
                _strip_control_tokens(retry_reasoning_raw)
                if isinstance(retry_reasoning_raw, str)
                else ""
            ).strip()
            retry_reasoning_parts_raw = getattr(retry_resp, "reasoning_parts", [])
            retry_reasoning_parts = (
                retry_reasoning_parts_raw if isinstance(retry_reasoning_parts_raw, list) else []
            )
            retry_thought_payload: dict[str, object] = {
                "iteration": synthetic_iteration,
                "lane": retry_lane,
                "fallback_only": True,
                "text": retry_reasoning or _strip_control_tokens(retry_resp.text),
                "thought_source": (
                    "provider_reasoning"
                    if retry_reasoning
                    else "assistant_text_fallback"
                ),
                "tool_call_count": 0,
                "tool_calls_preview": [],
            }
            if retry_reasoning_parts:
                retry_thought_payload["reasoning_parts"] = retry_reasoning_parts
            if notify_fn is not None:
                notify_fn("agent.thought", retry_thought_payload)
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="agent.thought",
                    component="orchestrator",
                    actor_type="agent",
                    actor_id=actor_id,
                    payload_json=json.dumps(retry_thought_payload),
                    payload_redacted_json=json.dumps(redact_payload(retry_thought_payload)),
                ),
            )
            retry_memory_text = _memory_text(
                {
                    "type": "agent.thought",
                    "actor_id": actor_id,
                    "iteration": synthetic_iteration,
                    "lane": retry_lane,
                    "thought_source": retry_thought_payload.get("thought_source", ""),
                    "text": retry_thought_payload.get("text", ""),
                    "reasoning_parts": retry_reasoning_parts,
                    "tool_calls_preview": retry_thought_payload.get("tool_calls_preview", []),
                }
            )
            _enqueue_memory_index(
                trace_id=trace_id,
                thread_id=thread_id,
                text=retry_memory_text,
                metadata={
                    "role": "system",
                    "actor_id": actor_id,
                    "source": "agent.thought",
                    "iteration": synthetic_iteration,
                    "lane": retry_lane,
                    "thought_source": str(retry_thought_payload.get("thought_source", "")),
                    "thought_sha256": sha256(retry_memory_text.encode("utf-8")).hexdigest(),
                    "thought_char_count": len(retry_memory_text),
                },
            )
            if retry_text and retry_text != PLACEHOLDER_RESPONSE:
                final_text = retry_text
                lane = retry_lane
                if retry_primary_error:
                    primary_error = retry_primary_error
                break

    if final_text.strip() == PLACEHOLDER_RESPONSE:
        final_text = DEGRADED_RESPONSE
        degraded_payload: dict[str, object] = {
            "reason": "placeholder_response",
            "actor_id": actor_id,
        }
        if notify_fn is not None:
            notify_fn("agent.response.degraded", degraded_payload)
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="agent.response.degraded",
                component="orchestrator",
                actor_type="agent",
                actor_id=actor_id,
                payload_json=json.dumps(degraded_payload),
                payload_redacted_json=json.dumps(redact_payload(degraded_payload)),
            ),
        )

    message_role = "assistant" if actor_id == "main" else "agent"
    message_id = insert_message(conn, thread_id, message_role, final_text)
    _enqueue_memory_index(
        trace_id=trace_id,
        thread_id=thread_id,
        text=final_text,
        metadata={
            "role": message_role,
            "actor_id": actor_id,
            "message_id": message_id,
            "source": "agent.step.end",
            "lane": lane,
        },
    )
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
            from jarvis.tasks import get_task_runner

            get_task_runner().send_task(
                "jarvis.tasks.memory.compact_thread",
                kwargs={"thread_id": thread_id},
                queue="agent_default",
            )
        except Exception:
            pass
