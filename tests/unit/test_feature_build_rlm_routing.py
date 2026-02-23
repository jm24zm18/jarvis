from jarvis.tasks.feature_build import run_feature_build


def test_run_feature_build_short_circuits_on_decomposition(monkeypatch):
    expected = {
        "run_id": "run123",
        "feature_id": "feat123",
        "trace_id": "trc123",
        "status": "decomposed",
        "child_ids": ["child1"],
    }
    monkeypatch.setattr(
        "jarvis.tasks.feature_build._decompose_and_split",
        lambda **kwargs: expected,
    )
    result = run_feature_build(
        run_id="run123",
        feature_id="feat123",
        trace_id="trc123",
        title="title",
        actor_id="agent",
    )
    assert result == expected


def test_run_feature_build_returns_failure_when_decompose_fails(monkeypatch):
    failure = {
        "run_id": "run456",
        "feature_id": "feat456",
        "trace_id": "trc456",
        "status": "failed",
        "error": "rlm_decompose_failed",
    }
    monkeypatch.setattr(
        "jarvis.tasks.feature_build._decompose_and_split",
        lambda **kwargs: failure,
    )
    result = run_feature_build(
        run_id="run456",
        feature_id="feat456",
        trace_id="trc456",
        title="title",
        actor_id="agent",
    )
    assert result == failure
