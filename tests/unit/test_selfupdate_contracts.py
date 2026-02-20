from jarvis.selfupdate.contracts import validate_evidence_context, validate_evidence_packet
from jarvis.selfupdate.pipeline import evaluate_test_first_gate


def _evidence() -> dict[str, object]:
    return {
        "intent": "apply patch safely",
        "file_refs": ["src/jarvis/tools/runtime.py:10"],
        "line_refs": ["src/jarvis/tools/runtime.py:10"],
        "policy_refs": ["deny-by-default tool access"],
        "invariant_checks": ["append-only database migrations"],
        "test_plan": ["pytest tests -q"],
        "risk_notes": ["low risk"],
    }


def test_validate_evidence_packet_requires_line_refs() -> None:
    evidence = _evidence()
    del evidence["line_refs"]
    issues = validate_evidence_packet(evidence)
    assert any(item.field == "line_refs" for item in issues)


def test_validate_evidence_packet_rejects_invalid_policy_refs() -> None:
    evidence = _evidence()
    evidence["policy_refs"] = ["not-a-policy"]
    issues = validate_evidence_packet(evidence)
    assert any(item.field == "policy_refs" for item in issues)


def test_validate_evidence_packet_rejects_invalid_invariant_checks() -> None:
    evidence = _evidence()
    evidence["invariant_checks"] = ["append-only migrations"]
    issues = validate_evidence_packet(evidence)
    assert any(item.field == "invariant_checks" for item in issues)


def test_validate_evidence_context_rejects_file_ref_not_in_patch() -> None:
    evidence = _evidence()
    evidence["file_refs"] = ["src/unknown.py:1"]
    issues = validate_evidence_context(
        evidence,
        changed_files=["src/jarvis/tools/runtime.py"],
        critical_change=False,
    )
    assert any(item.field == "file_refs" for item in issues)


def test_validate_evidence_context_requires_test_plan_for_critical_change() -> None:
    evidence = _evidence()
    evidence["test_plan"] = []
    issues = validate_evidence_context(
        evidence,
        changed_files=["src/jarvis/tools/runtime.py"],
        critical_change=True,
    )
    assert any(item.field == "test_plan" for item in issues)


def test_evaluate_test_first_gate_returns_typed_failure_codes() -> None:
    ok, failures, detail = evaluate_test_first_gate(
        artifact={"tests": {"result": "pending"}},
        changed_files=["src/jarvis/tools/runtime.py"],
        critical_patterns=["src/jarvis/tools/**"],
        min_coverage_pct=80.0,
        require_critical_path_tests=True,
    )
    assert ok is False
    codes = {item["code"] for item in failures}
    assert "missing_test_evidence" in codes
    assert "missing_coverage_evidence" in codes
    assert "critical_path_tests_missing" in codes
    assert detail["critical_change"] is True
