"""Channel adapter registry — maps channel_type strings to adapter instances."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)

_adapters: dict[str, ChannelAdapter] = {}


def register_channel(adapter: ChannelAdapter) -> None:
    """Register a channel adapter instance."""
    _adapters[adapter.channel_type] = adapter


def get_channel(channel_type: str) -> ChannelAdapter | None:
    """Look up a registered adapter by channel type."""
    return _adapters.get(channel_type)


def all_channels() -> dict[str, ChannelAdapter]:
    """Return a copy of the current adapter map."""
    return dict(_adapters)


def _reset() -> None:
    """Clear all registered adapters (for testing)."""
    _adapters.clear()
