"""Unit tests for db/queries.py helpers."""

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    ensure_channel,
    ensure_open_thread,
    ensure_user,
    get_channel_outbound,
    insert_message,
)
from jarvis.ids import new_id


def test_insert_message_media_round_trip() -> None:
    """insert_message with media_path/mime_type should be retrievable via get_channel_outbound."""
    with get_conn() as conn:
        # Set up user, channel, and thread.
        user_id = ensure_user(conn, f"wa_media_test_{new_id('usr')}")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)

        # Insert an assistant message with media fields.
        media_path = "/tmp/voice_test.ogg"
        mime_type = "audio/ogg"
        message_id = insert_message(
            conn,
            thread_id,
            "assistant",
            "Transcribed voice content",
            media_path=media_path,
            mime_type=mime_type,
        )

        # Verify via get_channel_outbound that media fields are returned.
        row = get_channel_outbound(conn, thread_id, message_id, "whatsapp")

    assert row is not None
    assert row["media_path"] == media_path
    assert row["mime_type"] == mime_type


def test_insert_message_without_media() -> None:
    """insert_message without media params stores None for media fields."""
    with get_conn() as conn:
        user_id = ensure_user(conn, f"wa_nomedia_test_{new_id('usr')}")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = ensure_open_thread(conn, user_id, channel_id)

        message_id = insert_message(conn, thread_id, "assistant", "Hello world")

        row = get_channel_outbound(conn, thread_id, message_id, "whatsapp")

    assert row is not None
    assert row["media_path"] is None
    assert row["mime_type"] is None


def test_ensure_open_thread_unification_across_channels() -> None:
    """ensure_open_thread uses user_id only — different channel_ids return the same thread."""
    with get_conn() as conn:
        user_id = ensure_user(conn, f"multi_channel_user_{new_id('usr')}")
        channel_id_whatsapp = ensure_channel(conn, user_id, "whatsapp")
        channel_id_telegram = ensure_channel(conn, user_id, "telegram")

        thread_id_1 = ensure_open_thread(conn, user_id, channel_id_whatsapp)
        thread_id_2 = ensure_open_thread(conn, user_id, channel_id_telegram)

    assert thread_id_1 == thread_id_2, (
        "ensure_open_thread should return the same thread for a user regardless of channel"
    )
