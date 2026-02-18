import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import create_thread, ensure_channel, insert_message, now_iso
from jarvis.main import app
from jarvis.routes import ws as ws_route

_MANAGED_CLIENTS: list[TestClient] = []


def _managed_client() -> TestClient:
    client = TestClient(app)
    client.__enter__()
    _MANAGED_CLIENTS.append(client)
    return client


@pytest.fixture(autouse=True)
def _cleanup_managed_clients():
    yield
    while _MANAGED_CLIENTS:
        _MANAGED_CLIENTS.pop().__exit__(None, None, None)


def test_websocket_subscribe_and_notification_delivery() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()

    login = client.post("/api/v1/auth/login", json={"password": "secret"})
    assert login.status_code == 200

    user_id = str(login.json()["user_id"])
    with get_conn() as conn:
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)
        message_id = insert_message(conn, thread_id, "assistant", "hello websocket")

    with client.websocket_connect("/ws") as ws:
        auth_event = ws.receive_json()
        assert auth_event["type"] == "auth.ok"

        ws.send_json({"action": "subscribe", "thread_id": thread_id})
        ack = ws.receive_json()
        assert ack["type"] == "subscribed"

        with get_conn() as conn:
            conn.execute(
                (
                    "INSERT INTO web_notifications("
                    "thread_id, event_type, payload_json, created_at"
                    ") VALUES(?,?,?,?)"
                ),
                (
                    thread_id,
                    "message.new",
                    json.dumps({"message_id": message_id}),
                    now_iso(),
                ),
            )
        asyncio.run(ws_route._poll_once())

        event = ws.receive_json()
        assert event["type"] == "message.new"
        assert event["thread_id"] == thread_id
        assert event["message"]["content"] == "hello websocket"


def test_admin_subscribe_system_receives_system_events() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()

    login = client.post(
        "/api/v1/auth/login",
        json={"password": "secret", "external_id": "bootstrap-admin"},
    )
    assert login.status_code == 200
    bootstrap_user_id = str(login.json()["user_id"])
    with get_conn() as conn:
        conn.execute("UPDATE users SET role='admin' WHERE id=?", (bootstrap_user_id,))
    login = client.post(
        "/api/v1/auth/login",
        json={"password": "secret", "external_id": "bootstrap-admin"},
    )
    assert login.status_code == 200
    assert login.json()["role"] == "admin"

    user_id = str(login.json()["user_id"])
    with get_conn() as conn:
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)
        conn.execute(
            (
                "INSERT INTO web_notifications("
                "thread_id, event_type, payload_json, created_at"
                ") VALUES(?,?,?,?)"
            ),
            (
                thread_id,
                "system.guardrail.trip",
                json.dumps({"detail": "trip"}),
                now_iso(),
            ),
        )

    with client.websocket_connect("/ws") as ws:
        auth_event = ws.receive_json()
        assert auth_event["type"] == "auth.ok"
        assert auth_event["role"] == "admin"
        ws.send_json({"action": "subscribe_system"})
        ack = ws.receive_json()
        assert ack["type"] == "subscribed.system"

        asyncio.run(ws_route._poll_once())
        event = ws.receive_json()
        assert event["type"] == "system.guardrail.trip"
        assert event["detail"] == "trip"


def test_websocket_rejects_query_token_auth() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=legacy-token"):
            pass
