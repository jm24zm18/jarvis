import os

import pytest
from fastapi.testclient import TestClient

from jarvis.channels.whatsapp.media_security import MediaSecurityError
from jarvis.channels.whatsapp.transcription import VoiceTranscriptionError
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


def test_inbound_strict_mode_queues_unknown_sender_without_message_insert() -> None:
    old_review_mode = os.environ.get("WHATSAPP_REVIEW_MODE")
    old_allowed_senders = os.environ.get("WHATSAPP_ALLOWED_SENDERS")
    old_admin_ids = os.environ.get("ADMIN_WHATSAPP_IDS")
    try:
        os.environ["WHATSAPP_REVIEW_MODE"] = "strict"
        os.environ["WHATSAPP_ALLOWED_SENDERS"] = ""
        os.environ["ADMIN_WHATSAPP_IDS"] = ""
        get_settings.cache_clear()
        client = TestClient(app)
        payload_one = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "wamid.TEST.REVIEW.1",
                                        "from": "15555559001",
                                        "text": {"body": "hello"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        payload_two = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "wamid.TEST.REVIEW.2",
                                        "from": "15555559001",
                                        "text": {"body": "hello again"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        with get_conn() as conn:
            before = int(conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"])
        first = client.post("/webhooks/whatsapp", json=payload_one)
        second = client.post("/webhooks/whatsapp", json=payload_two)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["queued_for_review"] is True
        assert second.json()["queued_for_review"] is True
        with get_conn() as conn:
            after = int(conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"])
            open_rows = conn.execute(
                "SELECT COUNT(*) AS c FROM whatsapp_sender_review_queue "
                "WHERE instance='personal' AND sender_jid='15555559001' AND status='open'"
            ).fetchone()
        assert after == before
        assert open_rows is not None and int(open_rows["c"]) == 1
    finally:
        if old_review_mode is None:
            os.environ.pop("WHATSAPP_REVIEW_MODE", None)
        else:
            os.environ["WHATSAPP_REVIEW_MODE"] = old_review_mode
        if old_allowed_senders is None:
            os.environ.pop("WHATSAPP_ALLOWED_SENDERS", None)
        else:
            os.environ["WHATSAPP_ALLOWED_SENDERS"] = old_allowed_senders
        if old_admin_ids is None:
            os.environ.pop("ADMIN_WHATSAPP_IDS", None)
        else:
            os.environ["ADMIN_WHATSAPP_IDS"] = old_admin_ids
        get_settings.cache_clear()


def test_inbound_strict_mode_blocks_sender_after_denied_review() -> None:
    old_review_mode = os.environ.get("WHATSAPP_REVIEW_MODE")
    old_allowed_senders = os.environ.get("WHATSAPP_ALLOWED_SENDERS")
    old_admin_ids = os.environ.get("ADMIN_WHATSAPP_IDS")
    try:
        os.environ["WHATSAPP_REVIEW_MODE"] = "strict"
        os.environ["WHATSAPP_ALLOWED_SENDERS"] = ""
        os.environ["ADMIN_WHATSAPP_IDS"] = ""
        get_settings.cache_clear()
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "wamid.TEST.REVIEW.DENY.1",
                                        "from": "15555559002",
                                        "text": {"body": "blocked"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        with get_conn() as conn:
            before = int(conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"])
            conn.execute(
                (
                    "INSERT OR REPLACE INTO whatsapp_sender_review_queue("
                    "id, instance, sender_jid, remote_jid, participant_jid, "
                    "thread_id, external_msg_id, "
                    "reason, status, reviewer_id, resolution_note, created_at, updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
                ),
                (
                    "sch_review_denied_seed",
                    "personal",
                    "15555559002",
                    "15555559002",
                    "",
                    "",
                    "seed",
                    "unknown_sender",
                    "denied",
                    "usr_admin",
                    "blocked",
                    "2026-02-19T00:00:00+00:00",
                    "2026-02-19T00:00:00+00:00",
                ),
            )
        client = TestClient(app)
        response = client.post("/webhooks/whatsapp", json=payload)
        assert response.status_code == 200
        assert response.json()["accepted"] is True
        assert response.json()["blocked_sender"] is True
        with get_conn() as conn:
            after = int(conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"])
        assert after == before
    finally:
        if old_review_mode is None:
            os.environ.pop("WHATSAPP_REVIEW_MODE", None)
        else:
            os.environ["WHATSAPP_REVIEW_MODE"] = old_review_mode
        if old_allowed_senders is None:
            os.environ.pop("WHATSAPP_ALLOWED_SENDERS", None)
        else:
            os.environ["WHATSAPP_ALLOWED_SENDERS"] = old_allowed_senders
        if old_admin_ids is None:
            os.environ.pop("ADMIN_WHATSAPP_IDS", None)
        else:
            os.environ["ADMIN_WHATSAPP_IDS"] = old_admin_ids
        get_settings.cache_clear()


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
        ({"audioMessage": {"seconds": 4, "url": "https://cdn.example/audio.ogg"}}, "[voice]"),
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

    async def _fake_download_media_file(**kwargs) -> int:  # type: ignore[no-untyped-def]
        target_path = kwargs["target_path"]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"media")
        return 5

    monkeypatch.setattr(whatsapp_router, "get_task_runner", lambda: _Runner())
    monkeypatch.setattr(whatsapp_router, "download_media_file", _fake_download_media_file)
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


def test_inbound_batch_event_redacts_qr_and_pairing_fields_in_stored_logs(monkeypatch) -> None:
    from jarvis.channels.whatsapp import router as whatsapp_router

    payload = {
        "event": "messages.upsert",
        "qrcode": "data:image/png;base64,SECRET_QR",
        "pairing_code": "654321",
        "data": {
            "key": {
                "id": "BAE5REDACT1",
                "remoteJid": "15555550666@s.whatsapp.net",
                "participant": "15555550666@s.whatsapp.net",
            },
            "message": {"conversation": "hello"},
        },
    }

    class _Runner:
        def send_task(self, *_args, **_kwargs) -> bool:
            return True

    monkeypatch.setattr(whatsapp_router, "get_task_runner", lambda: _Runner())
    client = TestClient(app)
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200

    with get_conn() as conn:
        row = conn.execute(
            "SELECT payload_json, payload_redacted_json FROM events "
            "WHERE event_type='channel.inbound.batch' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    raw_payload = str(row["payload_json"])
    redacted_payload = str(row["payload_redacted_json"])
    assert "SECRET_QR" in raw_payload
    assert "654321" in raw_payload
    assert "SECRET_QR" not in redacted_payload
    assert "654321" not in redacted_payload
    assert "[REDACTED]" in redacted_payload


def test_inbound_blocks_oversized_media_with_degraded_marker(monkeypatch) -> None:
    from jarvis.channels.whatsapp import router as whatsapp_router

    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "id": "BAE5OVERSIZE1",
                "remoteJid": "15555550777@s.whatsapp.net",
                "participant": "15555550777@s.whatsapp.net",
            },
            "message": {
                "imageMessage": {
                    "caption": "too big",
                    "url": "https://cdn.example/huge.png",
                    "mimetype": "image/png",
                }
            },
        },
    }

    class _Runner:
        def send_task(self, *_args, **_kwargs) -> bool:
            return True

    async def _oversized_download(**_kwargs) -> int:  # type: ignore[no-untyped-def]
        raise MediaSecurityError("media_size_exceeded")

    monkeypatch.setattr(whatsapp_router, "get_task_runner", lambda: _Runner())
    monkeypatch.setattr(whatsapp_router, "download_media_file", _oversized_download)
    client = TestClient(app)
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 202
    assert response.json() == {"accepted": True, "degraded": True}

    with get_conn() as conn:
        row = conn.execute(
            "SELECT content FROM messages WHERE role='user' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        degraded = conn.execute(
            "SELECT payload_json FROM events WHERE event_type='channel.inbound.degraded' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert str(row["content"]) == "[media blocked]"
    assert degraded is not None
    assert "media_size_exceeded" in str(degraded["payload_json"])


def test_inbound_voice_note_transcription_failure_uses_marker(monkeypatch) -> None:
    from jarvis.channels.whatsapp import router as whatsapp_router

    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "id": "BAE5VOICEFAIL1",
                "remoteJid": "15555550888@s.whatsapp.net",
                "participant": "15555550888@s.whatsapp.net",
            },
            "message": {
                "audioMessage": {
                    "seconds": 4,
                    "url": "https://cdn.example/fail-audio.ogg",
                    "mimetype": "audio/ogg; codecs=opus",
                }
            },
        },
    }

    class _Runner:
        def send_task(self, *_args, **_kwargs) -> bool:
            return True

    async def _fake_download_media_file(**kwargs) -> int:  # type: ignore[no-untyped-def]
        target_path = kwargs["target_path"]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"audio")
        return 5

    async def _transcribe_fail(**_kwargs) -> str:  # type: ignore[no-untyped-def]
        raise VoiceTranscriptionError("voice_transcription_failed")

    monkeypatch.setattr(whatsapp_router, "get_task_runner", lambda: _Runner())
    monkeypatch.setattr(whatsapp_router, "download_media_file", _fake_download_media_file)
    monkeypatch.setattr(whatsapp_router, "transcribe_with_timeout", _transcribe_fail)
    client = TestClient(app)
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 202
    assert response.json() == {"accepted": True, "degraded": True}

    with get_conn() as conn:
        row = conn.execute(
            "SELECT content FROM messages WHERE role='user' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        degraded = conn.execute(
            "SELECT payload_json FROM events WHERE event_type='channel.inbound.degraded' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert str(row["content"]) == "[voice note unavailable]"
    assert degraded is not None
    assert "voice_transcription_failed" in str(degraded["payload_json"])


def test_inbound_voice_note_uses_faster_whisper_backend(monkeypatch) -> None:
    from jarvis.channels.whatsapp import router as whatsapp_router

    old_backend = os.environ.get("WHATSAPP_VOICE_TRANSCRIBE_BACKEND")
    try:
        os.environ["WHATSAPP_VOICE_TRANSCRIBE_BACKEND"] = "faster_whisper"
        get_settings.cache_clear()

        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "id": "BAE5VOICEFW1",
                    "remoteJid": "15555550899@s.whatsapp.net",
                    "participant": "15555550899@s.whatsapp.net",
                },
                "message": {
                    "audioMessage": {
                        "seconds": 6,
                        "url": "https://cdn.example/fw-audio.ogg",
                        "mimetype": "audio/ogg; codecs=opus",
                    }
                },
            },
        }

        class _Runner:
            def send_task(self, *_args, **_kwargs) -> bool:
                return True

        async def _fake_download_media_file(**kwargs) -> int:  # type: ignore[no-untyped-def]
            target_path = kwargs["target_path"]
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"audio")
            return 5

        class _Transcriber:
            async def transcribe(self, **_kwargs) -> str:  # type: ignore[no-untyped-def]
                return "transcribed from local model"

        monkeypatch.setattr(whatsapp_router, "get_task_runner", lambda: _Runner())
        monkeypatch.setattr(whatsapp_router, "download_media_file", _fake_download_media_file)
        monkeypatch.setattr(
            whatsapp_router,
            "build_voice_transcriber",
            lambda _settings: _Transcriber(),
        )
        client = TestClient(app)
        response = client.post("/webhooks/whatsapp", json=payload)
        assert response.status_code == 200
        assert response.json() == {"accepted": True, "degraded": False}

        with get_conn() as conn:
            row = conn.execute(
                "SELECT content FROM messages WHERE role='user' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        assert row is not None
        assert str(row["content"]).startswith("[voice] transcribed from local model")
    finally:
        if old_backend is None:
            os.environ.pop("WHATSAPP_VOICE_TRANSCRIBE_BACKEND", None)
        else:
            os.environ["WHATSAPP_VOICE_TRANSCRIBE_BACKEND"] = old_backend
        get_settings.cache_clear()


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
