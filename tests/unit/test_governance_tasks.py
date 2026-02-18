import json

from jarvis.tasks import dependency_steward, release_candidate


def test_dependency_steward_parses_proposals(monkeypatch) -> None:
    class _Proc:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "a", "version": "1.0.0", "latest_version": "1.1.0"},
                {"name": "b", "version": "1.0.0", "latest_version": "2.0.0"},
            ]
        )
        stderr = ""

    monkeypatch.setenv("DEPENDENCY_STEWARD_ENABLED", "1")
    dependency_steward.get_settings.cache_clear()
    monkeypatch.setattr(dependency_steward.subprocess, "run", lambda *args, **kwargs: _Proc())
    result = dependency_steward.run_dependency_steward()
    assert result["status"] == "ok"
    assert len(result["proposals"]) >= 1


def test_release_candidate_has_blockers_when_story_missing(monkeypatch) -> None:
    monkeypatch.setenv("RELEASE_CANDIDATE_AGENT_ENABLED", "1")
    release_candidate.get_settings.cache_clear()
    monkeypatch.setattr(release_candidate, "latest_story_pack_status", lambda pack: "missing")
    result = release_candidate.build_release_candidate()
    assert result["status"] == "blocked"
    assert isinstance(result["blockers"], list)
