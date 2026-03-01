"""Media attachment service."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from jarvis.ids import new_id
from jarvis.media.storage import LocalDiskProvider, StorageProvider

logger = logging.getLogger(__name__)

_ALLOWED_MIME_PREFIXES = (
    "image/",
    "audio/",
    "video/",
    "application/pdf",
    "text/plain",
)

_THUMBNAIL_SIZE = (200, 200)


def _is_allowed_mime(mime_type: str) -> bool:
    value = mime_type.strip().lower()
    return any(value.startswith(prefix) for prefix in _ALLOWED_MIME_PREFIXES)


def _safe_thumbnail(file_path: Path, thumb_path: Path) -> bool:
    """Generate a 200×200 thumbnail using Pillow. Returns True on success."""
    try:
        from PIL import Image

        with Image.open(file_path) as img:
            img.thumbnail(_THUMBNAIL_SIZE)
            img.save(thumb_path)
        return True
    except Exception:
        logger.debug("Thumbnail generation failed for %s", file_path, exc_info=True)
        return False


class MediaService:
    def __init__(self, storage: StorageProvider | None = None) -> None:
        self._storage: StorageProvider = storage or LocalDiskProvider()

    def upload(
        self,
        conn: sqlite3.Connection,
        owner_id: str,
        file_data: bytes,
        filename: str,
        mime_type: str,
        *,
        message_id: str | None = None,
        event_id: str | None = None,
    ) -> str:
        """Store *file_data* and insert a media_attachments row.

        Returns the new attachment ID (``mda_…``).
        Raises ValueError for disallowed MIME types.
        """
        if not _is_allowed_mime(mime_type):
            raise ValueError(f"mime type not allowed: {mime_type!r}")

        attachment_id = new_id("mda")
        safe_filename = f"{attachment_id}_{Path(filename).name}"
        file_path = self._storage.save(file_data, safe_filename)

        thumbnail_path: str | None = None
        if mime_type.startswith("image/"):
            thumb_name = f"{attachment_id}_thumb.jpg"
            thumb_target = self._storage.resolve(thumb_name)
            thumb_target.parent.mkdir(parents=True, exist_ok=True)
            if _safe_thumbnail(file_path, thumb_target):
                thumbnail_path = str(thumb_target)

        now = datetime.now(UTC).isoformat()
        conn.execute(
            (
                "INSERT INTO media_attachments("
                "id, owner_id, message_id, event_id, file_path, mime_type, "
                "size_bytes, thumbnail_path, original_filename, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                attachment_id,
                owner_id,
                message_id,
                event_id,
                str(file_path),
                mime_type,
                len(file_data),
                thumbnail_path,
                filename,
                now,
            ),
        )
        return attachment_id

    def get(self, conn: sqlite3.Connection, attachment_id: str) -> dict[str, object] | None:
        row = conn.execute(
            "SELECT id, owner_id, message_id, file_path, mime_type, "
            "size_bytes, thumbnail_path, original_filename, created_at "
            "FROM media_attachments WHERE id=? LIMIT 1",
            (attachment_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "owner_id": str(row["owner_id"]),
            "message_id": str(row["message_id"]) if row["message_id"] is not None else None,
            "file_path": str(row["file_path"]),
            "mime_type": str(row["mime_type"]),
            "size_bytes": int(row["size_bytes"]),
            "thumbnail_path": (
                str(row["thumbnail_path"]) if row["thumbnail_path"] is not None else None
            ),
            "original_filename": (
                str(row["original_filename"]) if row["original_filename"] is not None else None
            ),
            "created_at": str(row["created_at"]),
        }

    def list_for_message(
        self, conn: sqlite3.Connection, message_id: str
    ) -> list[dict[str, object]]:
        rows = conn.execute(
            "SELECT id, owner_id, mime_type, size_bytes, thumbnail_path, created_at "
            "FROM media_attachments WHERE message_id=? ORDER BY created_at ASC",
            (message_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "owner_id": str(row["owner_id"]),
                "mime_type": str(row["mime_type"]),
                "size_bytes": int(row["size_bytes"]),
                "thumbnail_path": (
                    str(row["thumbnail_path"]) if row["thumbnail_path"] is not None else None
                ),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
