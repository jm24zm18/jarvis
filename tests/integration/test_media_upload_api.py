"""Integration tests for media upload/download API surfaces."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.main import app
from jarvis.media.service import MediaService

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


def _login(client: TestClient, external_id: str) -> dict[str, str]:
    del external_id
    response = client.post(
        "/api/v1/auth/login",
        json={"password": "secret"},
    )
    assert response.status_code == 200
    payload = response.json()
    return {"token": str(payload["token"]), "user_id": str(payload["user_id"])}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_media_upload_and_download_round_trip(tmp_path: Path) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    os.environ["MEDIA_STORAGE_DIR"] = str(tmp_path / "media")
    get_settings.cache_clear()
    client = _managed_client()
    alice = _login(client, "alice-media")

    upload = client.post(
        "/api/v1/media/upload",
        headers=_headers(alice["token"]),
        files={"file": ("hello.txt", b"hello media", "text/plain")},
    )
    assert upload.status_code == 200
    payload = upload.json()
    assert payload["attachment_id"].startswith("mda_")
    assert payload["mime_type"] == "text/plain"
    assert payload["size_bytes"] == len(b"hello media")

    download = client.get(payload["url"], headers=_headers(alice["token"]))
    assert download.status_code == 200
    assert download.content == b"hello media"
    assert "text/plain" in str(download.headers.get("content-type", ""))


def test_media_download_is_available_to_authenticated_session(tmp_path: Path) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    os.environ["MEDIA_STORAGE_DIR"] = str(tmp_path / "media")
    get_settings.cache_clear()
    client = _managed_client()
    alice = _login(client, "alice-media-own")
    bob = _login(client, "bob-media-own")

    upload = client.post(
        "/api/v1/media/upload",
        headers=_headers(alice["token"]),
        files={"file": ("private.txt", b"alice secret", "text/plain")},
    )
    assert upload.status_code == 200
    url = str(upload.json()["url"])

    allowed = client.get(url, headers=_headers(bob["token"]))
    assert allowed.status_code == 200


def test_messages_list_includes_media_array(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    os.environ["MEDIA_STORAGE_DIR"] = str(tmp_path / "media")
    get_settings.cache_clear()
    monkeypatch.setattr("jarvis.routes.api.messages._send_task", lambda *_a, **_k: True)
    monkeypatch.setattr("jarvis.routes.api.messages.is_onboarding_active", lambda *_a, **_k: False)
    client = _managed_client()
    alice = _login(client, "alice-media-thread")

    thread = client.post("/api/v1/threads", headers=_headers(alice["token"]))
    assert thread.status_code == 200
    thread_id = str(thread.json()["id"])

    send = client.post(
        f"/api/v1/threads/{thread_id}/messages",
        headers=_headers(alice["token"]),
        json={"content": "message with attachment"},
    )
    assert send.status_code == 200
    message_id = str(send.json()["message_id"])

    with get_conn() as conn:
        attachment_id = MediaService().upload(
            conn,
            owner_id=alice["user_id"],
            file_data=b"attached by integration test",
            filename="attached.txt",
            mime_type="text/plain",
            message_id=message_id,
        )

    listing = client.get(f"/api/v1/threads/{thread_id}/messages", headers=_headers(alice["token"]))
    assert listing.status_code == 200
    items = listing.json()["items"]
    msg = next((item for item in items if item["id"] == message_id), None)
    assert msg is not None
    media = msg["media"]
    assert isinstance(media, list)
    assert len(media) == 1
    assert media[0]["id"] == attachment_id
    assert media[0]["mime_type"] == "text/plain"
    assert media[0]["url"] == f"/api/v1/media/{attachment_id}"
