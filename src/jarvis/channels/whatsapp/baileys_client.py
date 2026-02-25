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
        self._base_url = settings.baileys_api_url.strip().rstrip("/")
        self._instance = settings.whatsapp_instance.strip() or "personal"

        # Webhook is configured in the Baileys sidecar container environment.
        self._webhook_url = settings.baileys_webhook_url.strip()
        self._webhook_by_events = int(settings.baileys_webhook_by_events) == 1
        self._webhook_events = [
            item.strip()
            for item in settings.baileys_webhook_events.split(",")
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

    async def send_presence(self, recipient: str, presence: str = "composing") -> int:
        """Send typing indicator to a WhatsApp contact.

        Args:
            recipient: WhatsApp JID (e.g. 15551234567@s.whatsapp.net)
            presence: One of "composing", "paused", "available", "unavailable"
        """
        url = f"{self._base_url}/presenceUpdate"
        payload = {"number": recipient, "presence": presence}
        async with httpx.AsyncClient(timeout=10) as client:
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

    async def download_media(self, message: dict[str, Any], target_path: str) -> int:
        """Download and decrypt media from a Baileys message via the microservice.

        Args:
            message: The raw Baileys message object containing the encrypted media.
            target_path: Local file path to save the decrypted media.

        Returns:
            Number of bytes written, or 0 on failure.
        """
        url = f"{self._base_url}/downloadMedia"
        payload = {"message": message}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(url, json=payload, headers=self._headers())
            if response.status_code != 200:
                return 0
            from pathlib import Path
            Path(target_path).parent.mkdir(parents=True, exist_ok=True)
            Path(target_path).write_bytes(response.content)
            return len(response.content)
        except Exception:
            return 0

    async def create_instance(self) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/start"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=self._headers())
        return response.status_code, self._safe_json(response)

    async def reset_instance(self) -> tuple[int, dict[str, Any]]:
        """Force a full re-pair by clearing saved credentials then reconnecting."""
        url = f"{self._base_url}/reset"
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

    async def restart_server(self) -> tuple[int, dict[str, Any]]:
        """Restart the Baileys Node process; Docker restart: always will revive it."""
        url = f"{self._base_url}/restart"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(url, headers=self._headers())
            return response.status_code, self._safe_json(response)
        except Exception:
            # Expected: the process exits before it can send a response
            return 200, {"ok": True, "message": "restarting"}

    async def configure_webhook(self) -> tuple[int, dict[str, Any]]:
        # Sidecar handles webhook forwarding; nothing to configure over HTTP.
        return 200, {"success": True, "mode": "managed_by_sidecar"}

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}
