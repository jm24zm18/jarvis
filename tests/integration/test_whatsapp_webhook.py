import os

import pytest
from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.main import app
from jarvis.tasks.agent import agent_step
from jarvis.tasks.channel import send_whatsapp_message

PAYLOAD = {
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "messages": [
                            {
                                "id": "wamid.TEST.1",
                                "from": "15555550123",
                                "text": {"body": "hello"},
                            }
                        ]
                    }
                }
            ]
        }
    ]
}


def test_verify_success() -> None:
    client = TestClient(app)
    response = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "test-token", "hub.challenge": "42"},
    )
    assert response.status_code == 200
    assert response.text == "42"


def test_inbound_accepted() -> None:
    client = TestClient(app)
    response = client.post("/webhooks/whatsapp", json=PAYLOAD)
    assert response.status_code in {200, 202}
    payload = response.json()
    assert payload["accepted"] is True
    assert isinstance(payload["degraded"], bool)


def test_inbound_degraded_when_broker_unavailable(monkeypatch) -> None:
    from jarvis.channels.whatsapp import router as whatsapp_router

    class _FailRunner:
        def send_task(self, *_args, **_kwargs) -> bool:
            raise RuntimeError("runner unavailable")

    monkeypatch.setattr(whatsapp_router, "get_task_runner", lambda: _FailRunner())

    client = TestClient(app)
    response = client.post("/webhooks/whatsapp", json=PAYLOAD)
    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["degraded"] is True


def test_webhook_to_outbound_flow_emits_events(monkeypatch) -> None:
    from jarvis.channels.whatsapp import router as whatsapp_router

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.TEST.E2E.1",
                                    "from": "15555550124",
                                    "text": {"body": "/status"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    enqueued: list[dict[str, object]] = []

    def fake_send_task(name: str, kwargs: dict[str, str], queue: str) -> bool:
        enqueued.append({"name": name, "kwargs": kwargs, "queue": queue})
        return True

    async def fake_send_text(_recipient: str, _text: str) -> int:
        return 200

    class _InboundRunner:
        def send_task(self, name: str, kwargs: dict[str, str], queue: str) -> bool:
            return fake_send_task(name, kwargs, queue)

    monkeypatch.setattr(whatsapp_router, "get_task_runner", lambda: _InboundRunner())

    class _Runner:
        def send_task(self, name: str, kwargs: dict[str, str], queue: str) -> bool:
            enqueued.append({"name": name, "kwargs": kwargs, "queue": queue})
            return True

    monkeypatch.setattr("jarvis.tasks.agent.get_task_runner", lambda: _Runner())

    from jarvis.channels.registry import get_channel

    adapter = get_channel("whatsapp")
    if adapter is not None:
        monkeypatch.setattr(adapter, "send_text", fake_send_text)

    client = TestClient(app)
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    assert response.json() == {"accepted": True, "degraded": False}

    agent_calls = [
        item
        for item in enqueued
        if item["name"] == "jarvis.tasks.agent.agent_step"
        and item["queue"] == "agent_priority"
    ]
    assert len(agent_calls) == 1
    call_kwargs = agent_calls[0]["kwargs"]
    assert isinstance(call_kwargs, dict)
    trace_id = str(call_kwargs["trace_id"])
    thread_id = str(call_kwargs["thread_id"])

    message_id = agent_step(trace_id=trace_id, thread_id=thread_id)
    assert message_id.startswith("msg_")

    outbound_calls = [
        item
        for item in enqueued
        if item["name"] in (
            "jarvis.tasks.channel.send_whatsapp_message",
            "jarvis.tasks.channel.send_channel_message",
        )
        and item["queue"] == "tools_io"
    ]
    assert len(outbound_calls) == 1
    outbound_kwargs = outbound_calls[0]["kwargs"]
    assert isinstance(outbound_kwargs, dict)
    assert outbound_kwargs["thread_id"] == thread_id
    assert outbound_kwargs["message_id"] == message_id

    outbound_result = send_whatsapp_message(thread_id=thread_id, message_id=message_id)
    assert outbound_result["status"] == "sent"

    with get_conn() as conn:
        outbound_events = conn.execute(
            (
                "SELECT event_type FROM events "
                "WHERE thread_id=? AND event_type='channel.outbound' "
                "ORDER BY created_at ASC"
            ),
            (thread_id,),
        ).fetchall()

    assert len(outbound_events) >= 2


def test_inbound_rejects_invalid_secret(monkeypatch) -> None:
    del monkeypatch
    os.environ["WHATSAPP_WEBHOOK_SECRET"] = "secret123"
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.post("/webhooks/whatsapp", json=PAYLOAD)
    assert response.status_code == 401
    assert response.json() == {"accepted": False, "error": "invalid_webhook_secret"}
    os.environ["WHATSAPP_WEBHOOK_SECRET"] = ""
    get_settings.cache_clear()


def test_inbound_accepts_evolution_payload(monkeypatch) -> None:
    from jarvis.channels.whatsapp import router as whatsapp_router

    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "id": "BAE5TESTEVO2",
                "remoteJid": "15555550199@s.whatsapp.net",
                "participant": "15555550199@s.whatsapp.net",
            },
            "message": {"conversation": "hello from evolution"},
        },
    }

    class _Runner:
        def send_task(self, *_args, **_kwargs) -> bool:
            return True

    monkeypatch.setattr(whatsapp_router, "get_task_runner", lambda: _Runner())
    client = TestClient(app)
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    assert response.json()["accepted"] is True


