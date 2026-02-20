"""Evolution API client for WhatsApp personal account integration."""

from __future__ import annotations

from typing import Any

import httpx

from jarvis.config import get_settings


class EvolutionClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.evolution_api_url.rstrip("/")
        self._api_key = settings.evolution_api_key.strip()
        self._instance = settings.whatsapp_instance.strip() or "personal"
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
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["apikey"] = self._api_key
        return headers

    async def send_text(self, recipient: str, text: str) -> int:
        url = f"{self._base_url}/message/sendText/{self._instance}"
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
        url = f"{self._base_url}/message/sendMedia/{self._instance}"
        payload = {
            "number": recipient,
            "mediatype": media_type,
            "media": media_url,
            "caption": caption,
            "fileName": file_name,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=self._headers())
        return response.status_code

    async def send_reaction(self, remote_jid: str, message_id: str, emoji: str) -> int:
        url = f"{self._base_url}/message/sendReaction/{self._instance}"
        payload = {"remoteJid": remote_jid, "messageId": message_id, "reaction": emoji}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload, headers=self._headers())
        return response.status_code

    async def create_instance(self) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/instance/create"
        payload = {"instanceName": self._instance, "qrcode": True}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload, headers=self._headers())
        return response.status_code, self._safe_json(response)

    async def status(self) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/instance/connectionState/{self._instance}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=self._headers())
        return response.status_code, self._safe_json(response)

    async def qrcode(self) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/instance/connect/{self._instance}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=self._headers())
        return response.status_code, self._safe_json(response)

    async def pairing_code(self, number: str) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/instance/connect/{self._instance}"
        payload = {"number": number}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload, headers=self._headers())
        return response.status_code, self._safe_json(response)

    async def disconnect(self) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/instance/logout/{self._instance}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.delete(url, headers=self._headers())
        return response.status_code, self._safe_json(response)

    async def configure_webhook(self) -> tuple[int, dict[str, Any]]:
        if not self.webhook_enabled:
            return 400, {"error": "webhook_url_not_configured"}
        url = f"{self._base_url}/webhook/set/{self._instance}"
        payload = {
            "enabled": True,
            "url": self._webhook_url,
            "webhookByEvents": self._webhook_by_events,
            "events": self._webhook_events,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload, headers=self._headers())
        return response.status_code, self._safe_json(response)

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}
