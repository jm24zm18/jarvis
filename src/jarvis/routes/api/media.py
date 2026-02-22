"""Media upload/download REST endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from jarvis.auth.dependencies import UserContext, require_scope
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.media.service import MediaService

router = APIRouter(prefix="/media", tags=["api-media"])


@router.post("/upload")
async def upload_media(
    file: Annotated[UploadFile, File(...)],
    thread_id: Annotated[str | None, Form()] = None,
    ctx: UserContext = Depends(require_scope("media:write")),  # noqa: B008
) -> dict[str, object]:
    """Upload a media file and return its attachment ID and access URL."""
    del thread_id
    settings = get_settings()
    max_bytes = settings.media_max_upload_bytes

    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file too large: max {max_bytes} bytes",
        )

    mime_type = file.content_type or "application/octet-stream"
    filename = file.filename or "upload"

    service = MediaService()
    with get_conn() as conn:
        try:
            attachment_id = service.upload(
                conn,
                owner_id=ctx.user_id,
                file_data=data,
                filename=filename,
                mime_type=mime_type,
            )
        except ValueError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc

    return {
        "attachment_id": attachment_id,
        "url": f"/api/v1/media/{attachment_id}",
        "mime_type": mime_type,
        "size_bytes": len(data),
    }


@router.get("/{attachment_id}")
def download_media(
    attachment_id: str,
    ctx: UserContext = Depends(require_scope("media:read")),  # noqa: B008
) -> FileResponse:
    """Stream a media attachment, enforcing ownership."""
    service = MediaService()
    with get_conn() as conn:
        item = service.get(conn, attachment_id)

    if item is None:
        raise HTTPException(status_code=404, detail="attachment not found")

    if not ctx.is_admin and str(item["owner_id"]) != ctx.user_id:
        raise HTTPException(status_code=403, detail="forbidden")

    file_path = Path(str(item["file_path"]))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="file not found on disk")

    return FileResponse(
        path=str(file_path),
        media_type=str(item["mime_type"]),
        filename=str(item.get("original_filename") or attachment_id),
    )


@router.get("/{attachment_id}/thumb")
def download_thumbnail(
    attachment_id: str,
    ctx: UserContext = Depends(require_scope("media:read")),  # noqa: B008
) -> FileResponse:
    """Stream a thumbnail for an image attachment."""
    service = MediaService()
    with get_conn() as conn:
        item = service.get(conn, attachment_id)

    if item is None:
        raise HTTPException(status_code=404, detail="attachment not found")

    if not ctx.is_admin and str(item["owner_id"]) != ctx.user_id:
        raise HTTPException(status_code=403, detail="forbidden")

    thumb_path_raw = item.get("thumbnail_path")
    if not thumb_path_raw:
        raise HTTPException(status_code=404, detail="no thumbnail available")

    thumb_path = Path(str(thumb_path_raw))
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="thumbnail not found on disk")

    return FileResponse(
        path=str(thumb_path),
        media_type="image/jpeg",
    )
