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

    __slots__ = ("external_msg_id", "sender_id", "text", "media_url", "raw")

    def __init__(
        self,
        *,
        external_msg_id: str,
        sender_id: str,
        text: str,
        media_url: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        self.external_msg_id = external_msg_id
        self.sender_id = sender_id
        self.text = text
        self.media_url = media_url
        self.raw = raw or {}
