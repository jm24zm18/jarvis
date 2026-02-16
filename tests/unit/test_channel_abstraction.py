"""Tests for channel abstraction layer."""

from jarvis.channels.base import ChannelAdapter, InboundMessage
from jarvis.channels.registry import (
    _reset,
    all_channels,
    get_channel,
    register_channel,
)
from jarvis.channels.whatsapp.adapter import WhatsAppAdapter


class MockAdapter:
    @property
    def channel_type(self) -> str:
        return "mock"

    async def send_text(self, recipient: str, text: str) -> int:
        return 200

    def parse_inbound(self, payload):
        return [
            InboundMessage(
                external_msg_id="m1", sender_id="u1", text=payload.get("text", "")
            )
        ]


def test_whatsapp_adapter_is_channel_adapter() -> None:
    adapter = WhatsAppAdapter()
    assert isinstance(adapter, ChannelAdapter)
    assert adapter.channel_type == "whatsapp"


def test_whatsapp_adapter_parse_inbound() -> None:
    adapter = WhatsAppAdapter()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.1",
                                    "from": "15551234567",
                                    "text": {"body": "hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    messages = adapter.parse_inbound(payload)
    assert len(messages) == 1
    assert messages[0].external_msg_id == "wamid.1"
    assert messages[0].sender_id == "15551234567"
    assert messages[0].text == "hello"


def test_registry_register_and_get() -> None:
    _reset()
    adapter = MockAdapter()
    register_channel(adapter)
    assert get_channel("mock") is adapter
    assert get_channel("nonexistent") is None
    assert "mock" in all_channels()
    _reset()


def test_registry_reset_clears() -> None:
    _reset()
    register_channel(MockAdapter())
    assert len(all_channels()) == 1
    _reset()
    assert len(all_channels()) == 0
