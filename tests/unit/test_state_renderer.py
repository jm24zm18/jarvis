from jarvis.memory.state_items import StateItem
from jarvis.memory.state_renderer import render_state_section


def test_render_state_empty_returns_empty() -> None:
    assert render_state_section([]) == ""


def test_render_state_includes_header_conflict_and_low_confidence() -> None:
    items = [
        StateItem(
            uid="r_1",
            text="No rate limiting on refresh",
            status="active",
            type_tag="risk",
            topic_tags=["security"],
            refs=["msg_1"],
            confidence="medium",
            conflict=True,
            created_at="2026-02-01T00:00:00+00:00",
            last_seen_at="2026-02-02T00:00:00+00:00",
        ),
        StateItem(
            uid="q_1",
            text="Cache embeddings client side?",
            status="open",
            type_tag="question",
            topic_tags=["arch"],
            refs=["msg_2"],
            confidence="low",
            created_at="2026-02-01T00:00:00+00:00",
            last_seen_at="2026-02-03T00:00:00+00:00",
        ),
    ]
    rendered = render_state_section(items)
    assert rendered.startswith("State (updated: 2026-02-03T00:00:00+00:00, items: 2)")
    assert "CONFLICT" in rendered
    assert "(open, low)" in rendered
