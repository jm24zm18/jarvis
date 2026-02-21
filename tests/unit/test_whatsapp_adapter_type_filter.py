"""Unit tests for WhatsApp adapter history-sync (type: "append") filtering."""

from jarvis.channels.whatsapp.adapter import WhatsAppAdapter


def _notify_payload(messages: list | None = None) -> dict:
    return {
        "event": "messages.upsert",
        "data": {
            "type": "notify",
            "messages": messages or [
                {
                    "key": {
                        "id": "msg_001",
                        "remoteJid": "15551234567@s.whatsapp.net",
                        "fromMe": False,
                    },
                    "message": {"conversation": "hello"},
                    "status": "RECEIVED",
                }
            ],
        },
    }


def _append_payload() -> dict:
    return {
        "event": "messages.upsert",
        "data": {
            "type": "append",
            "messages": [
                {
                    "key": {
                        "id": "hist_001",
                        "remoteJid": "15559876543@s.whatsapp.net",
                        "fromMe": False,
                    },
                    "message": {"conversation": "old history message"},
                    "status": "RECEIVED",
                }
            ],
        },
    }


def test_append_type_returns_empty() -> None:
    """History-sync messages (type=append) must be discarded."""
    adapter = WhatsAppAdapter()
    result = adapter.parse_inbound(_append_payload())
    assert result == [], "Expected no messages from append (history-sync) event"


def test_notify_type_is_parsed() -> None:
    """Real-time messages (type=notify) must be parsed normally."""
    adapter = WhatsAppAdapter()
    result = adapter.parse_inbound(_notify_payload())
    assert len(result) == 1
    assert result[0].text == "hello"
    assert result[0].external_msg_id == "msg_001"


def test_append_type_case_insensitive() -> None:
    """type=APPEND (uppercase) should also be filtered."""
    adapter = WhatsAppAdapter()
    payload = _append_payload()
    payload["data"]["type"] = "APPEND"
    result = adapter.parse_inbound(payload)
    assert result == []


def test_missing_type_field_still_parsed() -> None:
    """If data dict has no 'type' key, fall through to normal parsing."""
    adapter = WhatsAppAdapter()
    payload = _notify_payload()
    del payload["data"]["type"]
    result = adapter.parse_inbound(payload)
    assert len(result) == 1
    assert result[0].text == "hello"


def test_non_upsert_event_ignored() -> None:
    """Non-upsert events are still ignored regardless of type field."""
    adapter = WhatsAppAdapter()
    payload = {"event": "connection.update", "data": {"type": "notify", "messages": []}}
    result = adapter.parse_inbound(payload)
    assert result == []
