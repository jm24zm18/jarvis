"""Action envelope helpers for auditable event payloads."""

from __future__ import annotations

from typing import Any

_ENVELOPE_EVENT_PREFIXES = ("tool.call.", "agent.step.", "self_update.", "policy.")
_ENVELOPE_EVENT_TYPES = {
    "evidence.check",
    "prompt.build",
    "model.run.start",
    "model.run.end",
    "model.fallback",
    "failure_capsule.lookup",
}


def requires_action_envelope(event_type: str) -> bool:
    clean = event_type.strip()
    if clean in _ENVELOPE_EVENT_TYPES:
        return True
    return any(clean.startswith(prefix) for prefix in _ENVELOPE_EVENT_PREFIXES)


def with_action_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure all action payloads include the audit envelope keys."""
    out = dict(payload)
    if not isinstance(out.get("intent"), str) or not str(out.get("intent", "")).strip():
        out["intent"] = f"audit:{str(out.get('status', 'record')).strip() or 'record'}"
    if not isinstance(out.get("evidence"), dict):
        out["evidence"] = {}
    if not isinstance(out.get("plan"), dict) or not out.get("plan"):
        out["plan"] = {"summary": "auto-generated envelope plan"}
    if not isinstance(out.get("diff"), dict):
        out["diff"] = {}
    tests = out.get("tests")
    if not isinstance(tests, dict):
        tests = {}
    if not str(tests.get("result", "")).strip():
        tests["result"] = "pending"
    out["tests"] = tests
    result = out.get("result")
    if not isinstance(result, dict):
        result = {}
    if not str(result.get("status", "")).strip():
        result["status"] = str(out.get("status", "recorded")).strip() or "recorded"
    out["result"] = result
    return out


def enforce_action_envelope(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not requires_action_envelope(event_type):
        return dict(payload)
    return with_action_envelope(payload)
