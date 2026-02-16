import asyncio
import json
import os

from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import create_thread, ensure_channel, insert_message, now_iso
from jarvis.main import app
from jarvis.routes import ws as ws_route


def test_websocket_subscribe_and_notification_delivery() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)

    login = client.post("/api/v1/auth/login", json={"password": "secret"})
    assert login.status_code == 200
    token = str(login.json()["token"])

    user_id = str(login.json()["user_id"])
    with get_conn() as conn:
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)
        message_id = insert_message(conn, thread_id, "assistant", "hello websocket")

    with client.websocket_connect(f"/ws?token={token}") as ws:
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
