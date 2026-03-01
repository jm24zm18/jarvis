import os

from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.main import app


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "secret"})
    assert response.status_code == 200
    return str(response.json()["token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_unauthenticated_requests_are_rejected() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)

    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/threads").status_code == 401
    assert client.get("/api/v1/selfupdate/patches").status_code == 401


def test_authenticated_session_can_access_control_plane_routes() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)
    token = _login(client)
    headers = _headers(token)

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert client.get("/api/v1/threads", headers=headers).status_code == 200
    assert client.get("/api/v1/selfupdate/patches", headers=headers).status_code == 200
    assert client.get("/api/v1/governance/fitness/latest", headers=headers).status_code == 200


def test_authenticated_websocket_can_subscribe_system() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)
    token = _login(client)

    with client.websocket_connect("/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
        auth_event = ws.receive_json()
        assert auth_event["type"] == "auth.ok"
        assert "user_id" in auth_event
        ws.send_json({"action": "subscribe_system"})
        ack = ws.receive_json()
        assert ack["type"] == "subscribed.system"
