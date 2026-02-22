from jarvis.orchestrator.step import _is_incomplete_build_response


def test_incomplete_build_response_detects_progress_only_text() -> None:
    reason = _is_incomplete_build_response(
        "I'm currently reviewing files and I'm going to check requirements next."
    )
    assert reason == "build_progress_without_completion_evidence"


def test_incomplete_build_response_allows_completion_summary() -> None:
    reason = _is_incomplete_build_response(
        "Implemented changes in src/a.py, updated tests, and ran lint/typecheck successfully."
    )
    assert reason is None
