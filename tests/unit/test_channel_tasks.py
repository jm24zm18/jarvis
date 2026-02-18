import logging

from jarvis.tasks.channel import send_channel_message


def test_send_channel_message_cli_missing_adapter_is_quiet(monkeypatch, caplog) -> None:
    monkeypatch.setattr("jarvis.tasks.channel.get_channel", lambda _channel_type: None)
    caplog.set_level(logging.WARNING)

    result = send_channel_message("thr_test", "msg_test", "cli")

    assert result["status"] == "skipped"
    assert "No adapter registered for channel_type=cli" not in caplog.text


def test_send_channel_message_unknown_channel_logs_warning(monkeypatch, caplog) -> None:
    monkeypatch.setattr("jarvis.tasks.channel.get_channel", lambda _channel_type: None)
    caplog.set_level(logging.WARNING)

    result = send_channel_message("thr_test", "msg_test", "unknown_channel")

    assert result["status"] == "skipped"
    assert "No adapter registered for channel_type=unknown_channel" in caplog.text
