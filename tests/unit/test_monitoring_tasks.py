from jarvis.tasks.monitoring import monitor_queue_backpressure


def test_monitor_queue_backpressure_emits_alerts(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.tasks.monitoring._queue_depth_by_name",
        lambda: {"agent_priority": 10, "local_llm": 25},
    )
    monkeypatch.setattr(
        "jarvis.tasks.monitoring._thresholds",
        lambda: {
            "agent_priority": 5,
            "agent_default": 500,
            "tools_io": 500,
            "local_llm": 10,
        },
    )
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "jarvis.tasks.monitoring._emit",
        lambda trace_id, event_type, payload: events.append((event_type, payload)),
    )
    monkeypatch.setattr("jarvis.tasks.monitoring._send_pagerduty", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("jarvis.tasks.monitoring._send_slack", lambda *_args, **_kwargs: None)

    result = monitor_queue_backpressure()
    assert result["ok"] is True
    assert len(result["alerts"]) == 2
    assert any(item[0] == "queue.backpressure" for item in events)
    assert any(item[0] == "router.local_llm.shifted" for item in events)
