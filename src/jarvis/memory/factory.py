"""Memory service factory for default and swappable implementations."""

from __future__ import annotations

from jarvis.memory.interfaces import ICompactor, IEmbedder, IMemoryStore, IRetriever
from jarvis.memory.service import MemoryService


def default_memory_service() -> MemoryService:
    return MemoryService()


def resolve_memory_store() -> IMemoryStore:
    return default_memory_service()


def resolve_retriever() -> IRetriever:
    return default_memory_service()


def resolve_embedder() -> IEmbedder:
    return default_memory_service()


def resolve_compactor() -> ICompactor:
    return default_memory_service()
