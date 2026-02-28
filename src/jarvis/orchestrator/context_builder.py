"""Unified context assembly for agent prompting."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from jarvis.config import get_settings
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
    retrieved = [str(item.get("text", "")).strip() for item in semantic_hits if item.get("text")]

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
        semantic_hits=semantic_hits,
        memory_chunks=memory_chunks,
        skill_catalog=skill_catalog,
        user_profile_snippet=user_profile_snippet,
        kg_facts=kg_facts,
        token_counts=token_counts,
    )
