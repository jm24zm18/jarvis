from jarvis.events.envelope import with_action_envelope


def test_with_action_envelope_adds_required_keys() -> None:
    payload = {"status": "ok"}
    out = with_action_envelope(payload)
    assert out["status"] == "ok"
    assert "intent" in out
    assert "evidence" in out
    assert "plan" in out
    assert "diff" in out
    assert "tests" in out
    assert "result" in out


def test_with_action_envelope_preserves_existing_values() -> None:
    payload = {
        "intent": "ship patch",
        "evidence": {"file_refs": ["x.py"]},
        "plan": {"steps": 1},
        "diff": {"char_count": 10},
        "tests": {"result": "passed"},
        "result": {"status": "ok"},
    }
    out = with_action_envelope(payload)
    assert out["intent"] == "ship patch"
    assert out["evidence"]["file_refs"] == ["x.py"]
    assert out["result"]["status"] == "ok"
