"""Media storage providers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from jarvis.channels.whatsapp.media_security import (
    ensure_media_root,
    resolve_media_output_path,
)
from jarvis.config import get_settings


@runtime_checkable
class StorageProvider(Protocol):
    def save(self, data: bytes, relative_name: str) -> Path:
        ...

    def resolve(self, relative_name: str) -> Path:
        ...


class LocalDiskProvider:
    """Saves files to MEDIA_STORAGE_DIR, reusing WhatsApp path-safety logic."""

    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = base_dir or get_settings().media_storage_dir

    @property
    def root(self) -> Path:
        return ensure_media_root(self._base_dir)

    def save(self, data: bytes, relative_name: str) -> Path:
        target = resolve_media_output_path(self.root, relative_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def resolve(self, relative_name: str) -> Path:
        return resolve_media_output_path(self.root, relative_name)
