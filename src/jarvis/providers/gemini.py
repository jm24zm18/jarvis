"""Gemini provider adapter using OAuth refresh-token flow."""

import json
from datetime import UTC, datetime, timedelta

import httpx

from jarvis.config import get_settings
from jarvis.providers._gemini_common import build_request_body, parse_response
from jarvis.providers.base import ModelResponse


class GeminiProvider:
    def __init__(
        self,
        model: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._transport = transport
        self._access_token: str | None = None
        self._access_token_expires_at: datetime | None = None

    async def _refresh_access_token(self) -> str:
        settings = get_settings()
        if (
            not settings.google_oauth_client_id
            or not settings.google_oauth_client_secret
            or not settings.google_oauth_refresh_token
        ):
            raise RuntimeError("gemini oauth credentials are missing")

        if (
            self._access_token is not None
            and self._access_token_expires_at is not None
            and datetime.now(UTC) < self._access_token_expires_at
        ):
            return self._access_token

        payload = {
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "refresh_token": settings.google_oauth_refresh_token,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=15, transport=self._transport) as client:
            response = await client.post("https://oauth2.googleapis.com/token", data=payload)
            response.raise_for_status()
        body = response.json()
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("gemini token refresh response missing access_token")
        expires_in_raw = body.get("expires_in", 3600)
        expires_in = int(expires_in_raw) if isinstance(expires_in_raw, int | float | str) else 3600
        self._access_token = token
        self._access_token_expires_at = datetime.now(UTC) + timedelta(
            seconds=max(1, expires_in - 60)
        )
        return token

    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ModelResponse:
        access_token = await self._refresh_access_token()
        body = build_request_body(messages, tools, temperature, max_tokens)

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30, transport=self._transport) as client:
            response = await client.post(url, headers=headers, content=json.dumps(body))
            response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("gemini response is not an object")
        return parse_response(payload)

    async def health_check(self) -> bool:
        try:
            access_token = await self._refresh_access_token()
        except Exception:
            return False
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(timeout=10, transport=self._transport) as client:
                response = await client.get(url, headers=headers)
            return response.status_code < 400
        except Exception:
            return False
