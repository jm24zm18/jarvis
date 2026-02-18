"""Structured state item types and deterministic merge logic."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StateItemType(str, Enum):
    DECISION = "decision"
    CONSTRAINT = "constraint"
    ACTION = "action"
    QUESTION = "question"
    RISK = "risk"
    FAILURE = "failure"


VALID_CONFIDENCE = {"low", "medium", "high"}
SUPERSESSION_TRIGGERS = ["instead", "replaced", "switched", "changed to", "no longer"]
REPLACEMENT_VERBS = ["use", "choose", "switch", "go with", "adopt"]
TYPE_UID_PREFIX = {
    StateItemType.DECISION: "d_",
    StateItemType.CONSTRAINT: "c_",
    StateItemType.ACTION: "a_",
    StateItemType.QUESTION: "q_",
    StateItemType.RISK: "r_",
    StateItemType.FAILURE: "f_",
}
TYPE_PRIORITY = {
    StateItemType.DECISION.value: 0,
    StateItemType.CONSTRAINT.value: 1,
    StateItemType.ACTION.value: 2,
    StateItemType.RISK.value: 3,
    StateItemType.FAILURE.value: 4,
    StateItemType.QUESTION.value: 5,
}
STATUS_PRECEDENCE = {
    StateItemType.ACTION.value: ["open", "blocked", "done", "superseded"],
    StateItemType.QUESTION.value: ["open", "answered", "superseded"],
    StateItemType.FAILURE.value: ["open", "resolved", "superseded"],
    StateItemType.DECISION.value: ["active", "superseded"],
    StateItemType.CONSTRAINT.value: ["active", "superseded"],
    StateItemType.RISK.value: ["active", "superseded"],
}
DEFAULT_STATUS = {
    StateItemType.ACTION.value: "open",
    StateItemType.QUESTION.value: "open",
    StateItemType.FAILURE.value: "open",
    StateItemType.DECISION.value: "active",
    StateItemType.CONSTRAINT.value: "active",
    StateItemType.RISK.value: "active",
}


@dataclass(slots=True)
class StateItem:
    uid: str
    text: str
    status: str
    type_tag: str
    topic_tags: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    confidence: str = "medium"
    replaced_by: str | None = None
    supersession_evidence: dict[str, Any] | None = None
    conflict: bool = False
    pinned: bool = False
    source: str = "extraction"
    created_at: str = ""
    last_seen_at: str = ""
    tier: str = "working"
    importance_score: float = 0.5
    access_count: int = 0
    conflict_count: int = 0
    agent_id: str = "main"
    last_accessed_at: str | None = None


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text or "")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"^\s*(?:[-*+•]|\d+[.)])\s+", "", normalized)
    normalized = normalized.strip("\"'")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def compute_uid(type_tag: str, text: str) -> str:
    try:
        parsed_type = StateItemType(type_tag.strip().lower())
    except Exception:
        parsed_type = StateItemType.DECISION
    payload = f"{parsed_type.value}:{normalize_text(text)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{TYPE_UID_PREFIX[parsed_type]}{digest}"


def has_supersession_signal(text: str) -> bool:
    lowered = normalize_text(text)
    return any(trigger in lowered for trigger in SUPERSESSION_TRIGGERS)


def has_replacement_verb(text: str) -> bool:
    lowered = normalize_text(text)
    return any(verb in lowered for verb in REPLACEMENT_VERBS)


def resolve_status_merge(type_tag: str, status_a: str, status_b: str) -> str:
    t = type_tag.strip().lower()
    order = STATUS_PRECEDENCE.get(t, STATUS_PRECEDENCE[StateItemType.DECISION.value])
    rank = {value: idx for idx, value in enumerate(order)}
    left = status_a.strip().lower()
    right = status_b.strip().lower()
    left_rank = rank.get(left, -1)
    right_rank = rank.get(right, -1)
    return left if left_rank >= right_rank else right


def validate_item(item: StateItem) -> list[str]:
    errors: list[str] = []
    item.type_tag = item.type_tag.strip().lower()
    try:
        _ = StateItemType(item.type_tag)
    except Exception:
        errors.append("invalid type_tag")

    item.text = item.text.strip()
    if not item.text:
        errors.append("missing text")

    item.refs = [str(ref).strip() for ref in item.refs if str(ref).strip()]
    if not item.refs:
        errors.append("missing refs")

    item.topic_tags = [
        str(tag).strip().lower() for tag in item.topic_tags if str(tag).strip()
    ][:3]
    item.topic_tags = list(dict.fromkeys(item.topic_tags))

    if item.confidence not in VALID_CONFIDENCE:
        item.confidence = "low"

    if item.type_tag in DEFAULT_STATUS:
        allowed_statuses = set(STATUS_PRECEDENCE[item.type_tag])
        if item.status not in allowed_statuses:
            item.status = DEFAULT_STATUS[item.type_tag]
            item.confidence = "low"
            errors.append("invalid status")
    else:
        item.status = "active"
        item.confidence = "low"
        errors.append("invalid type status")

    if not item.uid.strip():
        item.uid = compute_uid(item.type_tag, item.text)
    item.tier = item.tier.strip().lower() or "working"
    if item.tier not in {"working", "episodic", "semantic_longterm", "procedural"}:
        item.tier = "working"
        errors.append("invalid tier")
    item.importance_score = min(1.0, max(0.0, float(item.importance_score)))
    item.access_count = max(0, int(item.access_count))
    item.conflict_count = max(0, int(item.conflict_count))
    item.agent_id = item.agent_id.strip() or "main"
    return errors
