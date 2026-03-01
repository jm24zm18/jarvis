import os

import pytest
from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.main import app


def _login(client: TestClient, external_id: str) -> str:
    del external_id
    response = client.post(
        "/api/v1/auth/login",
        json={"password": "secret"},
    )
    assert response.status_code == 200
    payload = response.json()
    return str(payload["token"])

@pytest.fixture
def auth_tokens():
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)
    admin_token = _login(client, "admin-user")
    user_token = _login(client, "test-user")
    return {"admin": admin_token, "user": user_token}

@pytest.fixture
def admin_auth_headers(auth_tokens):
    return {"Authorization": f"Bearer {auth_tokens['admin']}"}

@pytest.fixture
def user_auth_headers(auth_tokens):
    return {"Authorization": f"Bearer {auth_tokens['user']}"}

def test_repo_api_admin_access(admin_auth_headers):
    client = TestClient(app)
    resp = client.get("/api/v1/repo/status", headers=admin_auth_headers)
    assert resp.status_code == 200
    assert "branch" in resp.json()
    assert "is_clean" in resp.json()

def test_repo_api_authenticated_access(user_auth_headers):
    client = TestClient(app)
    get_endpoints = [
        ("GET", "/api/v1/repo/status"),
        ("GET", "/api/v1/repo/log"),
        ("GET", "/api/v1/repo/branches"),
        ("GET", "/api/v1/repo/diff"),
    ]
    for method, path in get_endpoints:
        resp = client.request(method, path, headers=user_auth_headers)
        assert resp.status_code == 200
    post_endpoints = [
        ("POST", "/api/v1/repo/checkout"),
        ("POST", "/api/v1/repo/stage"),
        ("POST", "/api/v1/repo/unstage"),
        ("POST", "/api/v1/repo/commit"),
        ("POST", "/api/v1/repo/push"),
    ]
    for method, path in post_endpoints:
        resp = client.request(method, path, headers=user_auth_headers)
        assert resp.status_code in (200, 400, 409, 422)

def test_repo_stage_invalid_payload(admin_auth_headers):
    client = TestClient(app)
    resp = client.post("/api/v1/repo/stage", json={}, headers=admin_auth_headers)
    assert resp.status_code == 400

def test_repo_commit_empty_message(admin_auth_headers):
    client = TestClient(app)
    resp = client.post(
        "/api/v1/repo/commit", json={"message": "   "}, headers=admin_auth_headers
    )
    assert resp.status_code == 400

def test_repo_checkout_invalid_branch(admin_auth_headers):
    client = TestClient(app)
    resp = client.post(
        "/api/v1/repo/checkout", json={"branch": "-foo"}, headers=admin_auth_headers
    )
    assert resp.status_code == 400
    
    resp = client.post(
        "/api/v1/repo/checkout", json={"branch": "foo; rm -rf /"}, headers=admin_auth_headers
    )
    assert resp.status_code == 400
