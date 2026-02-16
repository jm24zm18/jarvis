"""Provider construction helpers."""

from jarvis.config import Settings
from jarvis.providers.base import ModelProvider
from jarvis.providers.gemini import GeminiProvider
from jarvis.providers.google_gemini_cli import GoogleGeminiCliProvider


def build_primary_provider(settings: Settings) -> ModelProvider:
    provider = settings.gemini_provider.strip().lower()
    if provider in {"google-gemini-cli", "gemini-cli"}:
        return GoogleGeminiCliProvider(
            settings.gemini_model,
            binary=settings.gemini_cli_binary,
            home_dir=settings.gemini_cli_home_dir,
            timeout_seconds=settings.gemini_cli_timeout_seconds,
        )
    return GeminiProvider(settings.gemini_model)
