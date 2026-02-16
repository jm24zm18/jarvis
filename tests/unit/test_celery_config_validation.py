import pytest

from jarvis.celery_app import _validate_runtime_settings
from jarvis.config import get_settings


def test_celery_runtime_validation_fails_for_invalid_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("PAGERDUTY_ROUTING_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError):
            _validate_runtime_settings()
    finally:
        get_settings.cache_clear()
