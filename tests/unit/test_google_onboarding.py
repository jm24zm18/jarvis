from urllib.parse import parse_qs, urlparse

import pytest

from jarvis.auth import google_onboarding
from jarvis.auth.google_onboarding import create_google_flow
from jarvis.config import get_settings


def test_create_google_flow_uses_openclaw_compatible_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    get_settings.cache_clear()
    try:
        flow = create_google_flow(redirect_uri="http://localhost:8000/api/v1/auth/google/callback")
    finally:
        get_settings.cache_clear()

    query = parse_qs(urlparse(flow["auth_url"]).query)
    scopes = set(query["scope"][0].split(" "))

    assert "https://www.googleapis.com/auth/cloud-platform" in scopes
    assert "https://www.googleapis.com/auth/userinfo.email" in scopes
    assert "https://www.googleapis.com/auth/userinfo.profile" in scopes
    assert "https://www.googleapis.com/auth/generative-language" not in scopes


def test_create_google_flow_requires_client_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setattr(
        google_onboarding,
        "_extract_gemini_cli_credentials",
        lambda: None,
    )
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="missing Google OAuth client secret"):
            create_google_flow(redirect_uri="http://localhost:8000/api/v1/auth/google/callback")
    finally:
        get_settings.cache_clear()


def test_create_google_flow_backfills_client_secret_from_gemini_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_id = "client.apps.googleusercontent.com"
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", client_id)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setattr(
        google_onboarding,
        "_extract_gemini_cli_credentials",
        lambda: (client_id, "cli-secret"),
    )
    get_settings.cache_clear()
    try:
        flow = create_google_flow(redirect_uri="http://localhost:8000/api/v1/auth/google/callback")
    finally:
        get_settings.cache_clear()

    state = flow["state"]
    assert google_onboarding._flows[state].client_secret == "cli-secret"


def test_create_google_flow_prefers_matching_gemini_cli_secret_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_id = "client.apps.googleusercontent.com"
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", client_id)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "stale-secret")
    monkeypatch.setattr(
        google_onboarding,
        "_extract_gemini_cli_credentials",
        lambda: (client_id, "cli-secret"),
    )
    get_settings.cache_clear()
    try:
        flow = create_google_flow(redirect_uri="http://localhost:8000/api/v1/auth/google/callback")
    finally:
        get_settings.cache_clear()

    state = flow["state"]
    assert google_onboarding._flows[state].client_secret == "cli-secret"


@pytest.mark.asyncio
async def test_complete_google_flow_writes_code_assist_token_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GEMINI_CODE_ASSIST_TOKEN_PATH", str(tmp_path / "token.json"))
    get_settings.cache_clear()

    class _DummyResponse:
        status_code = 200
        text = ""
        reason_phrase = "OK"

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
            }

    class _DummyClient:
        async def __aenter__(self) -> "_DummyClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb

        async def post(self, *_args, **_kwargs) -> _DummyResponse:  # type: ignore[no-untyped-def]
            return _DummyResponse()

    monkeypatch.setattr(google_onboarding.httpx, "AsyncClient", lambda timeout: _DummyClient())

    async def _fake_bootstrap(**_kwargs) -> dict[str, object]:
        return {
            "cloudaicompanionProject": "cap-proj",
            "currentTier": {"id": "tier-id", "name": "Tier Name"},
        }

    captured_env: dict[str, str] = {}
    monkeypatch.setattr(google_onboarding, "_load_code_assist_bootstrap", _fake_bootstrap)
    monkeypatch.setattr(
        google_onboarding,
        "_save_env_values",
        lambda values: captured_env.update(values),
    )

    flow = create_google_flow(redirect_uri="http://localhost:8000/api/v1/auth/google/callback")
    await google_onboarding.complete_google_flow(state=flow["state"], code="oauth-code")

    token_payload = (tmp_path / "token.json").read_text()
    assert "cap-proj" in token_payload
    assert "refresh-token" in token_payload
    assert captured_env["GOOGLE_OAUTH_CLIENT_ID"] == "client.apps.googleusercontent.com"
    get_settings.cache_clear()
