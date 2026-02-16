"""Event model definitions."""

from dataclasses import dataclass


@dataclass(slots=True)
class EventInput:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    thread_id: str | None
    event_type: str
    component: str
    actor_type: str
    actor_id: str
    payload_json: str
    payload_redacted_json: str
