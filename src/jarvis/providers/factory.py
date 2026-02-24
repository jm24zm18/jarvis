"""Provider construction helpers."""

from jarvis.config import Settings
from jarvis.providers.base import ModelProvider
from jarvis.providers.compat import ProviderCompat
from jarvis.providers.openrouter import OpenRouterProvider
from jarvis.providers.sglang import SGLangProvider

_ALLOWED_PRIMARY_PROVIDERS = {"openrouter", "sglang"}


def resolve_primary_provider_name(settings: Settings) -> str:
    value = settings.primary_provider.strip().lower()
    if value in _ALLOWED_PRIMARY_PROVIDERS:
        return value
    return "openrouter"


def _build_openrouter_compat(settings: Settings) -> ProviderCompat:
    return ProviderCompat(
        tool_choice=settings.openrouter_tool_choice or "auto",
        parallel_tool_calls=bool(settings.openrouter_parallel_tool_calls),
    )


def _build_sglang_compat(settings: Settings) -> ProviderCompat:
    return ProviderCompat(
        tool_choice=settings.sglang_tool_choice or "auto",
        parallel_tool_calls=bool(settings.sglang_parallel_tool_calls),
    )


def build_primary_provider(settings: Settings) -> ModelProvider:
    primary = resolve_primary_provider_name(settings)
    if primary == "sglang":
        return SGLangProvider(settings.sglang_model, compat=_build_sglang_compat(settings))
    return OpenRouterProvider(
        settings.openrouter_model, compat=_build_openrouter_compat(settings)
    )


def build_fallback_provider(settings: Settings) -> ModelProvider:
    primary = resolve_primary_provider_name(settings)
    if primary == "sglang":
        return OpenRouterProvider(
            settings.openrouter_model, compat=_build_openrouter_compat(settings)
        )
    return SGLangProvider(settings.sglang_model, compat=_build_sglang_compat(settings))
