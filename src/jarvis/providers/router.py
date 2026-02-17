"""Provider router with fallback behavior."""

import asyncio
import logging
import random
import re

from jarvis.errors import ProviderError
from jarvis.providers.base import ModelProvider, ModelResponse

logger = logging.getLogger(__name__)
_PRIMARY_RETRY_ATTEMPTS = 2
_BASE_RETRY_DELAY_SECONDS = 0.3
_MAX_RETRY_DELAY_SECONDS = 1.5


class ProviderRouter:
    def __init__(self, primary: ModelProvider, fallback: ModelProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    async def _local_llm_overloaded(self) -> bool:
        return False

    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        priority: str = "normal",
    ) -> tuple[ModelResponse, str, str | None]:
        last_exc: Exception | None = None
        primary_error = ""
        for attempt in range(_PRIMARY_RETRY_ATTEMPTS + 1):
            try:
                response = await self.primary.generate(messages, tools, temperature, max_tokens)
                return response, "primary", None
            except Exception as exc:
                last_exc = exc
                primary_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Primary provider failed: %s", primary_error)
                if (
                    attempt >= _PRIMARY_RETRY_ATTEMPTS
                    or not _is_retryable_primary_error(primary_error)
                ):
                    break
                delay_s = _compute_retry_delay_seconds(primary_error, attempt)
                await asyncio.sleep(delay_s)

        if priority == "low" and await self._local_llm_overloaded():
            raise ProviderError(primary_error, retryable=True) from last_exc
        try:
            response = await self.fallback.generate(messages, tools, temperature, max_tokens)
        except Exception as fallback_exc:
            raise ProviderError(
                f"all providers failed: primary={primary_error}, "
                f"fallback={type(fallback_exc).__name__}: {fallback_exc}",
                retryable=True,
            ) from fallback_exc
        return response, "fallback", primary_error

    async def health(self) -> dict[str, bool]:
        return {
            "primary": await self.primary.health_check(),
            "fallback": await self.fallback.health_check(),
        }


def _is_retryable_primary_error(primary_error: str) -> bool:
    text = primary_error.lower()
    retryable_markers = (
        "quota exceeded",
        "quota exhausted",
        "rate limit",
        "resource_exhausted",
        "timed out",
        "timeout",
        "temporarily exhausted",
        "429",
    )
    return any(marker in text for marker in retryable_markers)


def _compute_retry_delay_seconds(primary_error: str, attempt: int) -> float:
    text = primary_error.lower()
    hint = _parse_retry_after_seconds(text)
    if hint > 0:
        return float(min(_MAX_RETRY_DELAY_SECONDS, max(_BASE_RETRY_DELAY_SECONDS, hint)))
    base = min(_MAX_RETRY_DELAY_SECONDS, _BASE_RETRY_DELAY_SECONDS * (2 ** attempt))
    jitter = random.uniform(0.05, 0.25)
    return float(min(_MAX_RETRY_DELAY_SECONDS, base + jitter))


def _parse_retry_after_seconds(text: str) -> int:
    if match := re.search(r"retry(?:[-\s]*after| in)\s+(\d+(?:\.\d+)?)", text):
        return max(1, int(float(match.group(1))))
    return 0
