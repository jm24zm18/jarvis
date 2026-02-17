import json

from jarvis.db.connection import get_conn
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload


def test_emit_event_with_trace() -> None:
    with get_conn() as conn:
        event_id = emit_event(
            conn,
            EventInput(
                trace_id="trc_1",
                span_id="spn_1",
                parent_span_id=None,
                thread_id=None,
                event_type="unit.test",
                component="tests",
                actor_type="system",
                actor_id="pytest",
                payload_json=json.dumps({"text": "hello"}),
                payload_redacted_json=json.dumps({"text": "hello"}),
            ),
        )
        row = conn.execute(
            "SELECT trace_id, event_type FROM events WHERE id=?",
            (event_id,),
        ).fetchone()
        vec = conn.execute(
            "SELECT id FROM event_vec WHERE id=?",
            (event_id,),
        ).fetchone()
    assert row is not None
    assert row["trace_id"] == "trc_1"
    assert row["event_type"] == "unit.test"
    assert vec is not None


def test_redact_payload_redacts_nested_sensitive_keys() -> None:
    payload = {
        "safe": "ok",
        "credentials": {
            "access_token": "secret-access",
            "nested": {"password": "secret-password"},
        },
        "items": [{"api_key": "secret-key"}, {"value": 1}],
    }
    redacted = redact_payload(payload)
    assert redacted["safe"] == "ok"
    assert redacted["credentials"]["access_token"] == "[REDACTED]"
    assert redacted["credentials"]["nested"]["password"] == "[REDACTED]"
    assert redacted["items"][0]["api_key"] == "[REDACTED]"
