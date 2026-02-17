"""Action envelope helpers for auditable event payloads."""

from __future__ import annotations

from typing import Any


def with_action_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure all action payloads include the audit envelope keys."""
    out = dict(payload)
    out.setdefault("intent", "")
    out.setdefault("evidence", {})
    out.setdefault("plan", {})
    out.setdefault("diff", {})
    out.setdefault("tests", {})
    out.setdefault("result", {})
    return out
