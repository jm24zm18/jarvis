"""Self-update contracts and validation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class ValidationIssue:
    field: str
    message: str


REQUIRED_EVIDENCE_FIELDS = (
    "intent",
    "file_refs",
    "line_refs",
    "policy_refs",
    "invariant_checks",
    "test_plan",
    "risk_notes",
)

ALLOWED_POLICY_REFS = {
    "deny-by-default tool access",
    "unknown tool: deny",
    "during lockdown: deny all but safe tools",
    "session tools: main agent only",
}

ALLOWED_INVARIANT_CHECKS = {
    "deny-by-default tool policy",
    "append-only database migrations",
    "traceable events schema",
    "ownership/rbac boundaries",
    "no direct master writes",
}

_PATH_RE = re.compile(r"^(?!/)(?!.*\.\.)([A-Za-z0-9._/-]+)$")
_LINE_REF_RE = re.compile(r"^(?P<path>[A-Za-z0-9._/-]+):(?P<line>[1-9]\d*)$")


def _is_valid_file_ref(value: str) -> bool:
    clean = value.strip()
    if not clean:
        return False
    candidate = clean.split(":", 1)[0]
    return bool(_PATH_RE.fullmatch(candidate))


def _is_valid_line_ref(value: str) -> bool:
    clean = value.strip()
    if not clean:
        return False
    match = _LINE_REF_RE.fullmatch(clean)
    if not match:
        return False
    return bool(_PATH_RE.fullmatch(match.group("path")))


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

    line_refs = evidence.get("line_refs")
    if not isinstance(line_refs, list) or not line_refs:
        issues.append(ValidationIssue(field="line_refs", message="must be a non-empty list"))
    elif any(not isinstance(item, str) or not _is_valid_line_ref(item) for item in line_refs):
        issues.append(
            ValidationIssue(field="line_refs", message="must be path:line with line >= 1")
        )

    file_refs = evidence.get("file_refs")
    if isinstance(file_refs, list) and file_refs:
        if any(not isinstance(item, str) or not _is_valid_file_ref(item) for item in file_refs):
            issues.append(
                ValidationIssue(
                    field="file_refs",
                    message="must contain workspace-relative paths (optionally path:line)",
                )
            )

    policy_refs = evidence.get("policy_refs")
    if isinstance(policy_refs, list) and policy_refs:
        invalid_policy_refs = [
            item
            for item in policy_refs
            if not isinstance(item, str) or item.strip() not in ALLOWED_POLICY_REFS
        ]
        if invalid_policy_refs:
            issues.append(
                ValidationIssue(
                    field="policy_refs",
                    message=f"unsupported values: {invalid_policy_refs}",
                )
            )

    invariant_checks = evidence.get("invariant_checks")
    if isinstance(invariant_checks, list) and invariant_checks:
        invalid_checks = [
            item
            for item in invariant_checks
            if not isinstance(item, str) or item.strip() not in ALLOWED_INVARIANT_CHECKS
        ]
        if invalid_checks:
            issues.append(
                ValidationIssue(
                    field="invariant_checks",
                    message=f"unsupported values: {invalid_checks}",
                )
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
            "replay": {
                "status": "pending",
                "detail": "",
                "tree_hash": "",
                "changed_files": [],
            },
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
