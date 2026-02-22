"""Unit tests for media attachment storage service."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.channels.whatsapp.media_security import MediaSecurityError
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_channel, ensure_open_thread, ensure_user, insert_message
from jarvis.media.service import MediaService
from jarvis.media.storage import LocalDiskProvider


def _seed_message() -> tuple[str, str]:
    with get_conn() as conn:
        user_id = ensure_user(conn, "media-unit-user")
        channel_id = ensure_channel(conn, user_id, "telegram")
        thread_id = ensure_open_thread(conn, user_id, channel_id)
        message_id = insert_message(conn, thread_id, "user", "hello")
    return user_id, message_id


def test_upload_stores_file_and_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()
    user_id, message_id = _seed_message()

    with get_conn() as conn:
        attachment_id = MediaService().upload(
            conn,
            owner_id=user_id,
            file_data=b"hello world",
            filename="note.txt",
            mime_type="text/plain",
            message_id=message_id,
        )
        row = conn.execute(
            "SELECT file_path, mime_type, size_bytes, message_id FROM media_attachments WHERE id=?",
            (attachment_id,),
        ).fetchone()

    assert row is not None
    assert row["mime_type"] == "text/plain"
    assert int(row["size_bytes"]) == len(b"hello world")
    assert str(row["message_id"]) == message_id
    assert Path(str(row["file_path"])).exists()


def test_upload_rejects_disallowed_mime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()
    user_id, _ = _seed_message()

    with get_conn() as conn:
        with pytest.raises(ValueError, match="mime type not allowed"):
            MediaService().upload(
                conn,
                owner_id=user_id,
                file_data=b"#!/bin/sh\necho nope\n",
                filename="script.sh",
                mime_type="application/x-sh",
            )


def test_upload_generates_thumbnail_for_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pil = pytest.importorskip("PIL.Image")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()
    user_id, message_id = _seed_message()

    image_path = tmp_path / "source.png"
    img = pil.new("RGB", (600, 400), color=(200, 40, 40))
    img.save(image_path, format="PNG")
    image_bytes = image_path.read_bytes()

    with get_conn() as conn:
        attachment_id = MediaService().upload(
            conn,
            owner_id=user_id,
            file_data=image_bytes,
            filename="photo.png",
            mime_type="image/png",
            message_id=message_id,
        )
        row = conn.execute(
            "SELECT thumbnail_path FROM media_attachments WHERE id=?",
            (attachment_id,),
        ).fetchone()

    assert row is not None
    thumbnail_path = row["thumbnail_path"]
    assert thumbnail_path is not None
    assert Path(str(thumbnail_path)).exists()


def test_list_for_message_returns_attachment_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()
    user_id, message_id = _seed_message()

    with get_conn() as conn:
        svc = MediaService()
        attachment_id = svc.upload(
            conn,
            owner_id=user_id,
            file_data=b"attachment",
            filename="doc.txt",
            mime_type="text/plain",
            message_id=message_id,
        )
        items = svc.list_for_message(conn, message_id)

    assert len(items) == 1
    assert items[0]["id"] == attachment_id
    assert items[0]["mime_type"] == "text/plain"


def test_local_storage_blocks_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()
    provider = LocalDiskProvider()

    with pytest.raises(MediaSecurityError, match="media_path_unsafe"):
        provider.resolve("../escape.txt")
