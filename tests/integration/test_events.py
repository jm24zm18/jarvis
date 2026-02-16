import json

from jarvis.db.connection import get_conn
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event


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
