"""Provider router with fallback behavior."""

import logging
import time

import httpx

from jarvis.config import get_settings
from jarvis.errors import ProviderError
from jarvis.providers.base import ModelProvider, ModelResponse

logger = logging.getLogger(__name__)


class ProviderRouter:
    _local_llm_overloaded_cache: tuple[float, bool] = (0.0, False)

    def __init__(self, primary: ModelProvider, fallback: ModelProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    async def _local_llm_overloaded(self) -> bool:
        settings = get_settings()
        threshold = settings.queue_threshold_local_llm
        if threshold <= 0:
            return False
        now = time.monotonic()
        cached_until, cached_value = self._local_llm_overloaded_cache
        if now < cached_until:
            return cached_value

        base = settings.rabbitmq_mgmt_url.strip().rstrip("/")
        if not base:
            self._local_llm_overloaded_cache = (now + 5.0, False)
            return False
        auth: tuple[str, str] | None = None
        if settings.rabbitmq_mgmt_user and settings.rabbitmq_mgmt_password:
            auth = (settings.rabbitmq_mgmt_user, settings.rabbitmq_mgmt_password)
        overloaded = False
        try:
            async with httpx.AsyncClient(timeout=3.0, auth=auth) as client:
                response = await client.get(f"{base}/api/queues")
                response.raise_for_status()
                payload = response.json()
            if isinstance(payload, list):
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    if item.get("name") != "local_llm":
                        continue
                    ready = item.get("messages_ready", 0)
                    unacked = item.get("messages_unacknowledged", 0)
                    total = int(ready) + int(unacked)
                    overloaded = total > threshold
                    break
        except Exception as exc:
            logger.warning("RabbitMQ management API queue check failed: %s", exc)
            overloaded = False
        self._local_llm_overloaded_cache = (now + 5.0, overloaded)
        return overloaded

    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        priority: str = "normal",
    ) -> tuple[ModelResponse, str, str | None]:
        try:
            response = await self.primary.generate(messages, tools, temperature, max_tokens)
            return response, "primary", None
        except Exception as exc:
            primary_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Primary provider failed: %s", primary_error)
            if priority == "low" and await self._local_llm_overloaded():
                raise ProviderError(primary_error, retryable=True) from exc
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
