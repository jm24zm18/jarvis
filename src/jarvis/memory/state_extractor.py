"""Structured state extraction from recent thread messages."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jarvis.config import get_settings
from jarvis.memory.scope import can_agent_access_thread_memory, normalize_agent_id
from jarvis.memory.state_items import (
    DEFAULT_STATUS,
    StateItem,
    compute_uid,
    has_replacement_verb,
    has_supersession_signal,
    validate_item,
)
from jarvis.memory.state_store import StateStore
from jarvis.providers.router import ProviderRouter

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExtractResult:
    items_extracted: int = 0
    items_merged: int = 0
    items_conflicted: int = 0
    items_dropped: int = 0
    duration_ms: int = 0
    llm_ms: int = 0
    embed_ms: int = 0
    db_ms: int = 0
    skipped_reason: str | None = None


def _is_provider_quota_cooldown_error(message: str) -> bool:
    lower = message.lower()
    return (
        "quota exceeded" in lower
        and "skipping primary until" in lower
        and "runtimeerror" in lower
    )


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    payload = text.strip()
    if payload.startswith("```"):
        payload = payload.strip("`").strip()
        payload = payload.replace("json\n", "", 1).strip()
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass
    start = payload.find("[")
    end = payload.rfind("]")
    if start >= 0 and end > start:
        fragment = payload[start : end + 1]
        try:
            parsed = json.loads(fragment)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except json.JSONDecodeError:
            return []
    return []


def _existing_state_block(items: list[StateItem]) -> str:
    if not items:
        return "## Existing State\n(none)"
    lines = ["## Existing State (reference by UID — do NOT repeat unchanged items)"]
    for item in items:
        lines.append(f"[{item.uid}] {item.type_tag} ({item.status}): {item.text}")
    return "\n".join(lines)


def _messages_block(messages: list[dict[str, str]]) -> str:
    lines = ["## New Transcript"]
    for message in messages:
        lines.append(f"[{message['id']}] {message['role']}: {message['content']}")
    return "\n".join(lines)


def _to_state_item(candidate: dict[str, Any]) -> StateItem | None:
    type_tag = str(candidate.get("type_tag", "")).strip().lower()
    text = str(candidate.get("text", "")).strip()
    status = str(candidate.get("status", "")).strip().lower() or DEFAULT_STATUS.get(
        type_tag, "active"
    )
    refs_raw = candidate.get("refs", [])
    topic_raw = candidate.get("topic_tags", [])
    refs = (
        [str(v).strip() for v in refs_raw if str(v).strip()]
        if isinstance(refs_raw, list)
        else []
    )
    topics = (
        [str(v).strip().lower() for v in topic_raw if str(v).strip()]
        if isinstance(topic_raw, list)
        else []
    )
    confidence = str(candidate.get("confidence", "medium")).strip().lower()
    conflict = bool(candidate.get("conflict", False))
    uid = compute_uid(type_tag, text)
    item = StateItem(
        uid=uid,
        text=text,
        status=status,
        type_tag=type_tag,
        topic_tags=topics,
        refs=refs,
        confidence=confidence,
        conflict=conflict,
        source="extraction",
    )
    errors = validate_item(item)
    if "invalid type_tag" in errors or "missing text" in errors:
        return None
    return item


async def extract_state_items(
    conn: Any,
    thread_id: str,
    router: ProviderRouter,
    memory: Any,
    actor_id: str = "main",
    on_status_change: Callable[[str], Awaitable[None]] | None = None,
) -> ExtractResult:
    settings = get_settings()
    if int(settings.state_extraction_enabled) != 1:
        return ExtractResult(skipped_reason="disabled")
    timeout_seconds = max(1, int(settings.state_extraction_timeout_seconds))
    try:
        return await asyncio.wait_for(
            _extract_state_items_impl(
                conn=conn,
                thread_id=thread_id,
                router=router,
                memory=memory,
                actor_id=actor_id,
                on_status_change=on_status_change,
            ),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise TimeoutError(
            f"state extraction timed out after {timeout_seconds}s"
        ) from exc


async def _extract_state_items_impl(
    conn: Any,
    thread_id: str,
    router: ProviderRouter,
    memory: Any,
    actor_id: str = "main",
    on_status_change: Callable[[str], Awaitable[None]] | None = None,
) -> ExtractResult:
    started = time.perf_counter()
    settings = get_settings()
    store = StateStore()
    scoped_actor = normalize_agent_id(actor_id)
    allowed, scope_reason = can_agent_access_thread_memory(
        conn, thread_id=thread_id, agent_id=scoped_actor
    )
    if not allowed:
        if on_status_change is not None:
            await on_status_change("skipped")
        return ExtractResult(skipped_reason=scope_reason)
    max_messages = max(1, int(settings.state_extraction_max_messages))
    watermark = store.get_extraction_watermark(conn, thread_id)
    new_messages = store.get_new_messages_since(conn, thread_id, watermark, max_messages)
    if not new_messages:
        logger.debug("state extraction skipped due to watermark thread=%s", thread_id)
        if on_status_change is not None:
            await on_status_change("skipped")
        return ExtractResult(skipped_reason="no_new_messages")
    if watermark is None:
        last = new_messages[-1]
        store.set_extraction_watermark(conn, thread_id, last["created_at"], last["id"])
        if on_status_change is not None:
            await on_status_change("skipped")
        return ExtractResult(skipped_reason="bootstrap")
    user_message_ids = {
        message["id"]
        for message in new_messages
        if message.get("role", "").strip().lower() == "user"
    }
    if not user_message_ids:
        last = new_messages[-1]
        store.set_extraction_watermark(conn, thread_id, last["created_at"], last["id"])
        if on_status_change is not None:
            await on_status_change("skipped")
        return ExtractResult(skipped_reason="no_user_messages")

    existing = store.get_active_items(
        conn,
        thread_id,
        limit=max(1, int(settings.state_max_active_items)),
        agent_id=scoped_actor,
    )
    prompt = (
        "You are a structured state extractor. Given conversation messages and existing state, "
        "extract new or updated items.\n"
        "Types: decision, constraint, action, question, risk\n"
        "Each item must include: "
        "{type_tag, text, status, confidence, topic_tags, refs, supersedes, conflict}\n"
        "Rules:\n"
        "- Return only concrete and specific items.\n"
        "- Refs must be message IDs from this transcript only.\n"
        "- topic_tags: 1-3 short labels max.\n"
        "- Mark supersedes only on explicit change language.\n"
        "- Return ONLY a JSON array."
    )
    convo = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": f"{_existing_state_block(existing)}\n\n{_messages_block(new_messages)}",
        },
    ]
    llm_started = time.perf_counter()
    try:
        response, _lane, _primary_error = await asyncio.wait_for(
            router.generate(convo, tools=None, temperature=0.0, max_tokens=2048),
            timeout=max(1, int(settings.state_extraction_llm_timeout)),
        )
    except Exception as exc:
        if _is_provider_quota_cooldown_error(f"{type(exc).__name__}: {exc}"):
            if on_status_change is not None:
                await on_status_change("skipped")
            return ExtractResult(
                duration_ms=int((time.perf_counter() - started) * 1000),
                llm_ms=int((time.perf_counter() - llm_started) * 1000),
                skipped_reason="provider_quota_cooldown",
            )
        raise
    llm_ms = int((time.perf_counter() - llm_started) * 1000)
    parsed = _extract_json_array(response.text)
    candidate_items: list[StateItem] = []
    dropped = 0
    allowed_refs = {message["id"] for message in new_messages}
    role_by_id = {message["id"]: message["role"].strip().lower() for message in new_messages}
    for raw in parsed:
        item = _to_state_item(raw)
        if item is None:
            dropped += 1
            continue
        filtered_refs = [ref for ref in item.refs if ref in allowed_refs]
        if not filtered_refs:
            dropped += 1
            continue
        item.refs = filtered_refs
        candidate_items.append(item)
    if not candidate_items:
        last = new_messages[-1]
        store.set_extraction_watermark(conn, thread_id, last["created_at"], last["id"])
        if on_status_change is not None:
            await on_status_change("skipped")
        return ExtractResult(
            items_dropped=dropped,
            duration_ms=int((time.perf_counter() - started) * 1000),
            llm_ms=llm_ms,
            skipped_reason="no_valid_items",
        )

    merge_threshold = float(settings.state_extraction_merge_threshold)
    conflict_threshold = float(settings.state_extraction_conflict_threshold)
    capped_items = candidate_items[:25]
    embed_started = time.perf_counter()
    embed_func = getattr(memory, "embed_texts", None)
    if callable(embed_func):
        embeddings = await asyncio.wait_for(
            asyncio.to_thread(embed_func, [item.text for item in capped_items]),
            timeout=max(1, int(settings.state_extraction_embed_timeout)),
        )
    else:
        embeddings = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: [memory.embed_text(item.text) for item in capped_items]
            ),
            timeout=max(1, int(settings.state_extraction_embed_timeout)),
        )
    if len(embeddings) != len(capped_items):
        raise RuntimeError(
            f"embedding batch size mismatch: expected={len(capped_items)} got={len(embeddings)}"
        )
    embed_ms = int((time.perf_counter() - embed_started) * 1000)
    merged_count = 0
    conflicted_count = 0

    db_started = time.perf_counter()
    conn.execute("BEGIN")
    try:
        for item, vector in zip(capped_items, embeddings, strict=False):
            similar = store.search_similar_items(
                conn=conn,
                thread_id=thread_id,
                embedding=vector,
                type_tag=item.type_tag,
                agent_id=scoped_actor,
                limit=10,
            )
            best: dict[str, object] | None = similar[0] if similar else None
            best_score = 0.0
            if best:
                score_raw = best.get("score")
                if isinstance(score_raw, int | float):
                    best_score = float(score_raw)
                topic_tags_raw = best.get("topic_tags", [])
                topic_tags = topic_tags_raw if isinstance(topic_tags_raw, list) else []
                topic_overlap = set(item.topic_tags).intersection(
                    {str(v) for v in topic_tags if isinstance(v, str)}
                )
                if topic_overlap:
                    best_score = min(1.0, best_score + 0.02)

            if best and best_score >= merge_threshold:
                if str(best.get("status")) == "superseded":
                    dropped += 1
                    continue
                item.uid = str(best["uid"])
                store.upsert_item(conn, thread_id, item, agent_id=scoped_actor)
                store.upsert_item_embedding(
                    conn, uid=item.uid, thread_id=thread_id, embedding=vector
                )
                merged_count += 1
                continue

            if best and conflict_threshold <= best_score < merge_threshold:
                has_user_ref = any(role_by_id.get(ref) == "user" for ref in item.refs)
                should_supersede = (
                    has_supersession_signal(item.text)
                    and has_user_ref
                    and has_replacement_verb(item.text)
                )
                if should_supersede:
                    best_uid = str(best["uid"])
                    signal = next(
                        (
                            trigger
                            for trigger in (
                                "instead",
                                "replaced",
                                "switched",
                                "changed to",
                                "no longer",
                            )
                            if trigger in item.text.lower()
                        ),
                        "instead",
                    )
                    evidence = {
                        "trigger": signal,
                        "ref_msg_id": item.refs[0],
                        "candidate_uid": item.uid,
                    }
                    store.mark_superseded(
                        conn=conn,
                        uid=best_uid,
                        thread_id=thread_id,
                        replaced_by=item.uid,
                        evidence=evidence,
                    )
                    item.conflict = False
                    store.upsert_item(conn, thread_id, item, agent_id=scoped_actor)
                    store.upsert_item_embedding(
                        conn, uid=item.uid, thread_id=thread_id, embedding=vector
                    )
                    continue

                best_items = store.get_items_by_uids(conn, [str(best["uid"])], thread_id=thread_id)
                if best_items:
                    incumbent = best_items[0]
                    incumbent.conflict = True
                    store.upsert_item(conn, thread_id, incumbent, agent_id=scoped_actor)
                item.conflict = True
                store.upsert_item(conn, thread_id, item, agent_id=scoped_actor)
                store.upsert_item_embedding(
                    conn, uid=item.uid, thread_id=thread_id, embedding=vector
                )
                conflicted_count += 1
                continue

            store.upsert_item(conn, thread_id, item, agent_id=scoped_actor)
            store.upsert_item_embedding(conn, uid=item.uid, thread_id=thread_id, embedding=vector)

        last = new_messages[-1]
        store.set_extraction_watermark(conn, thread_id, last["created_at"], last["id"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    db_ms = int((time.perf_counter() - db_started) * 1000)
    if on_status_change is not None:
        await on_status_change("idle")

    return ExtractResult(
        items_extracted=len(capped_items),
        items_merged=merged_count,
        items_conflicted=conflicted_count,
        items_dropped=dropped + max(0, len(candidate_items) - len(capped_items)),
        duration_ms=int((time.perf_counter() - started) * 1000),
        llm_ms=llm_ms,
        embed_ms=embed_ms,
        db_ms=db_ms,
        skipped_reason=None,
    )
