"""Memory browser API routes."""

import json
import sqlite3

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from jarvis.auth.dependencies import UserContext, require_admin, require_auth
from jarvis.db.connection import get_conn
from jarvis.memory.knowledge import KnowledgeBaseService
from jarvis.memory.scope import can_agent_access_thread_memory, normalize_agent_id
from jarvis.memory.service import MemoryService
from jarvis.tasks.memory import run_memory_maintenance

router = APIRouter(prefix="/memory", tags=["api-memory"])


class KbUpsertInput(BaseModel):
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)


class ReviewResolveInput(BaseModel):
    resolution: str = Field(min_length=1)


def _parse_metadata(raw: object) -> dict[str, object]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _thread_allowed(conn: sqlite3.Connection, ctx: UserContext, thread_id: str) -> bool:
    owner = conn.execute("SELECT user_id FROM threads WHERE id=? LIMIT 1", (thread_id,)).fetchone()
    if owner is None:
        return False
    return bool(ctx.is_admin or str(owner["user_id"]) == ctx.user_id)


def _resolve_state_agent_scope(
    conn: sqlite3.Connection, *, thread_id: str, agent_id: str
) -> str | None:
    scoped = normalize_agent_id(agent_id)
    allowed, _reason = can_agent_access_thread_memory(conn, thread_id=thread_id, agent_id=scoped)
    if not allowed:
        return None
    return scoped


