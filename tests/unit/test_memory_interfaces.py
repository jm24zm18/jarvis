from jarvis.memory.factory import (
    resolve_compactor,
    resolve_embedder,
    resolve_memory_store,
    resolve_retriever,
)


def test_memory_factory_returns_default_service_interfaces() -> None:
    store = resolve_memory_store()
    retriever = resolve_retriever()
    embedder = resolve_embedder()
    compactor = resolve_compactor()

    assert hasattr(store, "write")
    assert hasattr(retriever, "search")
    assert hasattr(embedder, "embed_text")
    assert hasattr(compactor, "compact_thread")
