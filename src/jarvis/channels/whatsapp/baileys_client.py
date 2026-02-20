"""Baileys API client for WhatsApp personal account integration."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from jarvis.config import get_settings

logger = logging.getLogger(__name__)


class BaileysClient:
    def __init__(self) -> None:
        settings = get_settings()
        # Fallback to local container if env var strictly not found
        self._base_url = (getattr(settings, "baileys_api_url", None) or "http://127.0.0.1:8081").rstrip("/")
        self._instance = settings.whatsapp_instance.strip() or "personal"
        
        # Webhook is hardcoded/configured in the node container via environment,
        # but we maintain the properties so channels.py doesn't break
        self._webhook_url = settings.evolution_webhook_url.strip()
        self._webhook_by_events = int(settings.evolution_webhook_by_events) == 1
        self._webhook_events = [
            item.strip()
            for item in settings.evolution_webhook_events.split(",")
            if item.strip()
        ]

    @property
    def enabled(self) -> bool:
        return bool(self._base_url)

    @property
    def instance(self) -> str:
        return self._instance

    @property
    def webhook_url(self) -> str:
        return self._webhook_url

    @property
    def webhook_by_events(self) -> bool:
        return self._webhook_by_events

    @property
    def webhook_events(self) -> list[str]:
        return list(self._webhook_events)

    @property
    def webhook_enabled(self) -> bool:
        return bool(self._webhook_url)

    def _headers(self) -> dict[str, str]:
        # Minimalist microservice doesn't need apikey yet, but can be passed
        return {"Content-Type": "application/json"}

    async def send_text(self, recipient: str, text: str) -> int:
        url = f"{self._base_url}/sendText"
        payload = {"number": recipient, "text": text}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload, headers=self._headers())
        return response.status_code

    async def send_media(
        self,
        recipient: str,
        *,
        media_type: str,
        media_url: str,
        caption: str = "",
        file_name: str = "file",
    ) -> int:
        # Not yet fully implemented in microservice, stub it to avoid crashes
        return 501

    async def send_reaction(self, remote_jid: str, message_id: str, emoji: str) -> int:
        # Not yet fully implemented in microservice, stub it to avoid crashes
        return 501

    async def create_instance(self) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/start"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=self._headers())
        return response.status_code, self._safe_json(response)

    async def status(self) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/status"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=self._headers())
        return response.status_code, self._safe_json(response)

    async def qrcode(self) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/qr"
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.get(url, headers=self._headers())
        return response.status_code, self._safe_json(response)

    async def pairing_code(self, number: str) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/pair"
        payload = {"number": number}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload, headers=self._headers())
        return response.status_code, self._safe_json(response)

    async def disconnect(self) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/disconnect"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=self._headers())
        return response.status_code, self._safe_json(response)

    async def configure_webhook(self) -> tuple[int, dict[str, Any]]:
        # Mock successful webhook config as the Node service handles this natively
        return 200, {"success": True, "message": "Handled internally by Baileys service"}

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}
