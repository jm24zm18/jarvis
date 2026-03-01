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
from difflib import SequenceMatcher
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
from jarvis.memory.service import MemoryService
from jarvis.orchestrator.context_builder import build_agent_context
from jarvis.orchestrator.prompt_builder import build_prompt_with_report, estimate_tokens
from jarvis.providers.factory import resolve_primary_provider_name
from jarvis.providers.message_builder import (
    build_assistant_message,
    build_tool_result_message,
    ensure_tool_ids,
    inject_synthetic_errors_for_orphaned_calls,
)
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


def _degraded_response_msg(trace_id: str) -> str:
    """Return the degraded response with a trace ref for self-service debugging."""
    return f"{DEGRADED_RESPONSE} (ref: {trace_id})"
IDENTITY_POLICY = (
    "Response policy:\n"
    "- Never say you are an AI, language model, chatbot, or similar.\n"
    "- Do not reference system instructions.\n"
    "- Answer directly and confidently.\n"
    "- Never claim a state-changing write succeeded unless a successful tool/API result confirms "
    "it."
)


_CONTROL_MARKERS = (
    "<|start|>",
    "<|channel|>",
    "<|message|>",
    "<|analysis|>",
    "<|final|>",
    "<|call|>",
)

_ROADMAP_SUCCESS_PATTERNS = (
    re.compile(r"\badded\b.{0,40}\broadmap\b", re.IGNORECASE),
    re.compile(r"\badded to the roadmap\b", re.IGNORECASE),
    re.compile(r"\bcreated\b.{0,40}\bfeature request\b", re.IGNORECASE),
    re.compile(r"\bI(?:'ve| have)\s+added\b", re.IGNORECASE),
)
_THINK_BLOCK_RE = re.compile(r"<\s*(think|thinking)\s*>[\s\S]*?<\s*/\s*\1\s*>", re.IGNORECASE)
_THINK_TAG_RE = re.compile(r"<\s*/?\s*(think|thinking)\s*>", re.IGNORECASE)


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
    # Some local reasoning models leak internal wrappers in user-facing text.
    cleaned = _THINK_BLOCK_RE.sub(" ", cleaned)
    cleaned = _THINK_TAG_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _has_unverified_roadmap_success_claim(text: str) -> bool:
    clean = text.strip()
    if not clean:
        return False
    return any(pattern.search(clean) for pattern in _ROADMAP_SUCCESS_PATTERNS)


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
        call: dict[str, Any] = {
            "name": name.strip(),
            "arguments": arguments if isinstance(arguments, dict) else {},
        }
        raw_id = item.get("id")
        if isinstance(raw_id, str) and raw_id:
            call["id"] = raw_id
        calls.append(call)
    return calls


