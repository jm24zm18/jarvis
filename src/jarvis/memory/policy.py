"""Memory governance checks (secret scan + PII redaction + audit)."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime

from jarvis.config import get_settings
from jarvis.ids import new_id

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
_SECRET_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{16,}|AIza[0-9A-Za-z\-_]{20,}|ghp_[A-Za-z0-9]{20,}|"
    r"gho_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{16,})\b"
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _mask_email(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        value = match.group(0)
        parts = value.split("@", 1)
        local = parts[0]
        domain = parts[1]
        if len(local) <= 2:
            local_masked = "*" * len(local)
        else:
            local_masked = f"{local[0]}***{local[-1]}"
        return f"{local_masked}@{domain}"

    return _EMAIL_RE.sub(_replace, text)


def _mask_phone(text: str) -> str:
    return _PHONE_RE.sub("[REDACTED_PHONE]", text)


def _emit_policy_event(
    conn: sqlite3.Connection,
    *,
    thread_id: str | None,
    actor_id: str,
    event_type: str,
    payload: dict[str, object],
) -> None:
    encoded = json.dumps(payload, sort_keys=True)
    conn.execute(
        (
            "INSERT INTO events("
            "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
            "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        (
            new_id("evt"),
            new_id("trc"),
            new_id("spn"),
            None,
            thread_id,
            event_type,
            "memory.policy",
            "agent",
            actor_id,
            encoded,
            encoded,
            _now_iso(),
        ),
    )


def record_memory_governance_decision(
    conn: sqlite3.Connection,
    *,
    thread_id: str | None,
    actor_id: str,
    target_kind: str,
    decision: str,
    reason: str,
    target_id: str = "",
    extra: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "char_count": 0,
        "decision": decision,
        "reason": reason,
    }
    if extra:
        payload.update(extra)
    try:
        conn.execute(
            (
                "INSERT INTO memory_governance_audit("
                "id, thread_id, actor_id, decision, reason, target_kind, target_id, "
                "payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?)"
            ),
            (
                new_id("evt"),
                thread_id,
                actor_id,
                decision,
                reason,
                target_kind,
                target_id,
                json.dumps(payload, sort_keys=True),
                _now_iso(),
            ),
        )
    except sqlite3.OperationalError:
        # Table not present yet (pre-migration), avoid breaking runtime.
        pass
    if decision == "redact":
        _emit_policy_event(
            conn,
            thread_id=thread_id,
            actor_id=actor_id,
            event_type="memory.policy.redaction",
            payload={"reason": reason, "target_kind": target_kind, "target_id": target_id},
        )
    elif decision == "deny":
        _emit_policy_event(
            conn,
            thread_id=thread_id,
            actor_id=actor_id,
            event_type="memory.policy.denial",
            payload={"reason": reason, "target_kind": target_kind, "target_id": target_id},
        )


def apply_memory_policy(
    conn: sqlite3.Connection,
    *,
    text: str,
    thread_id: str | None,
    actor_id: str,
    target_kind: str,
    target_id: str = "",
) -> tuple[str, str, str]:
    settings = get_settings()
    working = text
    decision = "allow"
    reason = "none"

    if int(settings.memory_secret_scan_enabled) == 1 and _SECRET_RE.search(working):
        working = _SECRET_RE.sub("[REDACTED_SECRET]", working)
        decision = "redact"
        reason = "secret_scan"

    pii_mode = settings.memory_pii_redact_mode.strip().lower()
    pii_found = bool(_EMAIL_RE.search(working) or _PHONE_RE.search(working))
    if pii_found:
        if pii_mode == "deny":
            working = "[BLOCKED_BY_MEMORY_POLICY]"
            decision = "deny"
            reason = "pii_detected"
        elif pii_mode == "mask":
            working = _mask_phone(_mask_email(working))
            decision = "redact"
            reason = "pii_masked"

    record_memory_governance_decision(
        conn,
        thread_id=thread_id,
        actor_id=actor_id,
        target_kind=target_kind,
        target_id=target_id,
        decision=decision,
        reason=reason,
        extra={"char_count": len(working)},
    )

    return working, decision, reason
