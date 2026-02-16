"""WhatsApp channel adapter implementation."""

from __future__ import annotations

from typing import Any

import httpx

from jarvis.channels.base import InboundMessage
from jarvis.config import get_settings


class WhatsAppAdapter:
    """ChannelAdapter implementation for WhatsApp Cloud API."""

    @property
    def channel_type(self) -> str:
        return "whatsapp"

    async def send_text(self, recipient: str, text: str) -> int:
        settings = get_settings()
        url = f"https://graph.facebook.com/v21.0/{settings.whatsapp_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": text},
        }
        headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload, headers=headers)
        return response.status_code

    def parse_inbound(self, payload: dict[str, Any]) -> list[InboundMessage]:
        messages: list[InboundMessage] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    text = msg.get("text", {}).get("body", "")
                    sender = msg.get("from", "unknown")
                    msg_id = msg.get("id", "")
                    if text and msg_id:
                        messages.append(
                            InboundMessage(
                                external_msg_id=msg_id,
                                sender_id=sender,
                                text=text,
                                raw=msg,
                            )
                        )
        return messages
