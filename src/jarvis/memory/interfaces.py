"""Protocol interfaces for swappable memory backends."""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol


class IEmbedder(Protocol):
    def embed_text(self, text: str) -> list[float]: ...


class IMemoryPolicy(Protocol):
    def apply(
        self,
        conn: sqlite3.Connection,
        text: str,
        *,
        thread_id: str,
        actor_id: str,
        target_kind: str,
        target_id: str = "",
    ) -> tuple[str, str, str]: ...


class IMemoryStore(Protocol):
    def write(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        text: str,
        metadata: dict[str, object] | None = None,
    ) -> str: ...


class IRetriever(Protocol):
    def search(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        limit: int = 5,
        query: str | None = None,
        vector_weight: float = 0.4,
        bm25_weight: float = 0.35,
        recency_weight: float = 0.25,
    ) -> list[dict[str, Any]]: ...


class ICompactor(Protocol):
    def compact_thread(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        llm_summarize: bool = False,
    ) -> dict[str, str]: ...
