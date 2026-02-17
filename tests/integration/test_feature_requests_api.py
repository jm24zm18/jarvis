import os

from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.main import app


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "secret"})
    assert response.status_code == 200
    payload = response.json()
    return str(payload["token"])


def test_create_feature_request_and_list(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/api/v1/feature-requests",
        headers=headers,
        json={
            "title": "Add dark mode",
            "description": "please",
            "priority": "medium",
        },
    )
    assert create.status_code == 200
    assert create.json()["kind"] == "feature"

    listing = client.get("/api/v1/feature-requests", headers=headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert any(item["kind"] == "feature" and item["title"] == "Add dark mode" for item in items)


def test_create_bug_with_github_sync_enqueues_task(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    calls: list[tuple[str, str]] = []

    def fake_send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
        _ = kwargs
        calls.append((name, queue))
        return True

    monkeypatch.setattr("jarvis.routes.api.bugs._send_task", fake_send_task)

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    create = client.post(
        "/api/v1/bugs",
        headers=headers,
        json={
            "title": "Sync bug",
            "description": "x",
            "priority": "high",
            "kind": "bug",
            "sync_to_github": True,
        },
    )
    assert create.status_code == 200
    payload = create.json()
    assert payload["github_sync_queued"] is True
    assert ("jarvis.tasks.github.github_issue_sync_bug_report", "tools_io") in calls
