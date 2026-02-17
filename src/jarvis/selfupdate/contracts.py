"""Self-update contracts and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ValidationIssue:
    field: str
    message: str


REQUIRED_EVIDENCE_FIELDS = (
    "intent",
    "file_refs",
    "policy_refs",
    "invariant_checks",
    "test_plan",
    "risk_notes",
)


def validate_evidence_packet(evidence: dict[str, object] | None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(evidence, dict):
        return [ValidationIssue(field="evidence", message="missing evidence payload")]

    for key in REQUIRED_EVIDENCE_FIELDS:
        if key not in evidence:
            issues.append(ValidationIssue(field=key, message="required"))

    intent = evidence.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        issues.append(ValidationIssue(field="intent", message="must be non-empty string"))

    for list_field in ("file_refs", "policy_refs", "invariant_checks", "risk_notes"):
        value = evidence.get(list_field)
        if not isinstance(value, list) or not value:
            issues.append(ValidationIssue(field=list_field, message="must be a non-empty list"))
            continue
        if any(not isinstance(item, str) or not item.strip() for item in value):
            issues.append(
                ValidationIssue(field=list_field, message="must contain non-empty strings")
            )

    test_plan = evidence.get("test_plan")
    if not isinstance(test_plan, list) or not test_plan:
        issues.append(ValidationIssue(field="test_plan", message="must be a non-empty list"))
    elif any(not isinstance(item, str) or not item.strip() for item in test_plan):
        issues.append(ValidationIssue(field="test_plan", message="must contain non-empty commands"))

    return issues


def default_artifact(
    *,
    trace_id: str,
    rationale: str,
    evidence: dict[str, object],
    patch_text: str,
) -> dict[str, object]:
    return {
        "trace_id": trace_id,
        "plan": {
            "rationale": rationale,
        },
        "evidence": evidence,
        "diff": {
            "char_count": len(patch_text),
        },
        "tests": {
            "commands": evidence.get("test_plan", []),
            "result": "pending",
            "detail": "",
        },
        "verification": {
            "status": "pending",
            "detail": "",
        },
        "risk": {
            "notes": evidence.get("risk_notes", []),
        },
        "rollback": {
            "status": "available",
            "detail": "",
        },
        "pr": {
            "status": "not_requested",
            "branch": "",
            "url": "",
            "number": None,
            "detail": "",
        },
    }
