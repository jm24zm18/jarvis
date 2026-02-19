import os

import pytest
from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import insert_message, now_iso
from jarvis.main import app

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


def _login(client: TestClient, external_id: str) -> tuple[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"password": "secret", "external_id": external_id},
    )
    assert response.status_code == 200
    payload = response.json()
    return str(payload["token"]), str(payload["user_id"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap_users(client: TestClient) -> tuple[dict[str, str], dict[str, str]]:
    _admin_token, _admin_user = _login(client, "bootstrap-admin")
    user_a_token, user_a_id = _login(client, "alice")
    user_b_token, user_b_id = _login(client, "bob")
    return (
        {"token": user_a_token, "user_id": user_a_id},
        {"token": user_b_token, "user_id": user_b_id},
    )


def _create_thread(client: TestClient, token: str) -> str:
    response = client.post("/api/v1/threads", headers=_headers(token))
    assert response.status_code == 200
    return str(response.json()["id"])


def test_user_cannot_read_other_users_thread() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, bob = _bootstrap_users(client)
    bob_thread = _create_thread(client, bob["token"])

    response = client.get(f"/api/v1/threads/{bob_thread}", headers=_headers(alice["token"]))
    assert response.status_code == 403


def test_user_cannot_list_other_users_threads() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, bob = _bootstrap_users(client)
    _ = _create_thread(client, bob["token"])

    response = client.get("/api/v1/threads", headers=_headers(alice["token"]))
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_user_cannot_send_message_to_other_users_thread() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, bob = _bootstrap_users(client)
    bob_thread = _create_thread(client, bob["token"])

    response = client.post(
        f"/api/v1/threads/{bob_thread}/messages",
        headers=_headers(alice["token"]),
        json={"content": "hi"},
    )
    assert response.status_code == 403


def test_user_cannot_patch_other_users_thread() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, bob = _bootstrap_users(client)
    bob_thread = _create_thread(client, bob["token"])

    response = client.patch(
        f"/api/v1/threads/{bob_thread}",
        headers=_headers(alice["token"]),
        json={"status": "closed"},
    )
    assert response.status_code == 403


def test_user_cannot_read_messages_from_other_users_thread() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, bob = _bootstrap_users(client)
    bob_thread = _create_thread(client, bob["token"])
    with get_conn() as conn:
        _ = insert_message(conn, bob_thread, "assistant", "private")

    response = client.get(
        f"/api/v1/threads/{bob_thread}/messages",
        headers=_headers(alice["token"]),
    )
    assert response.status_code == 403


def test_websocket_subscribe_to_other_users_thread_rejected() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, bob = _bootstrap_users(client)
    bob_thread = _create_thread(client, bob["token"])

    with client.websocket_connect(
        "/ws", headers={"Authorization": f"Bearer {alice['token']}"}
    ) as ws:
        auth_event = ws.receive_json()
        assert auth_event["type"] == "auth.ok"
        ws.send_json({"action": "subscribe", "thread_id": bob_thread})
        error = ws.receive_json()
        assert error["type"] == "error"
        assert error["detail"] == "forbidden"


def test_non_admin_websocket_subscribe_system_rejected() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, _bob = _bootstrap_users(client)

    with client.websocket_connect(
        "/ws", headers={"Authorization": f"Bearer {alice['token']}"}
    ) as ws:
        auth_event = ws.receive_json()
        assert auth_event["type"] == "auth.ok"
        assert auth_event["role"] == "user"
        ws.send_json({"action": "subscribe_system"})
        error = ws.receive_json()
        assert error["type"] == "error"
        assert error["detail"] == "forbidden"


def test_non_admin_cannot_toggle_lockdown() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, _bob = _bootstrap_users(client)

    response = client.post(
        "/api/v1/system/lockdown",
        headers=_headers(alice["token"]),
        json={"lockdown": True},
    )
    assert response.status_code == 403


def test_lockdown_route_is_reachable_after_successful_login() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()

    token, _user_id = _login(client, "alice")
    response = client.post(
        "/api/v1/system/lockdown",
        headers=_headers(token),
        json={"lockdown": True},
    )
    assert response.status_code == 403


def test_non_admin_cannot_modify_permissions() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, _bob = _bootstrap_users(client)

    response = client.put(
        "/api/v1/permissions/main/echo",
        headers=_headers(alice["token"]),
        json={},
    )
    assert response.status_code == 403


def test_non_admin_cannot_approve_selfupdate() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, _bob = _bootstrap_users(client)

    response = client.post(
        "/api/v1/selfupdate/patches/trc_demo/approve",
        headers=_headers(alice["token"]),
        json={},
    )
    assert response.status_code == 403


def test_non_admin_cannot_read_governance_fitness() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, _bob = _bootstrap_users(client)

    response = client.get(
        "/api/v1/governance/fitness/latest",
        headers=_headers(alice["token"]),
    )
    assert response.status_code == 403


def test_non_admin_cannot_read_governance_slo() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, _bob = _bootstrap_users(client)

    response = client.get(
        "/api/v1/governance/slo",
        headers=_headers(alice["token"]),
    )
    assert response.status_code == 403


def test_non_admin_cannot_read_governance_decision_timeline() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, _bob = _bootstrap_users(client)

    response = client.get(
        "/api/v1/governance/decision-timeline",
        headers=_headers(alice["token"]),
    )
    assert response.status_code == 403


def test_non_admin_cannot_submit_remediation_feedback() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, _bob = _bootstrap_users(client)

    response = client.post(
        "/api/v1/governance/remediations/frm_demo/feedback",
        headers=_headers(alice["token"]),
        json={"feedback": "accepted"},
    )
    assert response.status_code == 403


def test_non_admin_cannot_run_memory_maintenance() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, _bob = _bootstrap_users(client)

    response = client.post(
        "/api/v1/memory/maintenance/run",
        headers=_headers(alice["token"]),
        json={},
    )
    assert response.status_code == 403


def test_non_admin_cannot_manage_whatsapp_channels() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, _bob = _bootstrap_users(client)
    headers = _headers(alice["token"])

    assert client.get("/api/v1/channels/whatsapp/status", headers=headers).status_code == 403
    assert (
        client.post("/api/v1/channels/whatsapp/create", headers=headers, json={}).status_code
        == 403
    )
    assert client.get("/api/v1/channels/whatsapp/qrcode", headers=headers).status_code == 403
    assert (
        client.post(
            "/api/v1/channels/whatsapp/pairing-code",
            headers=headers,
            json={"number": "15555550123"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/channels/whatsapp/disconnect",
            headers=headers,
            json={},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/channels/whatsapp/review-queue", headers=headers).status_code == 403
    assert (
        client.post(
            "/api/v1/channels/whatsapp/review-queue/sch_demo/resolve",
            headers=headers,
            json={"decision": "deny", "reason": "blocked"},
        ).status_code
        == 403
    )


def test_user_memory_search_scoped() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, bob = _bootstrap_users(client)
    alice_thread = _create_thread(client, alice["token"])
    bob_thread = _create_thread(client, bob["token"])
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO memory_items(id, thread_id, text, metadata_json, created_at) "
                "VALUES(?,?,?,?,?)"
            ),
            ("mem_alice", alice_thread, "alice note", "{}", now_iso()),
        )
        conn.execute(
            (
                "INSERT INTO memory_items(id, thread_id, text, metadata_json, created_at) "
                "VALUES(?,?,?,?,?)"
            ),
            ("mem_bob", bob_thread, "bob note", "{}", now_iso()),
        )

    response = client.get("/api/v1/memory", headers=_headers(alice["token"]))
    assert response.status_code == 200
    items = response.json()["items"]
    thread_ids = {item["thread_id"] for item in items}
    assert alice_thread in thread_ids
    assert bob_thread not in thread_ids
    assert all(isinstance(item.get("metadata"), dict) for item in items)


def test_user_bugs_list_scoped() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    alice, bob = _bootstrap_users(client)

    create_alice = client.post(
        "/api/v1/bugs",
        headers=_headers(alice["token"]),
        json={"title": "alice bug", "description": "", "priority": "low"},
    )
    assert create_alice.status_code == 200
    create_bob = client.post(
        "/api/v1/bugs",
        headers=_headers(bob["token"]),
        json={"title": "bob bug", "description": "", "priority": "low"},
    )
    assert create_bob.status_code == 200

    listing = client.get("/api/v1/bugs", headers=_headers(alice["token"]))
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["reporter_id"] == alice["user_id"]
