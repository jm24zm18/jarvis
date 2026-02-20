"""Channel adapter protocol for multi-channel support."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChannelAdapter(Protocol):
    """Protocol that all channel adapters must implement."""

    @property
    def channel_type(self) -> str:
        """Unique identifier for this channel (e.g. 'whatsapp', 'telegram', 'web')."""
        ...

    async def send_text(self, recipient: str, text: str) -> int:
        """Send a text message to a recipient. Returns HTTP status code."""
        ...

    def parse_inbound(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Extract messages from a raw inbound webhook payload."""
        ...


class InboundMessage:
    """Normalized inbound message from any channel."""

    __slots__ = (
        "external_msg_id",
        "sender_id",
        "text",
        "media_url",
        "message_type",
        "media",
        "reaction",
        "mentions",
        "group_context",
        "thread_key",
        "raw",
    )

    def __init__(
        self,
        *,
        external_msg_id: str,
        sender_id: str,
        text: str,
        media_url: str | None = None,
        message_type: str = "text",
        media: dict[str, Any] | None = None,
        reaction: dict[str, Any] | None = None,
        mentions: list[str] | None = None,
        group_context: dict[str, Any] | None = None,
        thread_key: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        self.external_msg_id = external_msg_id
        self.sender_id = sender_id
        self.text = text
        self.media_url = media_url
        self.message_type = message_type
        self.media = media or {}
        self.reaction = reaction or {}
        self.mentions = mentions or []
        self.group_context = group_context or {}
        self.thread_key = thread_key
        self.raw = raw or {}