@pytest.mark.parametrize(
    ("message_payload", "expected_text_prefix"),
    [
        ({"extendedTextMessage": {"text": "hello extended"}}, "hello extended"),
        ({"imageMessage": {"caption": "look", "url": "https://cdn.example/image.jpg"}}, "[image]"),
        ({"videoMessage": {"caption": "vid", "url": "https://cdn.example/video.mp4"}}, "[video]"),
        (
            {"documentMessage": {"caption": "doc", "url": "https://cdn.example/doc.pdf"}},
            "[document]",
        ),
        ({"audioMessage": {"seconds": 4, "url": "https://cdn.example/audio.ogg"}}, "[audio]"),
        ({"stickerMessage": {"url": "https://cdn.example/sticker.webp"}}, "[sticker]"),
    ],
)
def test_inbound_accepts_evolution_message_variants(
    monkeypatch, message_payload: dict[str, object], expected_text_prefix: str
) -> None:
    from jarvis.channels.whatsapp import router as whatsapp_router

    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "id": f"BAE5VARIANT{expected_text_prefix[:3]}",
                "remoteJid": "15555550201@s.whatsapp.net",
                "participant": "15555550201@s.whatsapp.net",
            },
            "message": message_payload,
        },
    }

    class _Runner:
        def send_task(self, *_args, **_kwargs) -> bool:
            return True

    monkeypatch.setattr(whatsapp_router, "get_task_runner", lambda: _Runner())
    client = TestClient(app)
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    assert response.json()["accepted"] is True

    with get_conn() as conn:
        row = conn.execute(
            "SELECT content FROM messages WHERE role='user' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert str(row["content"]).startswith(expected_text_prefix)


def test_inbound_accepts_evolution_group_payload(monkeypatch) -> None:
    from jarvis.channels.whatsapp import router as whatsapp_router

    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "id": "BAE5GROUP1",
                "remoteJid": "120363000000000000@g.us",
                "participant": "15555550333@s.whatsapp.net",
            },
            "message": {"conversation": "group hello"},
        },
    }

    class _Runner:
        def send_task(self, *_args, **_kwargs) -> bool:
            return True

    monkeypatch.setattr(whatsapp_router, "get_task_runner", lambda: _Runner())
    client = TestClient(app)
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    assert response.json()["accepted"] is True

    with get_conn() as conn:
        event_row = conn.execute(
            "SELECT payload_redacted_json FROM events "
            "WHERE event_type='channel.inbound' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert event_row is not None
    assert "\"is_group\": true" in str(event_row["payload_redacted_json"]).lower()


def test_inbound_ignores_non_upsert_evolution_event() -> None:
    payload = {
        "event": "connection.update",
        "data": {"state": "open"},
    }
    with get_conn() as conn:
        before_messages = int(conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"])
        before_events = int(conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"])

    client = TestClient(app)
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    assert response.json() == {"accepted": True, "degraded": False, "ignored": True}

    with get_conn() as conn:
        after_messages = int(conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"])
        after_events = int(conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"])

    assert after_messages == before_messages
    assert after_events == before_events
