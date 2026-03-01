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


def test_run_feature_build_forces_decompose_for_broad_scope_when_rlm_disabled(monkeypatch):
    monkeypatch.setenv("FEATURE_BUILD_USE_RLM", "0")
    monkeypatch.setenv("RLM_ENABLED", "0")
    monkeypatch.setenv("FEATURE_BUILD_AUTO_DECOMPOSE", "1")
    from jarvis.config import get_settings

    get_settings.cache_clear()
    captured: dict[str, object] = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return {
            "run_id": "run789",
            "feature_id": "feat789",
            "trace_id": "trc789",
            "status": "decomposed",
            "child_ids": ["child1", "child2", "child3"],
        }

    monkeypatch.setattr("jarvis.tasks.feature_build._decompose_and_split", _capture)
    result = run_feature_build(
        run_id="run789",
        feature_id="feat789",
        trace_id="trc789",
        title="Custom Skill Builder UI API",
        actor_id="agent",
    )
    assert result["status"] == "decomposed"
    assert captured.get("force") is True
    assert captured.get("use_fallback") is True
