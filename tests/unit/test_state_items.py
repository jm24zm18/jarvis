from jarvis.memory.state_items import (
    StateItem,
    compute_uid,
    has_supersession_signal,
    normalize_text,
    resolve_status_merge,
    validate_item,
)


def test_normalize_text_and_uid_prefix() -> None:
    assert normalize_text('  - "Use Redis"  ') == "use redis"
    uid = compute_uid("decision", "Use Redis")
    assert uid.startswith("d_")
    assert len(uid) == 14


def test_validate_item_coerces_invalid_status_to_default_and_low_confidence() -> None:
    item = StateItem(
        uid="",
        text="Run migration 025",
        status="invalid",
        type_tag="action",
        topic_tags=["db"],
        refs=["msg_1"],
        confidence="high",
    )
    errors = validate_item(item)
    assert "invalid status" in errors
    assert item.status == "open"
    assert item.confidence == "low"
    assert item.uid.startswith("a_")


def test_supersession_signal_and_status_precedence() -> None:
    assert has_supersession_signal("Switch to postgres instead of sqlite")
    merged = resolve_status_merge("action", "open", "done")
    assert merged == "done"


def test_failure_type_uid_prefix_and_default_status() -> None:
    item = StateItem(
        uid="",
        text="socket timeout during deploy",
        status="",
        type_tag="failure",
        topic_tags=["deploy"],
        refs=["msg_9"],
    )
    errors = validate_item(item)
    assert "invalid type_tag" not in errors
    assert item.uid.startswith("f_")
    assert item.status == "open"
