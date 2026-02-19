"""Tests for the jarvis build CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from jarvis.cli.build import _SETTLE_SECONDS, BUILD_PROMPT


def test_build_prompt_contains_key_instructions() -> None:
    assert "auto/build-" in BUILD_PROMPT
    assert "test-gates" in BUILD_PROMPT
    assert "dev" in BUILD_PROMPT
    assert "do not delegate this flow to worker agents" in BUILD_PROMPT
    assert "gh pr create" in BUILD_PROMPT


def test_settle_seconds_is_positive() -> None:
    assert _SETTLE_SECONDS > 0


@patch("jarvis.cli.build._latest_assistant_message")
@patch("jarvis.cli.build.get_task_runner")
@patch("jarvis.cli.build.new_id", return_value="trc_fake")
@patch("jarvis.cli.build.get_conn")
@patch("jarvis.cli.build.insert_message", return_value="msg_u1")
@patch("jarvis.cli.build.resolve_thread", return_value="thr_fake123")
@patch("jarvis.cli.build.default_cli_user", return_value="cli:test@host")
def test_run_build_enqueues_and_polls(
    mock_user: MagicMock,
    mock_resolve: MagicMock,
    mock_insert: MagicMock,
    mock_conn: MagicMock,
    mock_new_id: MagicMock,
    mock_get_runner: MagicMock,
    mock_latest: MagicMock,
) -> None:
    from jarvis.cli.build import run_build

    runner = MagicMock()
    runner.send_task.return_value = True
    mock_get_runner.return_value = runner

    # Simulate: conn context manager returns a mock with execute().fetchone()
    ctx = MagicMock()
    ctx.execute.return_value.fetchone.return_value = {"created_at": "2026-01-01T00:00:00"}
    mock_conn.return_value.__enter__ = MagicMock(return_value=ctx)
    mock_conn.return_value.__exit__ = MagicMock(return_value=False)

    # First poll returns None, second returns a message, third returns same (settled)
    mock_latest.side_effect = [
        None,
        ("msg_a1", "All gates pass.", "2026-01-01T00:00:01"),
        ("msg_a1", "All gates pass.", "2026-01-01T00:00:01"),
    ]

    with patch("jarvis.cli.build._SETTLE_SECONDS", 0):
        with patch("jarvis.cli.build.time") as mock_time:
            # monotonic() calls: deadline calc, loop check, seen_at, loop check, settle check
            mock_time.monotonic.side_effect = [0, 0, 1, 2, 2, 100]
            mock_time.sleep = MagicMock()
            run_build(enqueue=True, timeout_s=300.0, poll_interval_s=0.1)

    mock_resolve.assert_called_once_with("cli:test@host", thread_id=None, new_thread=False)
    runner.send_task.assert_called_once()
    call_kwargs = runner.send_task.call_args
    assert call_kwargs.kwargs["kwargs"]["thread_id"] == "thr_fake123"
    assert call_kwargs.kwargs["kwargs"]["actor_id"] == "main"
