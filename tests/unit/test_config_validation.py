import os

import pytest

from jarvis.config import get_settings, validate_settings_for_env


def _base_prod_env() -> dict[str, str]:
    return {
        "APP_ENV": "prod",
        "APP_DB": "/srv/agent-framework/app.db",
        "BROKER_URL": "amqp://guest:guest@localhost:5672//",
        "RESULT_BACKEND": "rpc://",
        "WHATSAPP_VERIFY_TOKEN": "prod-verify-token",
        "WHATSAPP_ACCESS_TOKEN": "prod-access-token",
        "WHATSAPP_PHONE_NUMBER_ID": "1234567890",
        "GOOGLE_OAUTH_CLIENT_ID": "cid",
        "GOOGLE_OAUTH_CLIENT_SECRET": "csecret",
        "GOOGLE_OAUTH_REFRESH_TOKEN": "refresh",
        "GEMINI_MODEL": "gemini-2.5-pro",
        "SGLANG_BASE_URL": "http://localhost:30000/v1",
        "SGLANG_MODEL": "openai/gpt-oss-120b",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text",
        "SEARXNG_BASE_URL": "http://localhost:8080",
        "ADMIN_WHATSAPP_IDS": "15555550123",
        "RABBITMQ_MGMT_URL": "http://localhost:15672",
        "RABBITMQ_MGMT_USER": "guest",
        "RABBITMQ_MGMT_PASSWORD": "guest",
        "BACKUP_S3_ENDPOINT": "https://example-r2.endpoint",
        "BACKUP_S3_BUCKET": "jarvis-prod-backups",
        "BACKUP_S3_REGION": "auto",
        "BACKUP_S3_ACCESS_KEY_ID": "access",
        "BACKUP_S3_SECRET_ACCESS_KEY": "secret",
        "PAGERDUTY_ROUTING_KEY": "routing-key",
    }


def test_validate_settings_prod_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(_base_prod_env()):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "prod")

    get_settings.cache_clear()
    try:
        settings = get_settings()
        with pytest.raises(ValueError):
            validate_settings_for_env(settings)
    finally:
        get_settings.cache_clear()


def test_validate_settings_prod_accepts_full_required_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in list(_base_prod_env()):
        monkeypatch.setenv(key, _base_prod_env()[key])

    get_settings.cache_clear()
    try:
        settings = get_settings()
        validate_settings_for_env(settings)
    finally:
        get_settings.cache_clear()


def test_validate_settings_dev_skips_strict_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "dev-verify-token")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "dev-token")

    get_settings.cache_clear()
    try:
        settings = get_settings()
        validate_settings_for_env(settings)
    finally:
        get_settings.cache_clear()
    assert os.environ.get("APP_ENV") == "dev"


def test_validate_settings_prod_requires_github_secrets_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in list(_base_prod_env()):
        monkeypatch.setenv(key, _base_prod_env()[key])
    monkeypatch.setenv("GITHUB_PR_SUMMARY_ENABLED", "1")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    get_settings.cache_clear()
    try:
        settings = get_settings()
        with pytest.raises(ValueError):
            validate_settings_for_env(settings)
    finally:
        get_settings.cache_clear()
