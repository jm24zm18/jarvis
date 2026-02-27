"""Provider construction helpers."""

from jarvis.config import Settings
from jarvis.providers.base import ModelProvider
from jarvis.providers.compat import ProviderCompat
from jarvis.providers.lmstudio import LMStudioProvider
from jarvis.providers.openrouter import OpenRouterProvider
from jarvis.providers.sglang import SGLangProvider

_ALLOWED_PRIMARY_PROVIDERS = {"openrouter", "sglang", "lmstudio"}


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


def _build_lmstudio_compat(settings: Settings) -> ProviderCompat:
    return ProviderCompat(
        tool_choice=settings.lmstudio_tool_choice or "auto",
        parallel_tool_calls=bool(settings.lmstudio_parallel_tool_calls),
    )


def resolve_fallback_provider_name(settings: Settings, primary: str) -> str:
    fallback = settings.fallback_provider.strip().lower()
    if fallback in _ALLOWED_PRIMARY_PROVIDERS and fallback != primary:
        return fallback
    if primary == "sglang":
        return "openrouter"
    if primary == "lmstudio":
        return "openrouter"
    return "sglang"


def _build_provider_by_name(settings: Settings, provider_name: str) -> ModelProvider:
    if provider_name == "sglang":
        return SGLangProvider(settings.sglang_model, compat=_build_sglang_compat(settings))
    if provider_name == "lmstudio":
        return LMStudioProvider(settings.lmstudio_model, compat=_build_lmstudio_compat(settings))
    return OpenRouterProvider(
        settings.openrouter_model, compat=_build_openrouter_compat(settings)
    )


def build_primary_provider(settings: Settings) -> ModelProvider:
    primary = resolve_primary_provider_name(settings)
    return _build_provider_by_name(settings, primary)


def build_fallback_provider(settings: Settings) -> ModelProvider:
    primary = resolve_primary_provider_name(settings)
    fallback = resolve_fallback_provider_name(settings, primary)
    return _build_provider_by_name(settings, fallback)
