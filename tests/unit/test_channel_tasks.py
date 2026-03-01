import logging

import httpx
import pytest
from _pytest.logging import LogCaptureFixture

from jarvis.tasks.channel import send_channel_message


def test_send_channel_message_cli_missing_adapter_is_quiet(
    monkeypatch: pytest.MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.setattr("jarvis.tasks.channel.get_channel", lambda _channel_type: None)
    caplog.set_level(logging.WARNING)

    result = send_channel_message("thr_test", "msg_test", "cli")

    assert result["status"] == "skipped"
    assert "No adapter registered for channel_type=cli" not in caplog.text


def test_send_channel_message_unknown_channel_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.setattr("jarvis.tasks.channel.get_channel", lambda _channel_type: None)
    caplog.set_level(logging.WARNING)

    result = send_channel_message("thr_test", "msg_test", "unknown_channel")

    assert result["status"] == "skipped"
    assert "No adapter registered for channel_type=unknown_channel" in caplog.text


def test_send_channel_message_whatsapp_failure_clears_typing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Adapter:
        def __init__(self) -> None:
            self.presence_calls: list[tuple[str, str]] = []

        async def send_text(self, recipient: str, text: str) -> int:
            del recipient, text
            raise httpx.ConnectError("boom")

        async def send_presence(self, recipient: str, presence: str = "composing") -> int:
            self.presence_calls.append((recipient, presence))
            return 200

    adapter = _Adapter()
    typing_clears: list[tuple[str, str]] = []
    metric_calls: list[str] = []
    emitted: list[str] = []

    monkeypatch.setattr("jarvis.tasks.channel.get_channel", lambda _channel_type: adapter)
    monkeypatch.setattr(
        "jarvis.tasks.channel.get_system_state",
        lambda _conn: {"lockdown": 0, "restarting": 0},
    )
    monkeypatch.setattr(
        "jarvis.tasks.channel.get_channel_outbound",
        lambda _conn, _thread_id, _message_id, _channel_type: {
            "recipient": "15551239999@s.whatsapp.net",
            "text": "hello",
        },
    )
    monkeypatch.setattr(
        "jarvis.tasks.channel.clear_typing_state",
        lambda _conn, thread_id, recipient: typing_clears.append((thread_id, recipient)),
    )
    monkeypatch.setattr(
        "jarvis.tasks.channel.increment_metric",
        lambda name, amount=1: metric_calls.extend([name] * amount),
    )
    monkeypatch.setattr("jarvis.tasks.channel.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("jarvis.tasks.channel.random.uniform", lambda _a, _b: 0.0)

    def _capture_emit(
        trace_id: str,
        thread_id: str,
        event_type: str,
        payload: dict[str, object],
        channel_type: str = "whatsapp",
        conn: object = None,
    ) -> None:
        del trace_id, thread_id, payload, channel_type, conn
        emitted.append(event_type)

    monkeypatch.setattr("jarvis.tasks.channel._emit", _capture_emit)

    result = send_channel_message("thr_test", "msg_test", "whatsapp")

    assert result["status"] == "failed"
    assert ("15551239999@s.whatsapp.net", "paused") in adapter.presence_calls
    assert typing_clears == [("thr_test", "15551239999@s.whatsapp.net")]
    assert "channel.typing.clear" in emitted
    assert "whatsapp_typing_active_threads_clear" in metric_calls
