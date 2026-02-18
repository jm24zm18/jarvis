import hashlib
import hmac
import json
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import insert_message, now_iso
from jarvis.ids import new_id
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


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "secret"})
    assert response.status_code == 200
    payload = response.json()
    assert "token" in payload
    return str(payload["token"])


def _login_payload(client: TestClient, external_id: str = "web_admin") -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/login",
        json={"password": "secret", "external_id": external_id},
    )
    assert response.status_code == 200
    return dict(response.json())


def test_web_auth_login_me_logout_flow() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()

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


def test_provider_config_get_and_update(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    os.environ["PRIMARY_PROVIDER"] = "gemini"
    os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"
    os.environ["SGLANG_MODEL"] = "openai/gpt-oss-120b"
    get_settings.cache_clear()
    saved: dict[str, str] = {}

    def fake_save_env_values(values: dict[str, str]) -> None:
        saved.update(values)
        for key, value in values.items():
            os.environ[key] = value

    monkeypatch.setattr("jarvis.routes.api.auth._save_env_values", fake_save_env_values)
    monkeypatch.setattr("jarvis.routes.api.auth.enqueue_settings_reload", lambda: True)

    client = _managed_client()
    first_login = _login_payload(client, "bootstrap-admin")
    bootstrap_user_id = str(first_login["user_id"])
    with get_conn() as conn:
        conn.execute("UPDATE users SET role='admin' WHERE id=?", (bootstrap_user_id,))

    admin_login = _login_payload(client, "bootstrap-admin")
    assert admin_login["role"] == "admin"
    headers = {"Authorization": f"Bearer {admin_login['token']}"}

    before = client.get("/api/v1/auth/providers/config", headers=headers)
    assert before.status_code == 200
    assert before.json()["primary_provider"] == "gemini"

    update = client.post(
        "/api/v1/auth/providers/config",
        headers=headers,
        json={
            "primary_provider": "sglang",
            "gemini_model": "gemini-2.5-pro",
            "sglang_model": "openai/gpt-oss-20b",
        },
    )
    assert update.status_code == 200
    payload = update.json()
    assert payload["ok"] is True
    assert payload["primary_provider"] == "sglang"
    assert payload["gemini_model"] == "gemini-2.5-pro"
    assert payload["sglang_model"] == "openai/gpt-oss-20b"
    assert saved["PRIMARY_PROVIDER"] == "sglang"
    assert saved["GEMINI_MODEL"] == "gemini-2.5-pro"
    assert saved["SGLANG_MODEL"] == "openai/gpt-oss-20b"
    get_settings.cache_clear()


def test_provider_config_requires_admin() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()

    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/v1/auth/providers/config", headers=headers)
    assert response.status_code == 403


def test_login_rejects_oversized_external_id() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()

    response = client.post(
        "/api/v1/auth/login",
        json={"password": "secret", "external_id": "x" * 257},
    )
    assert response.status_code == 422
    assert "external_id" in str(response.json().get("detail", "")).lower()


def test_login_accepts_max_sized_external_id() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()

    response = client.post(
        "/api/v1/auth/login",
        json={"password": "secret", "external_id": "x" * 256},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"].startswith("usr_")


def test_users_external_id_db_guard_rejects_oversized_value() -> None:
    with get_conn() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO users(id, external_id, created_at) VALUES(?,?,?)",
                (new_id("usr"), "x" * 257, now_iso()),
            )


def test_web_thread_and_message_flow(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    calls: list[tuple[str, str]] = []

    def fake_send_task(name: str, kwargs: dict[str, str], queue: str) -> bool:
        calls.append((name, queue))
        return True

    monkeypatch.setattr("jarvis.routes.api.messages._send_task", fake_send_task)
    monkeypatch.setattr("jarvis.routes.api.messages.is_onboarding_active", lambda *_a, **_k: False)

    client = _managed_client()
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

    def fake_send_task(name: str, kwargs: dict[str, str], queue: str) -> bool:
        calls.append((name, queue))
        return True

    monkeypatch.setattr("jarvis.routes.api.messages._send_task", fake_send_task)
    monkeypatch.setattr("jarvis.routes.api.messages.is_onboarding_active", lambda *_a, **_k: True)

    client = _managed_client()
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

    def fake_send_task(name: str, kwargs: dict[str, str], queue: str) -> bool:
        calls.append((name, queue))
        if name == "jarvis.tasks.onboarding.onboarding_step":
            return False
        return True

    monkeypatch.setattr("jarvis.routes.api.messages._send_task", fake_send_task)
    monkeypatch.setattr("jarvis.routes.api.messages.is_onboarding_active", lambda *_a, **_k: True)

    client = _managed_client()
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


def test_web_messages_hide_non_main_assistant_history() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    client = _managed_client()
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    thread = client.post("/api/v1/threads", headers=headers)
    assert thread.status_code == 200
    thread_id = thread.json()["id"]

    with get_conn() as conn:
        main_msg_id = insert_message(conn, thread_id, "assistant", "main response")
        planner_msg_id = insert_message(conn, thread_id, "assistant", "planner internal response")
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                new_id("evt"),
                new_id("trc"),
                new_id("spn"),
                None,
                thread_id,
                "agent.step.end",
                "orchestrator",
                "agent",
                "main",
                json.dumps({"message_id": main_msg_id}),
                json.dumps({"message_id": main_msg_id}),
                now_iso(),
            ),
        )
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                new_id("evt"),
                new_id("trc"),
                new_id("spn"),
                None,
                thread_id,
                "agent.step.end",
                "orchestrator",
                "agent",
                "planner",
                json.dumps({"message_id": planner_msg_id}),
                json.dumps({"message_id": planner_msg_id}),
                now_iso(),
            ),
        )

    listing = client.get(f"/api/v1/threads/{thread_id}/messages", headers=headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    contents = [str(item["content"]) for item in items]
    assert "main response" in contents
    assert "planner internal response" not in contents


def test_trace_endpoint_supports_redacted_and_raw_views() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    client = _managed_client()
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    thread = client.post("/api/v1/threads", headers=headers)
    assert thread.status_code == 200
    thread_id = thread.json()["id"]
    trace_id = new_id("trc")

    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                new_id("evt"),
                trace_id,
                new_id("spn"),
                None,
                thread_id,
                "agent.thought",
                "orchestrator",
                "agent",
                "main",
                json.dumps({"text": "private chain", "password": "secret"}),
                json.dumps({"text": "private chain", "password": "[REDACTED]"}),
                now_iso(),
            ),
        )

    redacted = client.get(f"/api/v1/traces/{trace_id}?view=redacted", headers=headers)
    assert redacted.status_code == 200
    redacted_items = redacted.json()["items"]
    assert redacted_items
    assert redacted_items[0]["payload"]["password"] == "[REDACTED]"

    raw = client.get(f"/api/v1/traces/{trace_id}?view=raw", headers=headers)
    assert raw.status_code == 200
    raw_items = raw.json()["items"]
    assert raw_items
    assert raw_items[0]["payload"]["password"] == "secret"


