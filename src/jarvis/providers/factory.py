"""Provider construction helpers."""

from jarvis.config import Settings
from jarvis.providers.base import ModelProvider
from jarvis.providers.google_gemini_cli import GeminiCodeAssistProvider
from jarvis.providers.sglang import SGLangProvider

_ALLOWED_PRIMARY_PROVIDERS = {"gemini", "sglang"}


def resolve_primary_provider_name(settings: Settings) -> str:
    value = settings.primary_provider.strip().lower()
    if value in _ALLOWED_PRIMARY_PROVIDERS:
        return value
    return "gemini"


def build_primary_provider(settings: Settings) -> ModelProvider:
    primary = resolve_primary_provider_name(settings)
    if primary == "sglang":
        return SGLangProvider(settings.sglang_model)
    return GeminiCodeAssistProvider(
        model=settings.gemini_model,
        token_path=settings.gemini_code_assist_token_path,
        timeout_seconds=settings.gemini_cli_timeout_seconds,
        quota_plan_tier=settings.gemini_code_assist_plan_tier,
        requests_per_minute=settings.gemini_code_assist_requests_per_minute,
        requests_per_day=settings.gemini_code_assist_requests_per_day,
        quota_cooldown_default_seconds=settings.gemini_quota_cooldown_default_seconds,
    )


def build_fallback_provider(settings: Settings) -> ModelProvider:
    primary = resolve_primary_provider_name(settings)
    if primary == "sglang":
        return GeminiCodeAssistProvider(
            model=settings.gemini_model,
            token_path=settings.gemini_code_assist_token_path,
            timeout_seconds=settings.gemini_cli_timeout_seconds,
            quota_plan_tier=settings.gemini_code_assist_plan_tier,
            requests_per_minute=settings.gemini_code_assist_requests_per_minute,
            requests_per_day=settings.gemini_code_assist_requests_per_day,
            quota_cooldown_default_seconds=settings.gemini_quota_cooldown_default_seconds,
        )
    return SGLangProvider(settings.sglang_model)
