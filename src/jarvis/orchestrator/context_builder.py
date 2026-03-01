"""Unified context assembly for agent prompting."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from jarvis.config import get_settings
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.memory.knowledge import KnowledgeBaseService
from jarvis.memory.knowledge_graph import KnowledgeGraph
from jarvis.memory.service import MemoryService
from jarvis.memory.skills import SkillsService
from jarvis.memory.state_renderer import render_state_section
from jarvis.memory.state_store import StateStore


@dataclass(slots=True)
class AgentContext:
    recent_messages: list[dict[str, str]]
    summary_short: str
    summary_long: str
    compact_summary: str
    structured_state: str
    semantic_hits: list[dict[str, object]]
    memory_chunks: list[str]
    skill_catalog: list[dict[str, object]]
    user_profile_snippet: str | None
    kg_facts: list[str]
    token_counts: dict[str, int]


_MEMORY_ID_PATTERN = re.compile(r"\b(mem_[a-z0-9]+)\b", re.IGNORECASE)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text.strip() else 0


def _build_skill_catalog(
    conn: sqlite3.Connection,
    *,
    actor_id: str,
    query_text: str,
) -> list[dict[str, object]]:
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
        related = skills.search(conn, query=query_text, scope=actor_id, limit=2)
        for item in related:
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

    return skill_catalog


def _resolve_thread_user_id(conn: sqlite3.Connection, thread_id: str) -> str | None:
    row = conn.execute("SELECT user_id FROM threads WHERE id=?", (thread_id,)).fetchone()
    if row is None:
        return None
    return str(row["user_id"])


def build_agent_context(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    actor_id: str,
    query_text: str,
    recent_rows: list[dict[str, str]],
    trace_id: str | None = None,
) -> AgentContext:
    settings = get_settings()
    memory = MemoryService()
    summaries = memory.thread_summary(conn, thread_id)

    state_store = StateStore()
    active_state_items = state_store.get_active_items(
        conn,
        thread_id,
        limit=max(1, int(settings.state_max_active_items)),
    )
    structured_state = render_state_section(active_state_items)
    semantic_hits = memory.search(conn, thread_id, limit=8, query=query_text or None)
    referenced_memory_ids: list[str] = []
    explicit_hits: list[dict[str, object]] = []
    if query_text:
        seen_memory_ids: set[str] = set()
        for match in _MEMORY_ID_PATTERN.findall(query_text):
            mid = str(match).strip().lower()
            if not mid or mid in seen_memory_ids:
                continue
            seen_memory_ids.add(mid)
            referenced_memory_ids.append(mid)
        for memory_id in referenced_memory_ids[:3]:
            hit = memory.get_user_memory_by_id(
                conn,
                requester_thread_id=thread_id,
                memory_id=memory_id,
                trace_id=trace_id,
            )
            if hit is not None:
                explicit_hits.append(hit)
        resolve_payload = {
            "thread_id": thread_id,
            "ids_seen": len(referenced_memory_ids),
            "ids_resolved": len(explicit_hits),
            "ids_denied": max(0, len(referenced_memory_ids) - len(explicit_hits)),
        }
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id or new_id("trc"),
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type="memory.reference.resolve",
                component="orchestrator",
                actor_type="agent",
                actor_id=actor_id,
                payload_json=json.dumps(resolve_payload),
                payload_redacted_json=json.dumps(redact_payload(resolve_payload)),
            ),
        )

    fallback_hits: list[dict[str, object]] = []
    if query_text and len(semantic_hits) < 2:
        fallback_hits = memory.search_user_memories(
            conn,
            requester_thread_id=thread_id,
            query=query_text,
            limit=4,
            exclude_thread_id=thread_id,
            trace_id=trace_id,
        )

    combined_hits: list[dict[str, object]] = []
    seen_hit_ids: set[str] = set()
    for hit in [*explicit_hits, *semantic_hits, *fallback_hits]:
        hit_id = str(hit.get("id", "")).strip()
        if not hit_id or hit_id in seen_hit_ids:
            continue
        seen_hit_ids.add(hit_id)
        combined_hits.append(hit)
    explicit_ids = {str(hit.get("id", "")).strip() for hit in explicit_hits}
    retrieved: list[str] = []
    for hit in combined_hits:
        text = str(hit.get("text", "")).strip()
        if not text:
            continue
        hit_id = str(hit.get("id", "")).strip()
        if hit_id in explicit_ids:
            retrieved.append(f"[memory:{hit_id}] {text}")
        else:
            retrieved.append(text)

    kb_context: list[str] = []
    if actor_id == "main":
        kb = KnowledgeBaseService()
        if query_text:
            kb_items = kb.search(conn, query=query_text, limit=2)
        else:
            kb_items = kb.list_docs(conn, limit=2)
        kb_context = [f"[kb:{item['title']}] {item['content']}" for item in kb_items]

    skill_catalog = _build_skill_catalog(conn, actor_id=actor_id, query_text=query_text)

    user_profile_snippet: str | None = None
    kg_facts: list[str] = []
    user_id = _resolve_thread_user_id(conn, thread_id)
    if user_id:
        profile = memory.get_user_profile(conn, user_id)
        if profile:
            summary = str(profile.get("summary", "")).strip()
            user_profile_snippet = summary[:1500] if summary else None
        if int(settings.memory_graph_enabled) == 1:
            graph = KnowledgeGraph()
            triples = graph.get_user_snapshot(conn, user_id=user_id, limit=10)
            for triple in triples:
                kg_facts.append(
                    f"{triple.get('subject', '')} "
                    f"{triple.get('predicate', '')} "
                    f"{triple.get('object', '')}"
                )

    memory_chunks = kb_context + retrieved
    if user_profile_snippet:
        memory_chunks.insert(0, f"[user-profile] {user_profile_snippet}")
    if kg_facts:
        memory_chunks.extend(f"[kg] {fact}" for fact in kg_facts[:10])

    token_counts = {
        "summary_short": _estimate_tokens(summaries.get("short", "")),
        "summary_long": _estimate_tokens(summaries.get("long", "")),
        "structured_state": _estimate_tokens(structured_state),
        "memory_chunks": sum(_estimate_tokens(chunk) for chunk in memory_chunks),
        "user_profile": _estimate_tokens(user_profile_snippet or ""),
        "kg": sum(_estimate_tokens(fact) for fact in kg_facts),
    }

    return AgentContext(
        recent_messages=recent_rows,
        summary_short=str(summaries.get("short", "")),
        summary_long=str(summaries.get("long", "")),
        compact_summary=str(summaries.get("short", "")),
        structured_state=structured_state,
        semantic_hits=combined_hits,
        memory_chunks=memory_chunks,
        skill_catalog=skill_catalog,
        user_profile_snippet=user_profile_snippet,
        kg_facts=kg_facts,
        token_counts=token_counts,
    )