def test_get_thread_onboarding_status() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    client = _managed_client()
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

    client = _managed_client()
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
    client = _managed_client()
    payload = {"action": "opened"}
    response = client.post(
        "/api/v1/webhooks/github",
        json=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-bad-signature",
            "X-Hub-Signature-256": "sha256=bad",
        },
    )
    assert response.status_code == 401


def test_github_webhook_requires_delivery_id() -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    payload = {
        "action": "opened",
        "repository": {"name": "jarvis", "owner": {"login": "justin"}},
        "pull_request": {"number": 13, "base": {"ref": "dev"}},
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
    assert response.status_code == 400
    assert response.json()["detail"] == "missing github delivery id"


def test_github_webhook_rejects_replayed_delivery() -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    payload = {
        "action": "opened",
        "repository": {"name": "jarvis", "owner": {"login": "justin"}},
        "pull_request": {"number": 14, "base": {"ref": "dev"}},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "delivery-replay",
        "X-Hub-Signature-256": f"sha256={sig}",
    }
    first = client.post("/api/v1/webhooks/github", content=body, headers=headers)
    second = client.post("/api/v1/webhooks/github", content=body, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "replay detected"


def test_github_webhook_accepts_distinct_delivery_ids() -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    payload = {
        "action": "opened",
        "repository": {"name": "jarvis", "owner": {"login": "justin"}},
        "pull_request": {"number": 15, "base": {"ref": "dev"}},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    response_a = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-unique-a",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )
    response_b = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-unique-b",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )
    assert response_a.status_code == 200
    assert response_b.status_code == 200


def test_github_webhook_enqueues_summary_task(monkeypatch) -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "secret"
    get_settings.cache_clear()
    calls: list[tuple[str, dict[str, object], str]] = []

    def fake_send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
        calls.append((name, kwargs, queue))
        return True

    monkeypatch.setattr("jarvis.routes.api.webhooks._send_task", fake_send_task)

    client = _managed_client()
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
            "X-GitHub-Delivery": "delivery-enqueue-summary",
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

    def fake_send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
        return False

    monkeypatch.setattr("jarvis.routes.api.webhooks._send_task", fake_send_task)

    client = _managed_client()
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
            "X-GitHub-Delivery": "delivery-degraded-summary",
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

    def fake_send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
        calls.append((name, kwargs, queue))
        return True

    monkeypatch.setattr("jarvis.routes.api.webhooks._send_task", fake_send_task)
    client = _managed_client()
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
            "X-GitHub-Delivery": "delivery-issue-comment-review",
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

    def fake_send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
        calls.append((name, kwargs, queue))
        return True

    monkeypatch.setattr("jarvis.routes.api.webhooks._send_task", fake_send_task)
    client = _managed_client()
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
            "X-GitHub-Delivery": "delivery-issue-comment-chat",
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

    def fake_send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
        calls.append((name, kwargs, queue))
        return True

    monkeypatch.setattr("jarvis.routes.api.webhooks._send_task", fake_send_task)
    client = _managed_client()
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
            "X-GitHub-Delivery": "delivery-issue-comment-help",
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
    client = _managed_client()
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
            "X-GitHub-Delivery": "delivery-issue-comment-ignored",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["ignored"] is True


def test_evolution_items_require_admin() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    listing = client.get("/api/v1/governance/evolution/items", headers=headers)
    assert listing.status_code == 403
    update = client.post(
        "/api/v1/governance/evolution/items/evo_1/status",
        headers=headers,
        json={
            "status": "started",
            "trace_id": "trc_evo_1",
            "evidence_refs": ["docs/PLAN.md:1"],
            "result": {"status": "in_progress"},
        },
    )
    assert update.status_code == 403


def test_evolution_items_status_flow_and_timeline() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()

    first_login = _login_payload(client, "evo-admin")
    with get_conn() as conn:
        conn.execute("UPDATE users SET role='admin' WHERE id=?", (str(first_login["user_id"]),))
    admin = _login_payload(client, "evo-admin")
    headers = {"Authorization": f"Bearer {admin['token']}"}

    start = client.post(
        "/api/v1/governance/evolution/items/evo_item_1/status",
        headers=headers,
        json={
            "status": "started",
            "trace_id": "trc_evo_item_1",
            "thread_id": "",
            "evidence_refs": ["docs/PLAN.md:150"],
            "result": {"status": "started"},
        },
    )
    assert start.status_code == 200
    assert start.json()["ok"] is True
    assert start.json()["transition"]["to_status"] == "started"

    verify = client.post(
        "/api/v1/governance/evolution/items/evo_item_1/status",
        headers=headers,
        json={
            "status": "verified",
            "trace_id": "trc_evo_item_1",
            "thread_id": "",
            "evidence_refs": ["tests/integration/test_web_api.py:900"],
            "result": {"status": "ok"},
        },
    )
    assert verify.status_code == 200
    verify_payload = verify.json()
    assert verify_payload["ok"] is True
    assert verify_payload["item"]["status"] == "verified"

    listing = client.get(
        "/api/v1/governance/evolution/items?status=verified&trace_id=trc_evo_item_1",
        headers=headers,
    )
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert items
    assert items[0]["id"] == "evo_item_1"
    assert items[0]["status"] == "verified"

    timeline = client.get(
        "/api/v1/governance/decision-timeline?trace_id=trc_evo_item_1",
        headers=headers,
    )
    assert timeline.status_code == 200
    event_types = [str(item["event_type"]) for item in timeline.json()["items"]]
    assert "evolution.item.started" in event_types
    assert "evolution.item.verified" in event_types

    with get_conn() as conn:
        row = conn.execute(
            (
                "SELECT payload_json FROM events WHERE trace_id=? "
                "AND event_type='evolution.item.verified' ORDER BY created_at DESC LIMIT 1"
            ),
            ("trc_evo_item_1",),
        ).fetchone()
    assert row is not None
    payload = json.loads(str(row["payload_json"]))
    assert "item_id" in payload
    assert "trace_id" in payload
    assert "status" in payload
    assert "evidence_refs" in payload
    assert "result" in payload


def test_evolution_items_reject_invalid_transition() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()

    first_login = _login_payload(client, "evo-admin-2")
    with get_conn() as conn:
        conn.execute("UPDATE users SET role='admin' WHERE id=?", (str(first_login["user_id"]),))
    admin = _login_payload(client, "evo-admin-2")
    headers = {"Authorization": f"Bearer {admin['token']}"}

    started = client.post(
        "/api/v1/governance/evolution/items/evo_item_2/status",
        headers=headers,
        json={
            "status": "started",
            "trace_id": "trc_evo_item_2",
            "evidence_refs": [],
            "result": {"status": "started"},
        },
    )
    assert started.status_code == 200
    verified = client.post(
        "/api/v1/governance/evolution/items/evo_item_2/status",
        headers=headers,
        json={
            "status": "verified",
            "trace_id": "trc_evo_item_2",
            "evidence_refs": [],
            "result": {"status": "ok"},
        },
    )
    assert verified.status_code == 200

    blocked_after_verified = client.post(
        "/api/v1/governance/evolution/items/evo_item_2/status",
        headers=headers,
        json={
            "status": "blocked",
            "trace_id": "trc_evo_item_2",
            "evidence_refs": ["tests/integration/test_web_api.py:972"],
            "result": {"status": "should_fail"},
        },
    )
    assert blocked_after_verified.status_code == 200
    payload = blocked_after_verified.json()
    assert payload["ok"] is False
    assert payload["error"] == "invalid_transition"
