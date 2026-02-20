"""Telegram channel adapter implementation using Bot API."""

from __future__ import annotations

from typing import Any

import httpx

from jarvis.channels.base import InboundMessage
from jarvis.config import get_settings


class TelegramAdapter:
    @property
    def channel_type(self) -> str:
        return "telegram"

    async def send_text(self, recipient: str, text: str) -> int:
        """Send a text message via Telegram Bot API.

        ``recipient`` is the chat_id (string or integer).
        Long messages are automatically chunked to stay within the 4096
        character limit imposed by the Telegram Bot API.
        """
        settings = get_settings()
        token = settings.telegram_bot_token
        if not token:
            return 503
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        chunks = _chunk_text(text, max_len=4096)
        last_status = 200
        async with httpx.AsyncClient(timeout=20) as client:
            for chunk in chunks:
                payload = {
                    "chat_id": recipient,
                    "text": chunk,
                    "parse_mode": "Markdown",
                }
                response = await client.post(url, json=payload)
                last_status = response.status_code
                if last_status >= 400:
                    break
        return last_status

    def parse_inbound(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Parse a Telegram Bot API Update payload into InboundMessages."""
        messages: list[InboundMessage] = []

        msg = payload.get("message") or payload.get("edited_message")
        if not isinstance(msg, dict):
            return messages

        msg_id = str(msg.get("message_id", ""))
        if not msg_id:
            return messages

        sender = msg.get("from", {}) if isinstance(msg.get("from"), dict) else {}
        sender_id = str(sender.get("id", "unknown"))

        chat = msg.get("chat", {}) if isinstance(msg.get("chat"), dict) else {}
        chat_id = str(chat.get("id", ""))
        chat_type = str(chat.get("type", "private"))

        text = str(msg.get("text") or msg.get("caption") or "")

        # Extract message type and media URL
        message_type = "text"
        media: dict[str, Any] = {}
        media_url: str | None = None

        if "photo" in msg:
            message_type = "image"
            photos = msg.get("photo", [])
            if isinstance(photos, list) and photos:
                best = photos[-1] if isinstance(photos[-1], dict) else {}
                media = {"type": "image", "file_id": best.get("file_id", "")}
        elif "voice" in msg:
            message_type = "audio"
            voice = msg.get("voice", {}) if isinstance(msg.get("voice"), dict) else {}
            media = {"type": "audio", "file_id": voice.get("file_id", ""),
                     "duration": voice.get("duration")}
        elif "audio" in msg:
            message_type = "audio"
            audio = msg.get("audio", {}) if isinstance(msg.get("audio"), dict) else {}
            media = {"type": "audio", "file_id": audio.get("file_id", ""),
                     "duration": audio.get("duration")}
        elif "document" in msg:
            message_type = "document"
            doc = msg.get("document", {}) if isinstance(msg.get("document"), dict) else {}
            media = {"type": "document", "file_id": doc.get("file_id", ""),
                     "file_name": doc.get("file_name", "")}
        elif "video" in msg:
            message_type = "video"
            video = msg.get("video", {}) if isinstance(msg.get("video"), dict) else {}
            media = {"type": "video", "file_id": video.get("file_id", ""),
                     "duration": video.get("duration")}
        elif "sticker" in msg:
            message_type = "sticker"
            sticker = msg.get("sticker", {}) if isinstance(msg.get("sticker"), dict) else {}
            media = {"type": "sticker", "file_id": sticker.get("file_id", ""),
                     "emoji": sticker.get("emoji", "")}

        # Extract mentions (entities of type "mention")
        mentions: list[str] = []
        entities = msg.get("entities", [])
        if isinstance(entities, list):
            for entity in entities:
                if isinstance(entity, dict) and entity.get("type") == "mention":
                    offset = int(entity.get("offset", 0))
                    length = int(entity.get("length", 0))
                    if text and offset >= 0 and length > 0:
                        mentions.append(text[offset:offset + length])

        # Group context
        group_context: dict[str, Any] = {}
        if chat_type in ("group", "supergroup"):
            group_context = {
                "chat_id": chat_id,
                "chat_type": chat_type,
                "chat_title": chat.get("title", ""),
                "is_group": True,
            }

        messages.append(
            InboundMessage(
                external_msg_id=f"tg_{msg_id}",
                sender_id=sender_id,
                text=text,
                media_url=media_url,
                message_type=message_type,
                media=media if media else {},
                mentions=mentions,
                group_context=group_context,
                thread_key=chat_id,
                raw=payload,
            )
        )

        return messages


def _chunk_text(text: str, max_len: int = 4096) -> list[str]:
    """Split text into chunks of at most ``max_len`` characters."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks
