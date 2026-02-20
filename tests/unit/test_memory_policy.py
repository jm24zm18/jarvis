from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.memory.policy import apply_memory_policy


def test_apply_memory_policy_masks_and_emits_redaction_event(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_SECRET_SCAN_ENABLED", "1")
    monkeypatch.setenv("MEMORY_PII_REDACT_MODE", "mask")
    get_settings.cache_clear()

    with get_conn() as conn:
        text, decision, reason = apply_memory_policy(
            conn,
            text="email me at alice@example.com phone 415-555-0100 key sk-abcDEF1234567890",
            thread_id="thr_mem_policy_redact",
            actor_id="main",
            target_kind="memory_item",
            target_id="mem_1",
        )
        assert decision == "redact"
        assert reason == "pii_masked"
        assert "[REDACTED_SECRET]" in text
        assert "[REDACTED_PHONE]" in text
        assert "a***e@example.com" in text

        event_row = conn.execute(
            (
                "SELECT event_type, payload_json FROM events "
                "WHERE thread_id=? ORDER BY created_at DESC LIMIT 1"
            ),
            ("thr_mem_policy_redact",),
        ).fetchone()
        assert event_row is not None
        assert str(event_row["event_type"]) == "memory.policy.redaction"
        assert "memory_item" in str(event_row["payload_json"])

        audit_row = conn.execute(
            (
                "SELECT decision, reason FROM memory_governance_audit "
                "WHERE thread_id=? ORDER BY created_at DESC LIMIT 1"
            ),
            ("thr_mem_policy_redact",),
        ).fetchone()
        assert audit_row is not None
        assert str(audit_row["decision"]) == "redact"
        assert str(audit_row["reason"]) == "pii_masked"


def test_apply_memory_policy_denies_and_emits_denial_event(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_SECRET_SCAN_ENABLED", "0")
    monkeypatch.setenv("MEMORY_PII_REDACT_MODE", "deny")
    get_settings.cache_clear()

    with get_conn() as conn:
        text, decision, reason = apply_memory_policy(
            conn,
            text="contact bob@example.com",
            thread_id="thr_mem_policy_deny",
            actor_id="main",
            target_kind="memory_item",
            target_id="mem_2",
        )
        assert text == "[BLOCKED_BY_MEMORY_POLICY]"
        assert decision == "deny"
        assert reason == "pii_detected"

        event_row = conn.execute(
            (
                "SELECT event_type, payload_json FROM events "
                "WHERE thread_id=? ORDER BY created_at DESC LIMIT 1"
            ),
            ("thr_mem_policy_deny",),
        ).fetchone()
        assert event_row is not None
        assert str(event_row["event_type"]) == "memory.policy.denial"
        assert "pii_detected" in str(event_row["payload_json"])

        audit_row = conn.execute(
            (
                "SELECT decision, reason FROM memory_governance_audit "
                "WHERE thread_id=? ORDER BY created_at DESC LIMIT 1"
            ),
            ("thr_mem_policy_deny",),
        ).fetchone()
        assert audit_row is not None
        assert str(audit_row["decision"]) == "deny"
        assert str(audit_row["reason"]) == "pii_detected"