@router.get("")
def search_memory(
    ctx: UserContext = Depends(require_auth),  # noqa: B008
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
                    "SELECT mi.id, mi.thread_id, mi.text, mi.metadata_json, mi.created_at "
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
                    "SELECT mi.id, mi.thread_id, mi.text, mi.metadata_json, mi.created_at "
                    "FROM memory_fts mf JOIN memory_items mi ON mi.id=mf.memory_id "
                    "WHERE memory_fts MATCH ? ORDER BY mi.created_at DESC LIMIT ?"
                ),
                (q, limit),
            ).fetchall()
        elif not ctx.is_admin:
            rows = conn.execute(
                (
                    "SELECT mi.id, mi.thread_id, mi.text, mi.metadata_json, mi.created_at "
                    "FROM memory_items mi JOIN threads t ON t.id=mi.thread_id "
                    "WHERE t.user_id=? "
                    "ORDER BY mi.created_at DESC LIMIT ?"
                ),
                (ctx.user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                (
                    "SELECT id, thread_id, text, metadata_json, created_at FROM memory_items "
                    "ORDER BY created_at DESC LIMIT ?"
                ),
                (limit,),
            ).fetchall()
        items = [
            {
                "id": str(row["id"]),
                "thread_id": str(row["thread_id"]),
                "text": str(row["text"]),
                "metadata": _parse_metadata(row["metadata_json"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
        return {"items": items}


@router.get("/stats")
def memory_stats(ctx: UserContext = Depends(require_auth)) -> dict[str, int]:  # noqa: B008
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
    ctx: UserContext = Depends(require_auth),  # noqa: B008
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
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, str]:
    del ctx
    kb = KnowledgeBaseService()
    with get_conn() as conn:
        saved = kb.put(conn, title=payload.title, content=payload.content, tags=payload.tags)
    return saved


@router.post("/maintenance/run")
def memory_maintenance_run(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    return run_memory_maintenance()


@router.get("/state/search")
def state_search(
    ctx: UserContext = Depends(require_auth),  # noqa: B008
    thread_id: str = "",
    q: str = "",
    k: int = Query(default=20, ge=1, le=100),
    min_score: float = Query(default=0.75, ge=0.0, le=1.0),
    agent_id: str = Query(default="main", min_length=1, max_length=128),
) -> dict[str, object]:
    if not thread_id.strip() or not q.strip():
        return {"items": []}
    service = MemoryService()
    with get_conn() as conn:
        if not _thread_allowed(conn, ctx, thread_id):
            return {"items": []}
        scoped_agent = _resolve_state_agent_scope(conn, thread_id=thread_id, agent_id=agent_id)
        if scoped_agent is None:
            return {"items": []}
        items = service.search_state(
            conn,
            thread_id=thread_id,
            query=q,
            k=k,
            min_score=min_score,
            actor_id=scoped_agent,
        )
    return {"items": items}


@router.get("/state/failures")
def state_failures(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
    similar_to: str = "",
    k: int = Query(default=10, ge=1, le=100),
) -> dict[str, object]:
    del ctx
    service = MemoryService()
    with get_conn() as conn:
        items = service.get_failures(conn, similar_to=similar_to, k=k)
    return {"items": items}


@router.get("/state/graph/{uid}")
def state_graph(
    uid: str,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
    depth: int = Query(default=2, ge=1, le=5),
    agent_id: str = Query(default="main", min_length=1, max_length=128),
) -> dict[str, object]:
    service = MemoryService()
    with get_conn() as conn:
        row = conn.execute(
            (
                "SELECT thread_id, agent_id FROM state_items "
                "WHERE uid=? ORDER BY updated_at DESC LIMIT 1"
            ),
            (uid,),
        ).fetchone()
        if row is None:
            return {"root_uid": uid, "nodes": [], "edges": []}
        thread_id = str(row["thread_id"])
        if not _thread_allowed(conn, ctx, thread_id):
            return {"root_uid": uid, "nodes": [], "edges": []}
        scoped_agent = _resolve_state_agent_scope(conn, thread_id=thread_id, agent_id=agent_id)
        if scoped_agent is None:
            return {"root_uid": uid, "nodes": [], "edges": []}
        if str(row["agent_id"]) != scoped_agent:
            return {"root_uid": uid, "nodes": [], "edges": []}
        graph = service.graph_traverse(conn, uid=uid, depth=depth)
    return graph


@router.get("/state/review/conflicts")
def state_review_conflicts(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    del ctx
    with get_conn() as conn:
        rows = conn.execute(
            (
                "SELECT id, uid, thread_id, agent_id, reason, status, reviewer_id, "
                "resolution_json, created_at, updated_at FROM memory_review_queue "
                "WHERE status='open' ORDER BY created_at DESC LIMIT ?"
            ),
            (limit,),
        ).fetchall()
    return {
        "items": [
            {
                "id": str(row["id"]),
                "uid": str(row["uid"]),
                "thread_id": str(row["thread_id"]),
                "agent_id": str(row["agent_id"]),
                "reason": str(row["reason"]),
                "status": str(row["status"]),
                "reviewer_id": str(row["reviewer_id"]) if row["reviewer_id"] is not None else None,
                "resolution": (
                    json.loads(str(row["resolution_json"])) if row["resolution_json"] else None
                ),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]
    }


@router.get("/state/stats")
def state_stats(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    with get_conn() as conn:
        tiers = conn.execute(
            "SELECT tier, COUNT(*) AS n FROM state_items "
            "GROUP BY tier ORDER BY n DESC, tier ASC"
        ).fetchall()
        archive_count = 0
        has_archive = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='state_items_archive'"
            ).fetchone()
            is not None
        )
        if has_archive:
            archive_row = conn.execute("SELECT COUNT(*) AS n FROM state_items_archive").fetchone()
            archive_count = int(archive_row["n"]) if archive_row is not None else 0
        open_conflicts = conn.execute(
            "SELECT COUNT(*) AS n FROM memory_review_queue WHERE status='open'"
        ).fetchone()
    return {
        "tiers": [
            {"tier": str(row["tier"]), "count": int(row["n"])}
            for row in tiers
        ],
        "archive_items": archive_count,
        "open_conflicts": int(open_conflicts["n"]) if open_conflicts is not None else 0,
    }


@router.post("/state/review/{uid}/resolve")
def state_review_resolve(
    uid: str,
    payload: ReviewResolveInput,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    with get_conn() as conn:
        now = conn.execute("SELECT datetime('now') AS now").fetchone()
        now_str = str(now["now"]) if now is not None else ""
        conn.execute(
            (
                "UPDATE memory_review_queue SET status='resolved', reviewer_id=?, "
                "resolution_json=?, "
                "updated_at=? WHERE uid=? AND status='open'"
            ),
            (ctx.user_id, json.dumps({"resolution": payload.resolution}), now_str, uid),
        )
    return {"ok": True, "uid": uid}


@router.get("/export")
def memory_export(
    ctx: UserContext = Depends(require_auth),  # noqa: B008
    format: str = "jsonl",
    tier: str = "",
    thread_id: str | None = None,
    agent_id: str = "",
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, object]:
    if format.lower() != "jsonl":
        return {"error": "only jsonl format is supported"}
    with get_conn() as conn:
        scoped_agent: str | None = None
        if thread_id and agent_id.strip():
            scoped_agent = _resolve_state_agent_scope(conn, thread_id=thread_id, agent_id=agent_id)
            if scoped_agent is None:
                return {"items": []}
        elif agent_id.strip():
            scoped_agent = normalize_agent_id(agent_id)
        if thread_id:
            if not _thread_allowed(conn, ctx, thread_id):
                return {"items": []}
            rows = conn.execute(
                (
                    "SELECT uid, thread_id, text, type_tag, status, tier, "
                    "importance_score, created_at "
                    "FROM state_items WHERE thread_id=? "
                    + ("AND tier=? " if tier.strip() else "")
                    + ("AND agent_id=? " if scoped_agent else "")
                    + "ORDER BY created_at DESC LIMIT ?"
                ),
                (
                    (
                        thread_id,
                        tier,
                        scoped_agent,
                        limit,
                    )
                    if tier.strip() and scoped_agent
                    else (
                        thread_id,
                        tier,
                        limit,
                    )
                    if tier.strip()
                    else (
                        thread_id,
                        scoped_agent,
                        limit,
                    )
                    if scoped_agent
                    else (thread_id, limit)
                ),
            ).fetchall()
        elif ctx.is_admin:
            rows = conn.execute(
                (
                    "SELECT uid, thread_id, text, type_tag, status, tier, "
                    "importance_score, created_at "
                    "FROM state_items "
                    + ("WHERE tier=? " if tier.strip() else "")
                    + ("AND agent_id=? " if tier.strip() and scoped_agent else "")
                    + ("WHERE agent_id=? " if (not tier.strip()) and scoped_agent else "")
                    + "ORDER BY created_at DESC LIMIT ?"
                ),
                (
                    (tier, scoped_agent, limit)
                    if tier.strip() and scoped_agent
                    else (tier, limit)
                    if tier.strip()
                    else (scoped_agent, limit)
                    if scoped_agent
                    else (limit,)
                ),
            ).fetchall()
        else:
            rows = conn.execute(
                (
                    "SELECT si.uid, si.thread_id, si.text, si.type_tag, si.status, si.tier, "
                    "si.importance_score, si.created_at "
                    "FROM state_items si JOIN threads t ON t.id=si.thread_id "
                    "WHERE t.user_id=? "
                    + ("AND si.tier=? " if tier.strip() else "")
                    + ("AND si.agent_id=? " if scoped_agent else "")
                    + "ORDER BY si.created_at DESC LIMIT ?"
                ),
                (
                    (ctx.user_id, tier, scoped_agent, limit)
                    if tier.strip() and scoped_agent
                    else (ctx.user_id, tier, limit)
                    if tier.strip()
                    else (ctx.user_id, scoped_agent, limit)
                    if scoped_agent
                    else (ctx.user_id, limit)
                ),
            ).fetchall()
    items = [
        json.dumps(
            {
                "uid": str(row["uid"]),
                "thread_id": str(row["thread_id"]),
                "text": str(row["text"]),
                "type_tag": str(row["type_tag"]),
                "status": str(row["status"]),
                "tier": str(row["tier"]),
                "importance_score": float(row["importance_score"]),
                "created_at": str(row["created_at"]),
            },
            sort_keys=True,
        )
        for row in rows
    ]
    return {"items": items}


@router.get("/state/consistency/report")
def state_consistency_report(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=500),
    thread_id: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> dict[str, object]:
    del ctx
    clauses: list[str] = []
    params: list[object] = []
    if thread_id and thread_id.strip():
        clauses.append("thread_id=?")
        params.append(thread_id.strip())
    if from_ts and from_ts.strip():
        clauses.append("created_at>=?")
        params.append(from_ts.strip())
    if to_ts and to_ts.strip():
        clauses.append("created_at<=?")
        params.append(to_ts.strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_conn() as conn:
        rows = conn.execute(
            (
                "SELECT id, thread_id, sample_size, total_items, conflicted_items, "
                "consistency_score, details_json, created_at "
                f"FROM memory_consistency_reports {where} ORDER BY created_at DESC LIMIT ?"
            ),
            tuple([*params, limit]),
        ).fetchall()
    items: list[dict[str, object]] = [
        {
            "id": str(row["id"]),
            "thread_id": str(row["thread_id"]),
            "sample_size": int(row["sample_size"]),
            "total_items": int(row["total_items"]),
            "conflicted_items": int(row["conflicted_items"]),
            "consistency_score": float(row["consistency_score"]),
            "details": _parse_metadata(row["details_json"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]
    total_score = 0.0
    for item in items:
        raw = item.get("consistency_score")
        if isinstance(raw, int | float | str):
            total_score += float(raw)
    avg = (total_score / len(items)) if items else 1.0
    return {"items": items, "avg_consistency": avg}
