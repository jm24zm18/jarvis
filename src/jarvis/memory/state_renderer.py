"""Compact structured state renderer for prompt assembly."""

from __future__ import annotations

from datetime import datetime

from jarvis.memory.state_items import TYPE_PRIORITY, StateItem


def _confidence_rank(confidence: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(confidence, 1)


def _stamp_rank(stamp: str) -> float:
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except Exception:
        return 0.0


def _sort_key(item: StateItem) -> tuple[int, int, int, int]:
    return (
        0 if item.pinned else 1,
        TYPE_PRIORITY.get(item.type_tag, 99),
        -_confidence_rank(item.confidence),
        -int(_stamp_rank(item.last_seen_at or item.created_at) * 1_000_000),
    )


def render_state_section(items: list[StateItem]) -> str:
    if not items:
        return ""
    ordered = sorted(items, key=_sort_key, reverse=False)
    newest = max(item.last_seen_at or item.created_at for item in ordered)
    lines = [f"State (updated: {newest}, items: {len(ordered)})"]
    for item in ordered:
        status_bits: list[str] = [item.status]
        if item.confidence == "low":
            status_bits.append("low")
        status_text = ", ".join(status_bits)
        topic = f"{item.topic_tags[0]}: " if item.topic_tags else ""
        line = (
            f"[{item.uid}] {item.type_tag.upper()} ({status_text}) "
            f"{topic}{item.text} [refs:{len(item.refs)}]"
        )
        if item.conflict:
            line += " CONFLICT"
        lines.append(line)
    return "\n".join(lines)
