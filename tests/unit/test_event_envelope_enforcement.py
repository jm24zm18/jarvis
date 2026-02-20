import json

from jarvis.db.connection import get_conn
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload


def test_emit_event_enforces_action_envelope_for_selfupdate_events() -> None:
    with get_conn() as conn:
        emit_event(
            conn,
            EventInput(
                trace_id="trc_test",
                span_id="spn_test",
                parent_span_id=None,
                thread_id=None,
                event_type="self_update.validate",
                component="selfupdate",
                actor_type="system",
                actor_id="selfupdate",
                payload_json=json.dumps({"status": "ok"}),
                payload_redacted_json=json.dumps({"status": "ok"}),
            ),
        )
        row = conn.execute(
            "SELECT payload_redacted_json FROM events ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    payload = json.loads(str(row["payload_redacted_json"]))
    assert payload.get("status") == "ok"
    assert "intent" in payload
    assert "evidence" in payload
    assert "plan" in payload
    assert "diff" in payload
    assert "tests" in payload
    assert "result" in payload
    assert str(payload.get("intent", "")).strip() != ""
    assert str(payload.get("tests", {}).get("result", "")).strip() != ""
    assert str(payload.get("result", {}).get("status", "")).strip() != ""


def test_redact_payload_masks_whatsapp_pairing_sensitive_fields() -> None:
    payload = {
        "qrcode": "data:image/png;base64,SECRET_QR",
        "code": "123-456",
        "pairing_code": "999999",
        "nested": {"qr_code": "ABC", "phone": "+15551234567"},
    }
    redacted = redact_payload(payload)
    assert redacted["qrcode"] == "[REDACTED]"
    assert redacted["code"] == "[REDACTED]"
    assert redacted["pairing_code"] == "[REDACTED]"
    assert isinstance(redacted["nested"], dict)
    assert redacted["nested"]["qr_code"] == "[REDACTED]"
    assert redacted["nested"]["phone"] == "[REDACTED]"


def test_emit_event_enforces_evolution_item_payload_contract() -> None:
    with get_conn() as conn:
        emit_event(
            conn,
            EventInput(
                trace_id="trc_evolution",
                span_id="spn_evolution",
                parent_span_id=None,
                thread_id=None,
                event_type="evolution.item.started",
                component="governance.evolution",
                actor_type="admin",
                actor_id="usr_admin",
                payload_json=json.dumps({"item_id": "evo_1"}),
                payload_redacted_json=json.dumps({"item_id": "evo_1"}),
            ),
        )
        row = conn.execute(
            "SELECT payload_json FROM events ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    payload = json.loads(str(row["payload_json"]))
    assert payload["item_id"] == "evo_1"
    assert payload["trace_id"] == ""
    assert payload["status"] == "started"
    assert payload["evidence_refs"] == []
    assert payload["result"] == {}
