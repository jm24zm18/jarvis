"""Unit tests for db/queries.py helpers."""

from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    ensure_channel,
    ensure_open_thread,
    ensure_user,
    get_channel_outbound,
    insert_message,
    prune_whatsapp_thread_map_orphans,
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


def test_prune_whatsapp_thread_map_orphans_removes_missing_threads() -> None:
    with get_conn() as conn:
        user_id = ensure_user(conn, f"wa_map_orphan_test_{new_id('usr')}")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        valid_thread_id = ensure_open_thread(conn, user_id, channel_id)

        conn.execute(
            (
                "INSERT INTO whatsapp_thread_map("
                "thread_id, instance, remote_jid, participant_jid, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?)"
            ),
            (
                valid_thread_id,
                "personal",
                "15550001111@s.whatsapp.net",
                "",
                "2026-02-21T00:00:00+00:00",
                "2026-02-21T00:00:00+00:00",
            ),
        )

        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            (
                "INSERT INTO whatsapp_thread_map("
                "thread_id, instance, remote_jid, participant_jid, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?)"
            ),
            (
                "thr_missing_orphan",
                "personal",
                "15550002222@s.whatsapp.net",
                "",
                "2026-02-21T00:00:00+00:00",
                "2026-02-21T00:00:00+00:00",
            ),
        )
        conn.execute("PRAGMA foreign_keys = ON")

        removed = prune_whatsapp_thread_map_orphans(conn)
        rows = conn.execute(
            "SELECT remote_jid, thread_id FROM whatsapp_thread_map "
            "ORDER BY remote_jid ASC"
        ).fetchall()

    assert removed == 1
    assert len(rows) == 1
    assert str(rows[0]["remote_jid"]) == "15550001111@s.whatsapp.net"
    assert str(rows[0]["thread_id"]) == valid_thread_id