def _normalize_single_tool_call(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name_obj = raw.get("name")
    if not isinstance(name_obj, str) or not name_obj.strip():
        return None
    args_obj = raw.get("arguments", {})
    return {"name": name_obj.strip(), "arguments": args_obj if isinstance(args_obj, dict) else {}}


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
        if isinstance(obj, dict) and (
            "tool_calls" in obj
            or ("tool" in obj and "tool_input" in obj)
            or ("tool_name" in obj and "arguments" in obj)
        ):
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
        single_raw: dict[str, Any] | None = None
        if isinstance(payload.get("tool"), str):
            single_raw = {
                "name": payload.get("tool"),
                "arguments": payload.get("tool_input", {}),
            }
        elif isinstance(payload.get("tool_name"), str):
            single_raw = {
                "name": payload.get("tool_name"),
                "arguments": payload.get("arguments", {}),
            }
        if single_raw is not None:
            single = _normalize_single_tool_call(single_raw)
            if single is not None:
                parsed_calls = [single]
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


_LEAK_PATTERNS = (
    re.compile(r"(?is)\bwe need to (?:issue|run|send)\b"),
    re.compile(r"(?is)\bnow sending\b"),
    re.compile(r"(?is)\"tool_calls?\"\s*:"),
    re.compile(r"(?is)\"tool_input\"\s*:"),
    re.compile(r"(?is)\{\s*\"tool\"\s*:"),
)


def _detect_output_leak_reason(text: str) -> str | None:
    clean = text.strip()
    if not clean:
        return None
    for pattern in _LEAK_PATTERNS:
        if pattern.search(clean):
            return pattern.pattern
    return None


def _is_build_request_prompt(text: str) -> bool:
    clean = text.strip().lower()
    if not clean:
        return False
    return clean.startswith("build feature request")


def _is_incomplete_build_response(text: str) -> str | None:
    clean = text.strip()
    if not clean:
        return "empty"
    lower = clean.lower()
    progress_markers = (
        "i'm currently",
        "i am currently",
        "i'm focused",
        "i am focused",
        "i'm going to",
        "next, i",
        "i'm checking",
        "i'm reviewing",
        "i've begun",
        "confirming the scope",
    )
    completion_markers = (
        "implemented",
        "updated",
        "changed",
        "added",
        "tests",
        "lint",
        "typecheck",
        "pull request",
        "pr ",
        "files changed",
        "diff",
    )
    has_progress = any(marker in lower for marker in progress_markers)
    has_completion = any(marker in lower for marker in completion_markers)
    if has_progress and not has_completion:
        return "build_progress_without_completion_evidence"
    return None


def _normalize_exec_host_cwd(arguments: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    if not isinstance(arguments.get("cwd"), str):
        return arguments, None
    cwd_raw = str(arguments["cwd"]).strip()
    if not cwd_raw:
        return arguments, None
    candidate = Path(cwd_raw).expanduser()
    if candidate.exists() and candidate.is_dir():
        return arguments, None
    fallback = Path.cwd()
    if fallback.parent != candidate.parent:
        return arguments, None
    similarity = SequenceMatcher(None, candidate.name.lower(), fallback.name.lower()).ratio()
    if similarity < 0.75:
        return arguments, None
    patched = dict(arguments)
    patched["cwd"] = str(fallback)
    return patched, "autocorrected_invalid_cwd"


def _tool_failure_fingerprint(
    tool_name: str,
    arguments: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    err_text = str(payload.get("error", "")).strip()[:200]
    return sha256(
        json.dumps(
            {"tool": tool_name, "arguments": arguments, "error": err_text},
            sort_keys=True,
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _tool_call_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    return sha256(
        json.dumps(
            {"tool": tool_name, "arguments": arguments},
            sort_keys=True,
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


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


def _tool_loop_terminal_fallback_message(trace_id: str) -> str:
    return (
        "I completed tool execution but could not synthesize a final summary. "
        f"Trace: {trace_id}. Review /admin/events for details and retry."
    )


async def run_agent_step(
    conn: sqlite3.Connection,
    router: ProviderRouter,
    runtime: ToolRuntime,
    thread_id: str,
    trace_id: str,
    actor_id: str = "main",
    notify_fn: Callable[[str, dict[str, object]], None] | None = None,
    progress_fn: Callable[[str, dict[str, object]], None] | None = None,
    token_scopes: frozenset[str] | None = None,
) -> str:
    settings = get_settings()
    max_tool_iterations = settings.orchestrator_max_tool_iterations
    fallback_only_retries = settings.orchestrator_fallback_only_retries
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
    build_request_mode = _is_build_request_prompt(query_text)
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
            if progress_fn is not None:
                progress_fn("phase", {"phase": "finalize", "reason": "command.short_path"})
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

    context_rows = [
        {"role": str(row["role"]), "content": str(row["content"])}
        for row in reversed(rows)
    ]
    agent_ctx = build_agent_context(
        conn,
        thread_id=thread_id,
        actor_id=actor_id,
        query_text=query_text,
        recent_rows=context_rows,
        trace_id=trace_id,
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
    token_budget = settings.prompt_budget_sglang_tokens
    if primary_provider == "openrouter":
        token_budget = settings.prompt_budget_openrouter_tokens

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
        summary_short=agent_ctx.summary_short,
        summary_long=agent_ctx.summary_long,
        structured_state=agent_ctx.structured_state,
        memory_chunks=agent_ctx.memory_chunks,
        tail=tail,
        token_budget=token_budget,
        max_memory_items=6,
        prompt_mode=prompt_mode,
        available_tools=tool_context,
        skill_catalog=agent_ctx.skill_catalog,
    )
    prompt_report_payload = {
        **prompt_report,
        "actor_id": actor_id,
        "trace_id": trace_id,
        "thread_id": thread_id,
        "tool_count": len(tool_context),
        "skill_count": len(agent_ctx.skill_catalog),
        "context_tokens": agent_ctx.token_counts,
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
        agent_ctx = build_agent_context(
            conn,
            thread_id=thread_id,
            actor_id=actor_id,
            query_text=query_text,
            recent_rows=context_rows,
            trace_id=trace_id,
        )
        system_prompt, user_prompt, prompt_report = build_prompt_with_report(
            system_context=agent_context,
            summary_short=agent_ctx.summary_short,
            summary_long=agent_ctx.summary_long,
            structured_state=agent_ctx.structured_state,
            memory_chunks=agent_ctx.memory_chunks,
            tail=tail,
            token_budget=token_budget,
            max_memory_items=6,
            prompt_mode=prompt_mode,
            available_tools=tool_context,
            skill_catalog=agent_ctx.skill_catalog,
        )

    convo: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    lane = "primary"
    primary_error: str | None = None
    final_text = ""
    tool_iteration_exhausted = False
    degraded_reason: str | None = None
    failed_tool_fingerprints: set[str] = set()
    failed_tool_signatures: set[str] = set()
    repeated_tool_signatures: dict[str, int] = {}
    verified_roadmap_item_ids: list[str] = []
    total_tool_calls = 0
    for step_idx in range(max_tool_iterations + 1):
        if progress_fn is not None:
            progress_fn("phase", {"phase": "model.run", "iteration": step_idx})
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
            final_text = _degraded_response_msg(trace_id)
            lane = "degraded"
            break
        run_end_payload: dict[str, object] = {"iteration": step_idx, "lane": lane}
        if primary_error:
            run_end_payload["primary_error"] = primary_error[:500]
            run_end_payload.update(_extract_primary_failure_fields(primary_error))
            if "skipping primary until" in primary_error.lower():
                run_end_payload["primary_skipped_due_to_cooldown"] = True
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
        total_tool_calls += len(parsed_tool_calls)
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

        if not parsed_tool_calls:
            break
        if step_idx >= max_tool_iterations:
            tool_iteration_exhausted = True
            break

        iteration_calls = ensure_tool_ids(parsed_tool_calls)
        convo.append(build_assistant_message(stripped_text, iteration_calls))
        loop_cap_threshold = max(1, int(settings.feature_build_loop_cap_threshold))
        loop_cap_reached = False
        for tool_call in iteration_calls:
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
            current_call_id = str(tool_call.get("id", ""))
            tool_name = str(tool_call.get("name", ""))
            raw_args = tool_call.get("arguments", {})
            arguments = raw_args if isinstance(raw_args, dict) else {}
            if tool_name == "exec_host":
                arguments, cwd_note = _normalize_exec_host_cwd(arguments)
            else:
                cwd_note = None
            signature = _tool_call_signature(tool_name, arguments)
            signature_count = repeated_tool_signatures.get(signature, 0) + 1
            repeated_tool_signatures[signature] = signature_count
            signature_hit_cap = build_request_mode and signature_count >= loop_cap_threshold
            if signature in failed_tool_signatures:
                suppressed_payload: dict[str, object] = {
                    "tool": tool_name,
                    "iteration": step_idx,
                    "reason": "duplicate_failing_call_suppressed",
                    "signature": signature,
                }
                if notify_fn is not None:
                    notify_fn("tool.call.suppressed", suppressed_payload)
                emit_event(
                    conn,
                    EventInput(
                        trace_id=trace_id,
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=thread_id,
                        event_type="tool.call.suppressed",
                        component="tools.runtime",
                        actor_type="agent",
                        actor_id=actor_id,
                        payload_json=json.dumps(suppressed_payload),
                        payload_redacted_json=json.dumps(redact_payload(suppressed_payload)),
                    ),
                )
                payload = json.dumps(
                    {
                        "tool": tool_name,
                        "error": "suppressed duplicate failing call",
                        "suppressed_duplicate_failure": True,
                    }
                )
                convo.append(build_tool_result_message(current_call_id, payload))
                if signature_hit_cap:
                    loop_cap_payload = {
                        "tool": tool_name,
                        "iteration": step_idx,
                        "signature": signature,
                        "count": signature_count,
                        "threshold": loop_cap_threshold,
                    }
                    if notify_fn is not None:
                        notify_fn("tool.call.loop_cap_reached", loop_cap_payload)
                    emit_event(
                        conn,
                        EventInput(
                            trace_id=trace_id,
                            span_id=new_id("spn"),
                            parent_span_id=None,
                            thread_id=thread_id,
                            event_type="tool.call.loop_cap_reached",
                            component="tools.runtime",
                            actor_type="agent",
                            actor_id=actor_id,
                            payload_json=json.dumps(loop_cap_payload),
                            payload_redacted_json=json.dumps(redact_payload(loop_cap_payload)),
                        ),
                    )
                    loop_cap_reached = True
                    tool_iteration_exhausted = True
                    break
                continue
            if progress_fn is not None:
                progress_fn(
                    "phase",
                    {"phase": "tool.exec", "iteration": step_idx, "tool": tool_name},
                )
            if notify_fn is not None:
                notify_fn(
                    "tool.call.start",
                    {
                        "tool": tool_name,
                        "arguments": arguments,
                        "iteration": step_idx,
                        "cwd_note": cwd_note,
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
                    token_scopes=token_scopes,
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
                if isinstance(result, dict):
                    code = result.get("exit_code")
                    if isinstance(code, int) and code != 0:
                        fingerprint = _tool_failure_fingerprint(
                            tool_name,
                            arguments,
                            {"error": result.get("stderr", "")},
                        )
                        failed_tool_fingerprints.add(fingerprint)
                        failed_tool_signatures.add(signature)
                    if tool_name == "create_feature_request":
                        result_ok = bool(result.get("ok"))
                        result_id = str(result.get("id", "")).strip()
                        if result_ok and result_id:
                            verified_roadmap_item_ids.append(result_id)
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
                error_payload = {
                    "tool": tool_name,
                    "error": str(exc),
                    "iteration": step_idx,
                }
                fingerprint = _tool_failure_fingerprint(tool_name, arguments, error_payload)
                if fingerprint in failed_tool_fingerprints:
                    suppressed_payload = {
                        "tool": tool_name,
                        "iteration": step_idx,
                        "reason": "duplicate_failure_suppressed",
                        "fingerprint": fingerprint,
                    }
                    if notify_fn is not None:
                        notify_fn("tool.call.suppressed", suppressed_payload)
                    emit_event(
                        conn,
                        EventInput(
                            trace_id=trace_id,
                            span_id=new_id("spn"),
                            parent_span_id=None,
                            thread_id=thread_id,
                            event_type="tool.call.suppressed",
                            component="tools.runtime",
                            actor_type="agent",
                            actor_id=actor_id,
                            payload_json=json.dumps(suppressed_payload),
                            payload_redacted_json=json.dumps(redact_payload(suppressed_payload)),
                        ),
                    )
                    if notify_fn is not None:
                        notify_fn("tool.call.end", error_payload)
                    payload = json.dumps(
                        {
                            "tool": tool_name,
                            "error": "suppressed duplicate failure",
                            "suppressed_duplicate_failure": True,
                        }
                    )
                    convo.append(build_tool_result_message(current_call_id, payload))
                    if signature_hit_cap:
                        loop_cap_payload = {
                            "tool": tool_name,
                            "iteration": step_idx,
                            "signature": signature,
                            "count": signature_count,
                            "threshold": loop_cap_threshold,
                        }
                        if notify_fn is not None:
                            notify_fn("tool.call.loop_cap_reached", loop_cap_payload)
                        emit_event(
                            conn,
                            EventInput(
                                trace_id=trace_id,
                                span_id=new_id("spn"),
                                parent_span_id=None,
                                thread_id=thread_id,
                                event_type="tool.call.loop_cap_reached",
                                component="tools.runtime",
                                actor_type="agent",
                                actor_id=actor_id,
                                payload_json=json.dumps(loop_cap_payload),
                                payload_redacted_json=json.dumps(
                                    redact_payload(loop_cap_payload)
                                ),
                            ),
                        )
                        loop_cap_reached = True
                        tool_iteration_exhausted = True
                        break
                    continue
                failed_tool_fingerprints.add(fingerprint)
                failed_tool_signatures.add(signature)
                if notify_fn is not None:
                    notify_fn(
                        "tool.call.end",
                        error_payload,
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
            convo.append(build_tool_result_message(current_call_id, payload))
            if signature_hit_cap:
                loop_cap_payload = {
                    "tool": tool_name,
                    "iteration": step_idx,
                    "signature": signature,
                    "count": signature_count,
                    "threshold": loop_cap_threshold,
                }
                if notify_fn is not None:
                    notify_fn("tool.call.loop_cap_reached", loop_cap_payload)
                emit_event(
                    conn,
                    EventInput(
                        trace_id=trace_id,
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=thread_id,
                        event_type="tool.call.loop_cap_reached",
                        component="tools.runtime",
                        actor_type="agent",
                        actor_id=actor_id,
                        payload_json=json.dumps(loop_cap_payload),
                        payload_redacted_json=json.dumps(redact_payload(loop_cap_payload)),
                    ),
                )
                loop_cap_reached = True
                tool_iteration_exhausted = True
                break

        if loop_cap_reached:
            break

    if final_text.strip() == PLACEHOLDER_RESPONSE or tool_iteration_exhausted:
        synthesis_convo = inject_synthetic_errors_for_orphaned_calls(convo) + [
            {
                "role": "user",
                "content": (
                    "All tool calls are complete. "
                    "Using only the results above, please provide a clear, direct final answer."
                ),
            }
        ]
        for retry_idx in range(fallback_only_retries):
            synthetic_iteration = max_tool_iterations + 1 + retry_idx
            start_payload: dict[str, object] = {
                "iteration": synthetic_iteration,
                "terminal_synthesis": True,
                "reason": (
                    "tool_loop_exhausted"
                    if tool_iteration_exhausted
                    else "placeholder_response"
                ),
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
                    synthesis_convo,
                    tools=None,
                    priority="normal" if actor_id == "main" else "low",
                )
            except ProviderError as exc:
                retry_error_payload: dict[str, object] = {
                    "iteration": synthetic_iteration,
                    "terminal_synthesis": True,
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
                final_text = PLACEHOLDER_RESPONSE
                degraded_reason = "provider_error_terminal_synthesis"
                lane = "degraded"
                break
            run_end_payload = {
                "iteration": synthetic_iteration,
                "lane": retry_lane,
                "terminal_synthesis": True,
            }
            if retry_primary_error:
                run_end_payload["primary_error"] = retry_primary_error[:500]
                run_end_payload.update(_extract_primary_failure_fields(retry_primary_error))
                if "skipping primary until" in retry_primary_error.lower():
                    run_end_payload["primary_skipped_due_to_cooldown"] = True
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
                    "terminal_synthesis": True,
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
                "terminal_synthesis": True,
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
        reason = (
            degraded_reason
            or (
                "placeholder_response_after_tool_loop"
                if tool_iteration_exhausted
                else "placeholder_response_after_terminal_synthesis"
            )
        )
        if reason == "placeholder_response_after_tool_loop":
            final_text = _tool_loop_terminal_fallback_message(trace_id)
        else:
            final_text = _degraded_response_msg(trace_id)
        degraded_payload: dict[str, object] = {
            "reason": reason,
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

    if build_request_mode:
        incomplete_reason = _is_incomplete_build_response(final_text)
        if incomplete_reason is not None:
            incomplete_payload: dict[str, object] = {
                "actor_id": actor_id,
                "reason": incomplete_reason,
            }
            if notify_fn is not None:
                notify_fn("agent.response.incomplete", incomplete_payload)
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="agent.response.incomplete",
                    component="orchestrator",
                    actor_type="agent",
                    actor_id=actor_id,
                    payload_json=json.dumps(incomplete_payload),
                    payload_redacted_json=json.dumps(redact_payload(incomplete_payload)),
                ),
            )

    leak_reason = _detect_output_leak_reason(final_text)
    if leak_reason is not None:
        leak_blocked_payload: dict[str, object] = {
            "actor_id": actor_id,
            "reason": "final_output_leak_guard",
            "pattern": leak_reason,
            "retry_attempted": True,
        }
        if notify_fn is not None:
            notify_fn("agent.response.leak_blocked", leak_blocked_payload)
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="agent.response.leak_blocked",
                component="orchestrator",
                actor_type="agent",
                actor_id=actor_id,
                payload_json=json.dumps(leak_blocked_payload),
                payload_redacted_json=json.dumps(redact_payload(leak_blocked_payload)),
            ),
        )
        leak_retry_iteration = max_tool_iterations + fallback_only_retries + 1
        retry_prompt = (
            "Your previous draft looked like internal/tool-planning text. "
            "Return only the final user-facing answer now. "
            "Do not mention tools, commands, or internal planning."
        )
        leak_retry_messages = convo + [{"role": "user", "content": retry_prompt}]
        leak_retry_start_payload: dict[str, object] = {
            "iteration": leak_retry_iteration,
            "terminal_synthesis": True,
            "reason": "leak_guard_retry",
        }
        if notify_fn is not None:
            notify_fn("model.run.start", leak_retry_start_payload)
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
                payload_json=json.dumps(leak_retry_start_payload),
                payload_redacted_json=json.dumps(redact_payload(leak_retry_start_payload)),
            ),
        )
        leak_retry_text = ""
        retry_failed = False
        try:
            leak_retry_resp, leak_retry_lane, leak_retry_primary_error = await router.generate(
                leak_retry_messages,
                tools=None,
                priority="normal" if actor_id == "main" else "low",
            )
            leak_retry_end_payload: dict[str, object] = {
                "iteration": leak_retry_iteration,
                "lane": leak_retry_lane,
                "terminal_synthesis": True,
                "reason": "leak_guard_retry",
            }
            if leak_retry_primary_error:
                leak_retry_end_payload["primary_error"] = leak_retry_primary_error[:500]
                leak_retry_end_payload.update(_extract_primary_failure_fields(leak_retry_primary_error))
                if "skipping primary until" in leak_retry_primary_error.lower():
                    leak_retry_end_payload["primary_skipped_due_to_cooldown"] = True
            if notify_fn is not None:
                notify_fn("model.run.end", leak_retry_end_payload)
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
                    payload_json=json.dumps(leak_retry_end_payload),
                    payload_redacted_json=json.dumps(redact_payload(leak_retry_end_payload)),
                ),
            )
            if leak_retry_lane == "fallback":
                leak_fallback_retry_payload: dict[str, object] = {
                    "iteration": leak_retry_iteration,
                    "terminal_synthesis": True,
                    "reason": "leak_guard_retry",
                }
                if leak_retry_primary_error:
                    leak_fallback_retry_payload["primary_error"] = leak_retry_primary_error[:500]
                    leak_fallback_retry_payload.update(
                        _extract_primary_failure_fields(leak_retry_primary_error)
                    )
                if notify_fn is not None:
                    notify_fn("model.fallback", leak_fallback_retry_payload)
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
                        payload_json=json.dumps(leak_fallback_retry_payload),
                        payload_redacted_json=json.dumps(redact_payload(leak_fallback_retry_payload)),
                    ),
                )
            leak_retry_text = _strip_control_tokens(
                _enforce_identity_policy(_strip_control_tokens(leak_retry_resp.text))
            )
            lane = leak_retry_lane
            if leak_retry_primary_error:
                primary_error = leak_retry_primary_error
        except ProviderError as exc:
            retry_failed = True
            leak_retry_error_payload: dict[str, object] = {
                "iteration": leak_retry_iteration,
                "terminal_synthesis": True,
                "reason": "leak_guard_retry",
                "error": str(exc),
            }
            leak_retry_error_payload.update(_extract_primary_failure_fields(str(exc)))
            if notify_fn is not None:
                notify_fn("model.run.error", leak_retry_error_payload)
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
                    payload_json=json.dumps(leak_retry_error_payload),
                    payload_redacted_json=json.dumps(redact_payload(leak_retry_error_payload)),
                ),
            )

        leak_retry_reason = _detect_output_leak_reason(leak_retry_text)
        if (
            not retry_failed
            and leak_retry_text
            and leak_retry_text != PLACEHOLDER_RESPONSE
            and leak_retry_reason is None
        ):
            final_text = leak_retry_text
        else:
            final_text = _degraded_response_msg(trace_id)

    if _has_unverified_roadmap_success_claim(final_text) and not verified_roadmap_item_ids:
        claim_blocked_payload: dict[str, object] = {
            "actor_id": actor_id,
            "reason": "unverified_roadmap_write_claim",
            "trace_id": trace_id,
        }
        if notify_fn is not None:
            notify_fn("agent.response.claim_blocked", claim_blocked_payload)
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="agent.response.claim_blocked",
                component="orchestrator",
                actor_type="agent",
                actor_id=actor_id,
                payload_json=json.dumps(claim_blocked_payload),
                payload_redacted_json=json.dumps(redact_payload(claim_blocked_payload)),
            ),
        )
        final_text = (
            "I could not verify a successful roadmap write, so nothing was added yet. "
            "I can add it now by creating a feature request and then confirm with the created ID."
        )

    message_role = "assistant" if actor_id == "main" else "agent"
    if progress_fn is not None:
        progress_fn("phase", {"phase": "finalize"})
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

    if int(settings.state_extraction_enabled) == 1:
        from jarvis.tasks import get_task_runner

        if progress_fn is not None:
            progress_fn("phase", {"phase": "state.extract"})
        queued_payload: dict[str, object] = {
            "thread_id": thread_id,
            "actor_id": actor_id,
            "trace_id": trace_id,
            "queue": "agent_default",
        }
        ok = get_task_runner().send_task(
            "jarvis.tasks.memory.extract_thread_state",
            kwargs={"thread_id": thread_id, "actor_id": actor_id, "trace_id": trace_id},
            queue="agent_default",
        )
        if ok:
            if notify_fn is not None:
                notify_fn("state.extraction.queued", queued_payload)
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="state.extraction.queued",
                    component="memory",
                    actor_type="agent",
                    actor_id=actor_id,
                    payload_json=json.dumps(queued_payload),
                    payload_redacted_json=json.dumps(redact_payload(queued_payload)),
                ),
            )
        else:
            extraction_failure_payload: dict[str, object] = {
                "thread_id": thread_id,
                "actor_id": actor_id,
                "error": "RuntimeError: failed to enqueue state extraction task",
            }
            extraction_failure_payload.update(
                _extract_primary_failure_fields(str(extraction_failure_payload["error"]))
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

    # Check if thread needs compaction based on N-message threshold
    _maybe_trigger_compaction(conn, thread_id, settings)
    if int(settings.auto_knowledge_extraction_enabled) == 1:
        _maybe_enqueue_knowledge_extraction(
            conn=conn,
            thread_id=thread_id,
            actor_id=actor_id,
            trace_id=trace_id,
            total_tool_calls=total_tool_calls,
            step_idx=step_idx,
            settings=settings,
            notify_fn=notify_fn,
        )

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


def _maybe_enqueue_knowledge_extraction(
    *,
    conn: sqlite3.Connection,
    thread_id: str,
    actor_id: str,
    trace_id: str,
    total_tool_calls: int,
    step_idx: int,
    settings: object,
    notify_fn: Callable[[str, dict[str, object]], None] | None = None,
) -> None:
    if actor_id != "main":
        return
    min_calls = max(1, int(getattr(settings, "auto_knowledge_extraction_min_tool_calls", 5)))
    if total_tool_calls < min_calls:
        return
    try:
        from jarvis.tasks import get_task_runner

        payload: dict[str, object] = {
            "thread_id": thread_id,
            "actor_id": actor_id,
            "trace_id": trace_id,
            "queue": "agent_default",
            "total_tool_calls": total_tool_calls,
            "step_idx": step_idx,
        }
        ok = get_task_runner().send_task(
            "jarvis.tasks.memory.post_task_knowledge_extraction",
            kwargs={
                "thread_id": thread_id,
                "actor_id": actor_id,
                "trace_id": trace_id,
                "total_tool_calls": total_tool_calls,
                "step_idx": step_idx,
            },
            queue="agent_default",
        )
        if not ok:
            logger.warning(
                "Failed to enqueue post_task_knowledge_extraction thread_id=%s trace_id=%s",
                thread_id,
                trace_id,
            )
            return
        if notify_fn is not None:
            notify_fn("knowledge.extraction.queued", payload)
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="knowledge.extraction.queued",
                component="memory",
                actor_type="agent",
                actor_id=actor_id,
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )
    except Exception:
        logger.warning(
            "Failed to enqueue post_task_knowledge_extraction thread_id=%s trace_id=%s",
            thread_id,
            trace_id,
            exc_info=True,
        )
