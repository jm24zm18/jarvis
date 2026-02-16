import hashlib
import hmac
import json
import os

from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError

from jarvis.config import get_settings
from jarvis.main import app


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "secret"})
    assert response.status_code == 200
    payload = response.json()
    assert "token" in payload
    return str(payload["token"])


def test_web_auth_login_me_logout_flow() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)

    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["user_id"].startswith("usr_")

    logout = client.post("/api/v1/auth/logout", headers=headers)
    assert logout.status_code == 200
    assert logout.json() == {"ok": True}

    me_after = client.get("/api/v1/auth/me", headers=headers)
    assert me_after.status_code == 401


def test_web_thread_and_message_flow(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    calls: list[tuple[str, str]] = []

    def fake_send_task(name: str, kwargs: dict[str, str], queue: str) -> None:
        calls.append((name, queue))

    monkeypatch.setattr("jarvis.routes.api.messages.celery_app.send_task", fake_send_task)
    monkeypatch.setattr("jarvis.routes.api.messages.is_onboarding_active", lambda *_a, **_k: False)

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    thread = client.post("/api/v1/threads", headers=headers)
    assert thread.status_code == 200
    thread_id = thread.json()["id"]

    send = client.post(
        f"/api/v1/threads/{thread_id}/messages",
        headers=headers,
        json={"content": "hello from web"},
    )
    assert send.status_code == 200
    assert send.json()["ok"] is True

    listing = client.get(f"/api/v1/threads/{thread_id}/messages", headers=headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["role"] == "user"
    assert items[0]["speaker"] == "user"
    assert items[0]["content"] == "hello from web"

    queue_names = {item[1] for item in calls}
    assert "agent_priority" in queue_names
    assert "tools_io" in queue_names
    task_names = [item[0] for item in calls]
    assert "jarvis.tasks.agent.agent_step" in task_names
    assert "jarvis.tasks.onboarding.onboarding_step" not in task_names


def test_web_message_routes_to_onboarding_when_requested(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    calls: list[tuple[str, str]] = []

    def fake_send_task(name: str, kwargs: dict[str, str], queue: str) -> None:
        calls.append((name, queue))

    monkeypatch.setattr("jarvis.routes.api.messages.celery_app.send_task", fake_send_task)
    monkeypatch.setattr("jarvis.routes.api.messages.is_onboarding_active", lambda *_a, **_k: True)

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    thread = client.post("/api/v1/threads", headers=headers)
    assert thread.status_code == 200
    thread_id = thread.json()["id"]

    send = client.post(
        f"/api/v1/threads/{thread_id}/messages",
        headers=headers,
        json={"content": "hello from web"},
    )
    assert send.status_code == 200
    assert send.json()["ok"] is True
    assert send.json()["onboarding"] is True

    listing = client.get(f"/api/v1/threads/{thread_id}/messages", headers=headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["role"] == "user"
    task_names = [item[0] for item in calls]
    assert "jarvis.tasks.memory.index_event" in task_names
    assert "jarvis.tasks.onboarding.onboarding_step" in task_names
    assert "jarvis.tasks.agent.agent_step" not in task_names


def test_web_message_onboarding_enqueue_failure_still_persists_user_message(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    calls: list[tuple[str, str]] = []

    def fake_send_task(name: str, kwargs: dict[str, str], queue: str) -> None:
        calls.append((name, queue))
        if name == "jarvis.tasks.onboarding.onboarding_step":
            raise OperationalError("queue unavailable")

    monkeypatch.setattr("jarvis.routes.api.messages.celery_app.send_task", fake_send_task)
    monkeypatch.setattr("jarvis.routes.api.messages.is_onboarding_active", lambda *_a, **_k: True)

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    thread = client.post("/api/v1/threads", headers=headers)
    assert thread.status_code == 200
    thread_id = thread.json()["id"]

    send = client.post(
        f"/api/v1/threads/{thread_id}/messages",
        headers=headers,
        json={"content": "hello from web"},
    )
    assert send.status_code == 200
    assert send.json()["ok"] is True
    assert send.json()["onboarding"] is True
    assert send.json()["degraded"] is True

    listing = client.get(f"/api/v1/threads/{thread_id}/messages", headers=headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["role"] == "user"
    assert items[0]["content"] == "hello from web"
    task_names = [item[0] for item in calls]
    assert "jarvis.tasks.memory.index_event" in task_names
    assert "jarvis.tasks.onboarding.onboarding_step" in task_names


def test_get_thread_onboarding_status() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    thread = client.post("/api/v1/threads", headers=headers)
    assert thread.status_code == 200
    thread_id = thread.json()["id"]

    status = client.get(f"/api/v1/threads/{thread_id}/onboarding", headers=headers)
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] in {"required", "in_progress", "completed", "not_required"}
    assert "required" in payload


def test_start_thread_onboarding_inserts_assistant_prompt(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    async def _fake_start_onboarding_prompt(**_: object) -> str:
        return "Before we start, what should I call your assistant?"

    monkeypatch.setattr(
        "jarvis.routes.api.messages.start_onboarding_prompt",
        _fake_start_onboarding_prompt,
    )
    monkeypatch.setattr("jarvis.routes.api.messages.get_assistant_name", lambda: "Jarvis")

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    thread = client.post("/api/v1/threads", headers=headers)
    assert thread.status_code == 200
    thread_id = thread.json()["id"]

    start = client.post(f"/api/v1/threads/{thread_id}/onboarding/start", headers=headers)
    assert start.status_code == 200
    assert start.json()["ok"] is True
    assert start.json()["prompted"] is True
    assert start.json()["message_id"] is not None

    listing = client.get(f"/api/v1/threads/{thread_id}/messages", headers=headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["role"] == "assistant"
    assert items[0]["speaker"] == "Jarvis"
    assert items[0]["content"] == "Before we start, what should I call your assistant?"

    start_again = client.post(f"/api/v1/threads/{thread_id}/onboarding/start", headers=headers)
    assert start_again.status_code == 200
    assert start_again.json()["ok"] is True
    assert start_again.json()["prompted"] is False


def test_github_webhook_rejects_bad_signature() -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "shh"
    get_settings.cache_clear()
    client = TestClient(app)
    payload = {"action": "opened"}
    response = client.post(
        "/api/v1/webhooks/github",
        json=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=bad",
        },
    )
    assert response.status_code == 401


def test_github_webhook_enqueues_summary_task(monkeypatch) -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "secret"
    get_settings.cache_clear()
    calls: list[tuple[str, dict[str, object], str]] = []

    def fake_send_task(name: str, kwargs: dict[str, object], queue: str) -> None:
        calls.append((name, kwargs, queue))

    monkeypatch.setattr("jarvis.routes.api.webhooks.celery_app.send_task", fake_send_task)

    client = TestClient(app)
    payload = {
        "action": "opened",
        "repository": {"name": "jarvis", "owner": {"login": "justin"}},
        "pull_request": {"number": 12, "base": {"ref": "dev"}},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert calls
    assert calls[0][0] == "jarvis.tasks.github.github_pr_summary"
    assert calls[0][2] == "tools_io"
    assert calls[0][1]["owner"] == "justin"
    assert calls[0][1]["repo"] == "jarvis"
    assert calls[0][1]["pull_number"] == 12


def test_github_webhook_degraded_on_enqueue_error(monkeypatch) -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "secret"
    get_settings.cache_clear()

    def fake_send_task(name: str, kwargs: dict[str, object], queue: str) -> None:
        raise OperationalError("broker down")

    monkeypatch.setattr("jarvis.routes.api.webhooks.celery_app.send_task", fake_send_task)

    client = TestClient(app)
    payload = {
        "action": "opened",
        "repository": {"name": "jarvis", "owner": {"login": "justin"}},
        "pull_request": {"number": 7, "base": {"ref": "dev"}},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["degraded"] is True


def test_github_issue_comment_chat_trigger_enqueues_task(monkeypatch) -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "secret"
    os.environ["GITHUB_BOT_LOGIN"] = "jarvis"
    get_settings.cache_clear()
    calls: list[tuple[str, dict[str, object], str]] = []

    def fake_send_task(name: str, kwargs: dict[str, object], queue: str) -> None:
        calls.append((name, kwargs, queue))

    monkeypatch.setattr("jarvis.routes.api.webhooks.celery_app.send_task", fake_send_task)
    client = TestClient(app)
    payload = {
        "action": "created",
        "repository": {"name": "jarvis", "owner": {"login": "justin"}},
        "issue": {"number": 44, "pull_request": {"url": "https://api.github.com/repos/x/y/pulls/44"}},
        "comment": {
            "body": "/jarvis review this diff",
            "user": {"login": "alice"},
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert calls
    assert calls[0][0] == "jarvis.tasks.github.github_pr_chat"
    assert calls[0][2] == "tools_io"
    assert calls[0][1]["pull_number"] == 44
    assert calls[0][1]["commenter_login"] == "alice"
    assert calls[0][1]["chat_mode"] == "review"
    assert calls[0][1]["comment_body"] == "this diff"


def test_github_issue_comment_mention_uses_chat_mode(monkeypatch) -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "secret"
    os.environ["GITHUB_BOT_LOGIN"] = "jarvis"
    get_settings.cache_clear()
    calls: list[tuple[str, dict[str, object], str]] = []

    def fake_send_task(name: str, kwargs: dict[str, object], queue: str) -> None:
        calls.append((name, kwargs, queue))

    monkeypatch.setattr("jarvis.routes.api.webhooks.celery_app.send_task", fake_send_task)
    client = TestClient(app)
    payload = {
        "action": "created",
        "repository": {"name": "jarvis", "owner": {"login": "justin"}},
        "issue": {"number": 47, "pull_request": {"url": "https://api.github.com/repos/x/y/pulls/47"}},
        "comment": {
            "body": "@jarvis can you summarize this?",
            "user": {"login": "alice"},
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert calls
    assert calls[0][1]["chat_mode"] == "chat"


def test_github_issue_comment_help_enqueues_help_mode(monkeypatch) -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "secret"
    os.environ["GITHUB_BOT_LOGIN"] = "jarvis"
    get_settings.cache_clear()
    calls: list[tuple[str, dict[str, object], str]] = []

    def fake_send_task(name: str, kwargs: dict[str, object], queue: str) -> None:
        calls.append((name, kwargs, queue))

    monkeypatch.setattr("jarvis.routes.api.webhooks.celery_app.send_task", fake_send_task)
    client = TestClient(app)
    payload = {
        "action": "created",
        "repository": {"name": "jarvis", "owner": {"login": "justin"}},
        "issue": {"number": 48, "pull_request": {"url": "https://api.github.com/repos/x/y/pulls/48"}},
        "comment": {
            "body": "/jarvis help",
            "user": {"login": "alice"},
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert calls
    assert calls[0][1]["chat_mode"] == "help"


def test_github_issue_comment_without_trigger_is_ignored() -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "secret"
    os.environ["GITHUB_BOT_LOGIN"] = "jarvis"
    get_settings.cache_clear()
    client = TestClient(app)
    payload = {
        "action": "created",
        "repository": {"name": "jarvis", "owner": {"login": "justin"}},
        "issue": {"number": 45, "pull_request": {"url": "https://api.github.com/repos/x/y/pulls/45"}},
        "comment": {
            "body": "looks good",
            "user": {"login": "alice"},
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["ignored"] is True
