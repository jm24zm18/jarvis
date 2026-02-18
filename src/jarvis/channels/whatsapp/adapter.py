"""WhatsApp channel adapter implementation (Evolution-first, Cloud fallback)."""

from __future__ import annotations

from typing import Any

import httpx

from jarvis.channels.base import InboundMessage
from jarvis.channels.whatsapp.evolution_client import EvolutionClient
from jarvis.config import get_settings


class WhatsAppAdapter:
    @property
    def channel_type(self) -> str:
        return "whatsapp"

    async def send_text(self, recipient: str, text: str) -> int:
        evolution = EvolutionClient()
        if evolution.enabled:
            return await evolution.send_text(recipient=recipient, text=text)

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
        if self._looks_like_evolution(payload):
            return self._parse_evolution(payload)
        return self._parse_cloud(payload)

    @staticmethod
    def _looks_like_evolution(payload: dict[str, Any]) -> bool:
        return isinstance(payload.get("event"), str) and isinstance(payload.get("data"), dict)

    def _parse_cloud(self, payload: dict[str, Any]) -> list[InboundMessage]:
        messages: list[InboundMessage] = []
        for entry in payload.get("entry", []):
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes", []):
                if not isinstance(change, dict):
                    continue
                value = change.get("value", {})
                if not isinstance(value, dict):
                    continue
                for msg in value.get("messages", []):
                    if not isinstance(msg, dict):
                        continue
                    text = str((msg.get("text") or {}).get("body") or "")
                    sender = str(msg.get("from") or "unknown")
                    msg_id = str(msg.get("id") or "")
                    if not msg_id:
                        continue
                    messages.append(
                        InboundMessage(
                            external_msg_id=msg_id,
                            sender_id=sender,
                            text=text,
                            message_type="text",
                            raw=msg,
                        )
                    )
        return messages

    def _parse_evolution(self, payload: dict[str, Any]) -> list[InboundMessage]:
        event = str(payload.get("event") or "")
        if event != "messages.upsert":
            return []
        records = self._evolution_records(payload.get("data"))
        messages: list[InboundMessage] = []
        for data in records:
            parsed = self._parse_evolution_record(payload, data)
            if parsed is not None:
                messages.append(parsed)
        return messages

    def _parse_evolution_record(
        self, payload: dict[str, Any], data: dict[str, Any]
    ) -> InboundMessage | None:
        key = data.get("key", {}) if isinstance(data.get("key"), dict) else {}
        message = data.get("message", {}) if isinstance(data.get("message"), dict) else {}
        msg_id = str(key.get("id") or data.get("id") or "")
        remote_jid = str(key.get("remoteJid") or data.get("remoteJid") or "")
        participant = str(key.get("participant") or data.get("participant") or "")
        sender = participant or remote_jid or "unknown"
        thread_key = remote_jid or sender
        if not msg_id:
            return None

        mentions = self._extract_mentions(message)
        group_context = {
            "remote_jid": remote_jid,
            "participant": participant,
            "is_group": remote_jid.endswith("@g.us") if remote_jid else False,
        }

        if "conversation" in message:
            text = str(message.get("conversation") or "")
            return InboundMessage(
                external_msg_id=msg_id,
                sender_id=sender,
                text=text,
                message_type="text",
                mentions=mentions,
                group_context=group_context,
                thread_key=thread_key,
                raw=payload,
            )

        extended = message.get("extendedTextMessage")
        if isinstance(extended, dict):
            text = str(extended.get("text") or "")
            return InboundMessage(
                external_msg_id=msg_id,
                sender_id=sender,
                text=text,
                message_type="text",
                mentions=mentions,
                group_context=group_context,
                thread_key=thread_key,
                raw=payload,
            )

        reaction = message.get("reactionMessage")
        if isinstance(reaction, dict):
            reaction_text = str(reaction.get("text") or "")
            return InboundMessage(
                external_msg_id=msg_id,
                sender_id=sender,
                text="",
                message_type="reaction",
                reaction={
                    "emoji": reaction_text,
                    "key": reaction.get("key") if isinstance(reaction.get("key"), dict) else {},
                },
                mentions=mentions,
                group_context=group_context,
                thread_key=thread_key,
                raw=payload,
            )

        media_candidates: list[tuple[str, str]] = [
            ("audioMessage", "audio"),
            ("imageMessage", "image"),
            ("videoMessage", "video"),
            ("documentMessage", "document"),
            ("stickerMessage", "sticker"),
        ]
        for key_name, media_type in media_candidates:
            media_node = message.get(key_name)
            if not isinstance(media_node, dict):
                continue
            caption = str(media_node.get("caption") or "")
            media_url = str(media_node.get("url") or "")
            return InboundMessage(
                external_msg_id=msg_id,
                sender_id=sender,
                text=caption,
                media_url=media_url or None,
                message_type=media_type,
                media={
                    "type": media_type,
                    "url": media_url,
                    "mime_type": str(media_node.get("mimetype") or ""),
                    "seconds": media_node.get("seconds"),
                },
                mentions=mentions,
                group_context=group_context,
                thread_key=thread_key,
                raw=payload,
            )

        return InboundMessage(
            external_msg_id=msg_id,
            sender_id=sender,
            text="",
            message_type="unknown",
            mentions=mentions,
            group_context=group_context,
            thread_key=thread_key,
            raw=payload,
        )

    @staticmethod
    def _evolution_records(data: object) -> list[dict[str, Any]]:
        if isinstance(data, dict):
            records = data.get("messages")
            if isinstance(records, list):
                return [item for item in records if isinstance(item, dict)]
            return [data]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_mentions(message: dict[str, Any]) -> list[str]:
        mentions: list[str] = []
        extended = message.get("extendedTextMessage")
        if isinstance(extended, dict):
            context = extended.get("contextInfo")
            if isinstance(context, dict):
                mentioned = context.get("mentionedJid")
                if isinstance(mentioned, list):
                    mentions = [str(item) for item in mentioned if isinstance(item, str)]
        return mentions
