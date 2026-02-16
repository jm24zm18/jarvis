"""Memory browser API routes."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from jarvis.auth.dependencies import UserContext, require_auth
from jarvis.db.connection import get_conn
from jarvis.memory.knowledge import KnowledgeBaseService
from jarvis.memory.service import MemoryService

router = APIRouter(prefix="/memory", tags=["api-memory"])


class KbUpsertInput(BaseModel):
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)


@router.get("")
def search_memory(
    ctx: UserContext = Depends(require_auth),
    q: str = "",
    thread_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    service = MemoryService()
    with get_conn() as conn:
        if thread_id:
            owner = conn.execute(
                "SELECT user_id FROM threads WHERE id=? LIMIT 1", (thread_id,)
            ).fetchone()
            if owner is None:
                return {"items": []}
            if not ctx.is_admin and str(owner["user_id"]) != ctx.user_id:
                return {"items": []}
            items = service.search(conn, thread_id=thread_id, limit=limit, query=q or None)
            return {"items": items}

        if q.strip() and not ctx.is_admin:
            rows = conn.execute(
                (
                    "SELECT mi.id, mi.thread_id, mi.text, mi.created_at "
                    "FROM memory_fts mf JOIN memory_items mi ON mi.id=mf.memory_id "
                    "JOIN threads t ON t.id=mi.thread_id "
                    "WHERE memory_fts MATCH ? AND t.user_id=? "
                    "ORDER BY mi.created_at DESC LIMIT ?"
                ),
                (q, ctx.user_id, limit),
            ).fetchall()
        elif q.strip():
            rows = conn.execute(
                (
                    "SELECT mi.id, mi.thread_id, mi.text, mi.created_at "
                    "FROM memory_fts mf JOIN memory_items mi ON mi.id=mf.memory_id "
                    "WHERE memory_fts MATCH ? ORDER BY mi.created_at DESC LIMIT ?"
                ),
                (q, limit),
            ).fetchall()
        elif not ctx.is_admin:
            rows = conn.execute(
                (
                    "SELECT mi.id, mi.thread_id, mi.text, mi.created_at "
                    "FROM memory_items mi JOIN threads t ON t.id=mi.thread_id "
                    "WHERE t.user_id=? "
                    "ORDER BY mi.created_at DESC LIMIT ?"
                ),
                (ctx.user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                (
                    "SELECT id, thread_id, text, created_at FROM memory_items "
                    "ORDER BY created_at DESC LIMIT ?"
                ),
                (limit,),
            ).fetchall()
        items = [
            {
                "id": str(row["id"]),
                "thread_id": str(row["thread_id"]),
                "text": str(row["text"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
        return {"items": items}


@router.get("/stats")
def memory_stats(ctx: UserContext = Depends(require_auth)) -> dict[str, int]:
    with get_conn() as conn:
        if ctx.is_admin:
            total = conn.execute("SELECT COUNT(*) AS n FROM memory_items").fetchone()
            embedded = conn.execute("SELECT COUNT(*) AS n FROM memory_embeddings").fetchone()
        else:
            total = conn.execute(
                "SELECT COUNT(*) AS n "
                "FROM memory_items mi JOIN threads t ON t.id=mi.thread_id "
                "WHERE t.user_id=?",
                (ctx.user_id,),
            ).fetchone()
            embedded = conn.execute(
                "SELECT COUNT(*) AS n "
                "FROM memory_embeddings me "
                "JOIN memory_items mi ON mi.id=me.memory_id "
                "JOIN threads t ON t.id=mi.thread_id "
                "WHERE t.user_id=?",
                (ctx.user_id,),
            ).fetchone()
    total_n = int(total["n"]) if total is not None else 0
    embedded_n = int(embedded["n"]) if embedded is not None else 0
    return {
        "total_items": total_n,
        "embedded_items": embedded_n,
        "embedding_coverage_pct": int((embedded_n * 100 / total_n) if total_n else 0),
    }


@router.get("/kb")
def search_kb(
    ctx: UserContext = Depends(require_auth),
    q: str = "",
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    del ctx
    kb = KnowledgeBaseService()
    with get_conn() as conn:
        if q.strip():
            items = kb.search(conn, query=q, limit=limit)
        else:
            items = kb.list_docs(conn, limit=limit)
    return {"items": items}


@router.post("/kb")
def upsert_kb(
    payload: KbUpsertInput,
    ctx: UserContext = Depends(require_auth),
) -> dict[str, str]:
    del ctx
    kb = KnowledgeBaseService()
    with get_conn() as conn:
        saved = kb.put(conn, title=payload.title, content=payload.content, tags=payload.tags)
    return saved
