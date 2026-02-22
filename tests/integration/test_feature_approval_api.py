"""Integration tests for feature request approval and build-run API."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import create_feature_build_run
from jarvis.main import app

_MANAGED_CLIENTS: list[TestClient] = []


def _managed_client() -> TestClient:
    client = TestClient(app)
    client.__enter__()
    _MANAGED_CLIENTS.append(client)
    return client


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    while _MANAGED_CLIENTS:
        _MANAGED_CLIENTS.pop().__exit__(None, None, None)


def _login(client: TestClient, external_id: str) -> str:
    r = client.post("/api/v1/auth/login", json={"password": "secret", "external_id": external_id})
    assert r.status_code == 200
    return str(r.json()["token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _setup(client: TestClient) -> tuple[str, str]:
    """Return (admin_token, user_token) after bootstrapping."""
    admin_token = _login(client, "bootstrap-admin")
    user_token = _login(client, "alice")
    return admin_token, user_token


def _create_feature(client: TestClient, admin_token: str, title: str = "My feature") -> str:
    r = client.post(
        "/api/v1/feature-requests",
        headers=_headers(admin_token),
        json={"title": title, "description": "desc", "priority": "medium"},
    )
    assert r.status_code == 200
    return str(r.json()["id"])


# ---------------------------------------------------------------------------
# Feature approval endpoint tests
# ---------------------------------------------------------------------------

def test_admin_can_approve_feature() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, _ = _setup(client)

    feature_id = _create_feature(client, admin_token)

    r = client.patch(
        f"/api/v1/feature-requests/{feature_id}/approval",
        headers=_headers(admin_token),
        json={"decision": "approved", "note": "Looks good"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["approval_status"] == "approved"

    # Verify reflected in list endpoint.
    r2 = client.get(
        "/api/v1/feature-requests?approval_status=approved",
        headers=_headers(admin_token),
    )
    assert r2.status_code == 200
    ids = [item["id"] for item in r2.json()["items"]]
    assert feature_id in ids


def test_admin_can_reject_feature() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, _ = _setup(client)

    feature_id = _create_feature(client, admin_token)

    r = client.patch(
        f"/api/v1/feature-requests/{feature_id}/approval",
        headers=_headers(admin_token),
        json={"decision": "rejected"},
    )
    assert r.status_code == 200
    assert r.json()["approval_status"] == "rejected"


def test_non_admin_cannot_set_feature_approval() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, user_token = _setup(client)

    feature_id = _create_feature(client, admin_token)

    r = client.patch(
        f"/api/v1/feature-requests/{feature_id}/approval",
        headers=_headers(user_token),
        json={"decision": "approved"},
    )
    assert r.status_code == 403


def test_invalid_decision_returns_400() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, _ = _setup(client)

    feature_id = _create_feature(client, admin_token)

    r = client.patch(
        f"/api/v1/feature-requests/{feature_id}/approval",
        headers=_headers(admin_token),
        json={"decision": "maybe"},
    )
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Feature build-run endpoint tests
# ---------------------------------------------------------------------------

def test_build_rejected_without_approval_returns_409() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, _ = _setup(client)

    feature_id = _create_feature(client, admin_token)
    # Not approved yet.
    r = client.post(
        f"/api/v1/feature-requests/{feature_id}/build",
        headers=_headers(admin_token),
    )
    assert r.status_code == 409


def test_approved_feature_can_trigger_build() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, _ = _setup(client)

    feature_id = _create_feature(client, admin_token)

    # Approve first.
    client.patch(
        f"/api/v1/feature-requests/{feature_id}/approval",
        headers=_headers(admin_token),
        json={"decision": "approved"},
    )

    # Trigger build (may fail to enqueue task in test env, that's OK).
    r = client.post(
        f"/api/v1/feature-requests/{feature_id}/build",
        headers=_headers(admin_token),
    )
    assert r.status_code == 200
    data = r.json()
    assert "run_id" in data
    assert "trace_id" in data


def test_non_admin_cannot_trigger_build() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, user_token = _setup(client)

    feature_id = _create_feature(client, admin_token)
    client.patch(
        f"/api/v1/feature-requests/{feature_id}/approval",
        headers=_headers(admin_token),
        json={"decision": "approved"},
    )

    r = client.post(
        f"/api/v1/feature-requests/{feature_id}/build",
        headers=_headers(user_token),
    )
    assert r.status_code == 403


def test_list_feature_build_runs_admin_only() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, user_token = _setup(client)

    feature_id = _create_feature(client, admin_token)

    r_admin = client.get(
        f"/api/v1/feature-requests/{feature_id}/build-runs",
        headers=_headers(admin_token),
    )
    assert r_admin.status_code == 200
    assert "items" in r_admin.json()

    r_user = client.get(
        f"/api/v1/feature-requests/{feature_id}/build-runs",
        headers=_headers(user_token),
    )
    assert r_user.status_code == 403


def test_build_runs_payload_includes_thread_id_and_updated_at() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, _ = _setup(client)

    feature_id = _create_feature(client, admin_token)
    with get_conn() as conn:
        run_id = create_feature_build_run(conn, feature_id=feature_id, created_by="usr_admin")
        conn.execute(
            "UPDATE feature_request_build_runs SET thread_id=?, status='running' WHERE id=?",
            ("thr_contract_build_1", run_id),
        )

    r = client.get(
        f"/api/v1/feature-requests/{feature_id}/build-runs",
        headers=_headers(admin_token),
    )
    assert r.status_code == 200
    items = r.json()["items"]
    target = next(item for item in items if item["id"] == run_id)
    assert "thread_id" in target
    assert "updated_at" in target
    assert target["thread_id"] == "thr_contract_build_1"


def test_admin_can_reconcile_stale_feature_build_runs() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, _ = _setup(client)
    feature_id = _create_feature(client, admin_token)

    with get_conn() as conn:
        run_id = create_feature_build_run(conn, feature_id=feature_id, created_by="usr_admin")
        stale_stamp = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
        conn.execute(
            "UPDATE feature_request_build_runs SET status='running', updated_at=? WHERE id=?",
            (stale_stamp, run_id),
        )

    reconcile = client.post(
        "/api/v1/feature-requests/build-runs/reconcile?stale_after_seconds=60&limit=50",
        headers=_headers(admin_token),
    )
    assert reconcile.status_code == 200
    body = reconcile.json()
    assert body["reconciled"] >= 1
    assert run_id in body["ids"]

    runs = client.get(
        f"/api/v1/feature-requests/{feature_id}/build-runs",
        headers=_headers(admin_token),
    )
    assert runs.status_code == 200
    run_map = {item["id"]: item for item in runs.json()["items"]}
    assert run_map[run_id]["status"] == "failed"


def test_non_admin_cannot_reconcile_stale_feature_build_runs() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    _, user_token = _setup(client)

    r = client.post(
        "/api/v1/feature-requests/build-runs/reconcile",
        headers=_headers(user_token),
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Approvals center endpoint tests
# ---------------------------------------------------------------------------

def test_admin_can_list_approvals() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, _ = _setup(client)

    r = client.get("/api/v1/approvals", headers=_headers(admin_token))
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "allowed_actions" in data


def test_non_admin_cannot_list_approvals() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    _, user_token = _setup(client)

    r = client.get("/api/v1/approvals", headers=_headers(user_token))
    assert r.status_code == 403


def test_admin_can_create_and_revoke_approval() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, _ = _setup(client)

    # Create.
    r = client.post(
        "/api/v1/approvals",
        headers=_headers(admin_token),
        json={"action": "selfupdate.apply", "target_ref": "trc_test_1", "ttl_minutes": 10},
    )
    assert r.status_code == 200
    approval_id = r.json()["approval_id"]

    # Verify in list.
    r2 = client.get("/api/v1/approvals?status=approved", headers=_headers(admin_token))
    ids = [a["id"] for a in r2.json()["items"]]
    assert approval_id in ids

    # Revoke.
    r3 = client.post(
        f"/api/v1/approvals/{approval_id}/revoke",
        headers=_headers(admin_token),
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "revoked"


def test_invalid_action_returns_400() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = _managed_client()
    admin_token, _ = _setup(client)

    r = client.post(
        "/api/v1/approvals",
        headers=_headers(admin_token),
        json={"action": "not.an.allowed.action"},
    )
    assert r.status_code == 400
