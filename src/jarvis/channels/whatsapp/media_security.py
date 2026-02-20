"""Security helpers for inbound WhatsApp media handling."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx


class MediaSecurityError(RuntimeError):
    """Raised when inbound media cannot be safely processed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _commonpath_contains(parent: Path, child: Path) -> bool:
    try:
        return os.path.commonpath([str(parent), str(child)]) == str(parent)
    except ValueError:
        return False


def ensure_media_root(media_dir: str) -> Path:
    root = Path(media_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_media_output_path(media_root: Path, relative_name: str) -> Path:
    target = (media_root / relative_name).resolve()
    if not _commonpath_contains(media_root, target):
        raise MediaSecurityError("media_path_unsafe")
    return target


def parse_csv_set(value: str) -> set[str]:
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def validate_media_url(media_url: str, allowed_hosts: set[str]) -> None:
    parsed = urlparse(media_url)
    if parsed.scheme != "https":
        raise MediaSecurityError("media_url_invalid")
    if not parsed.hostname:
        raise MediaSecurityError("media_url_invalid")
    host = parsed.hostname.lower()
    if allowed_hosts and host not in allowed_hosts:
        raise MediaSecurityError("media_host_denied")


def validate_media_mime(mime_type: str, allowed_prefixes: set[str]) -> None:
    value = mime_type.strip().lower()
    if not value:
        raise MediaSecurityError("media_mime_denied")
    for prefix in allowed_prefixes:
        if value.startswith(prefix):
            return
    raise MediaSecurityError("media_mime_denied")


def media_filename(external_msg_id: str, media_type: str, mime_type: str) -> str:
    ext = "bin"
    lowered = mime_type.lower()
    if lowered.startswith("audio/ogg"):
        ext = "ogg"
    elif lowered.startswith("audio/mpeg"):
        ext = "mp3"
    elif lowered.startswith("audio/wav"):
        ext = "wav"
    elif lowered.startswith("image/jpeg"):
        ext = "jpg"
    elif lowered.startswith("image/png"):
        ext = "png"
    elif lowered.startswith("video/mp4"):
        ext = "mp4"
    elif lowered == "application/pdf":
        ext = "pdf"
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", external_msg_id)[:80] or "media"
    safe_type = re.sub(r"[^a-zA-Z0-9_-]", "_", media_type)[:24] or "file"
    return f"{safe_id}_{safe_type}.{ext}"


async def download_media_file(
    *,
    media_url: str,
    target_path: Path,
    max_bytes: int,
    timeout_seconds: int,
) -> int:
    if max_bytes <= 0:
        raise MediaSecurityError("media_size_exceeded")

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            async with client.stream("GET", media_url, follow_redirects=True) as response:
                if response.status_code >= 400:
                    raise MediaSecurityError("media_download_failed")
                content_length_raw = response.headers.get("Content-Length", "").strip()
                if content_length_raw:
                    try:
                        content_length = int(content_length_raw)
                    except ValueError:
                        content_length = 0
                    if content_length > max_bytes:
                        raise MediaSecurityError("media_size_exceeded")
                total = 0
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with target_path.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise MediaSecurityError("media_size_exceeded")
                        handle.write(chunk)
                return total
    except MediaSecurityError:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise
    except httpx.HTTPError as exc:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise MediaSecurityError("media_download_failed") from exc

