"""Memory storage and retrieval service."""

import json
import logging
import sqlite3
from datetime import UTC, datetime
from hashlib import sha256
from math import sqrt
from random import Random
from typing import Any

import httpx

from jarvis.config import get_settings
from jarvis.ids import new_id
from jarvis.memory.policy import apply_memory_policy
from jarvis.memory.state_store import StateStore

logger = logging.getLogger(__name__)


class MemoryService:
    MEMORY_VEC_INDEX_TABLE = "memory_vec_index"
    MEMORY_VEC_INDEX_MAP_TABLE = "memory_vec_index_map"
    EVENT_VEC_INDEX_TABLE = "event_vec_index"
    EVENT_VEC_INDEX_MAP_TABLE = "event_vec_index_map"
    BACKFILL_BATCH_SIZE = 200
    DEFAULT_CHUNK_SIZE = 8192

    def _emit_memory_event(
        self,
        conn: sqlite3.Connection,
        event_type: str,
        payload: dict[str, object],
        thread_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        event_trace = trace_id or new_id("trc")
        serialized = json.dumps(payload, sort_keys=True)
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                new_id("evt"),
                event_trace,
                new_id("spn"),
                None,
                thread_id,
                event_type,
                "memory",
                "system",
                "memory",
                serialized,
                serialized,
                datetime.now(UTC).isoformat(),
            ),
        )

    def ensure_vector_indexes(self, conn: sqlite3.Connection) -> bool:
        return self._ensure_vec_runtime(conn)

    @staticmethod
    def _fts_query(text: str) -> str:
        tokens = [token.strip() for token in text.replace('"', " ").split() if token.strip()]
        if not tokens:
            return ""
        return " OR ".join(tokens[:8])

    def write(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        text: str,
        metadata: dict[str, object] | None = None,
    ) -> str:
        settings = get_settings()
        actor_id = "system"
        if metadata and isinstance(metadata.get("actor_id"), str):
            actor_id = str(metadata["actor_id"])
        governed_text, decision, reason = apply_memory_policy(
            conn,
            text=text,
            thread_id=thread_id,
            actor_id=actor_id,
            target_kind="memory_item",
        )
        memory_id = new_id("mem")
        metadata_json = json.dumps(metadata or {})
        conn.execute(
            (
                "INSERT INTO memory_items("
                "id, thread_id, text, metadata_json, created_at"
                ") VALUES(?,?,?,?,?)"
            ),
            (memory_id, thread_id, governed_text, metadata_json, datetime.now(UTC).isoformat()),
        )
        conn.execute(
            "INSERT INTO memory_fts(memory_id, thread_id, text) VALUES(?,?,?)",
            (memory_id, thread_id, governed_text),
        )
        vector = self._embed_text_cached(conn, governed_text)
        vec_json = json.dumps(vector)
        conn.execute(
            (
                "INSERT OR REPLACE INTO memory_embeddings("
                "memory_id, model, vector_json, created_at"
                ") VALUES(?,?,?,?)"
            ),
            (
                memory_id,
                settings.ollama_embed_model,
                vec_json,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO memory_vec(memory_id, vector_json, created_at) VALUES(?,?,?)",
            (memory_id, vec_json, datetime.now(UTC).isoformat()),
        )
        self._upsert_memory_vec_index(conn, memory_id, vector)
        self._emit_memory_event(
            conn,
            "memory.write",
            {
                "memory_id": memory_id,
                "chars": len(governed_text),
                "policy_decision": decision,
                "policy_reason": reason,
            },
            thread_id=thread_id,
        )
        return memory_id

    def write_chunked(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        text: str,
        metadata: dict[str, object] | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> list[str]:
        chunk_len = max(1, int(chunk_size))
        content = str(text)
        if len(content) <= chunk_len:
            return [self.write(conn, thread_id, content, metadata=metadata)]

        chunk_group_id = f"mcg_{sha256(content.encode('utf-8')).hexdigest()[:24]}"
        pieces = [content[idx: idx + chunk_len] for idx in range(0, len(content), chunk_len)]
        chunk_total = len(pieces)
        memory_ids: list[str] = []
        base_metadata = dict(metadata or {})
        for chunk_idx, piece in enumerate(pieces):
            chunk_metadata: dict[str, object] = dict(base_metadata)
            chunk_metadata.update(
                {
                    "is_chunked": True,
                    "chunk_group_id": chunk_group_id,
                    "chunk_index": chunk_idx,
                    "chunk_total": chunk_total,
                    "continued": chunk_idx < (chunk_total - 1),
                }
            )
            memory_ids.append(
                self.write(conn, thread_id, piece, metadata=chunk_metadata)
            )
        return memory_ids

    def embed_text(self, text: str) -> list[float]:
        return self._embed_text(text)

    def _embed_text_cached(self, conn: sqlite3.Connection, text: str) -> list[float]:
        settings = get_settings()
        model = settings.ollama_embed_model
        key = sha256(f"{model}\n{text.strip()}".encode()).hexdigest()
        row = conn.execute(
            "SELECT vector_json FROM embedding_cache WHERE hash=? LIMIT 1",
            (key,),
        ).fetchone()
        if row is not None and isinstance(row["vector_json"], str):
            try:
                decoded = json.loads(str(row["vector_json"]))
                if isinstance(decoded, list):
                    vec = [float(item) for item in decoded if isinstance(item, int | float)]
                    if vec:
                        conn.execute(
                            "UPDATE embedding_cache SET hit_count=hit_count+1 WHERE hash=?",
                            (key,),
                        )
                        return self._fit_dims(vec, settings.memory_embed_dims)
            except json.JSONDecodeError:
                pass
        vector = self._embed_text(text)
        conn.execute(
            (
                "INSERT OR REPLACE INTO embedding_cache("
                "hash, model, vector_json, created_at, hit_count"
                ") "
                "VALUES(?,?,?,?,COALESCE((SELECT hit_count FROM embedding_cache WHERE hash=?), 0))"
            ),
            (key, model, json.dumps(vector), datetime.now(UTC).isoformat(), key),
        )
        return vector

    def upsert_event_vector(
        self,
        conn: sqlite3.Connection,
        event_id: str,
        thread_id: str | None,
        embedding: list[float],
    ) -> None:
        conn.execute(
            (
                "INSERT OR REPLACE INTO event_vec("
                "id, thread_id, vector_json, created_at"
                ") VALUES(?,?,?,?)"
            ),
            (
                event_id,
                thread_id,
                json.dumps(embedding),
                datetime.now(UTC).isoformat(),
            ),
        )
        self._upsert_event_vec_index(conn, event_id, thread_id, embedding)

    def search(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        limit: int = 5,
        query: str | None = None,
        vector_weight: float = 0.4,
        bm25_weight: float = 0.35,
        recency_weight: float = 0.25,
    ) -> list[dict[str, object]]:
        """Hybrid retrieval using Reciprocal Rank Fusion (vector + BM25 + recency)."""
        rrf_k = 60  # RRF smoothing constant
        pool_size = max(limit * 3, 15)

        # --- Vector ranking ---
        vector_ranking: list[str] = []
        vector_texts: dict[str, str] = {}
        if query and query.strip():
            semantic = self._semantic_scored(conn, thread_id, query, pool_size)
            if semantic:
                sorted_items = sorted(semantic.items(), key=lambda kv: kv[1][0], reverse=True)
                for mid, (_, text) in sorted_items:
                    vector_ranking.append(mid)
                    vector_texts[mid] = text

        # --- BM25 ranking ---
        bm25_ranking: list[str] = []
        bm25_texts: dict[str, str] = {}
        if query and query.strip():
            fts_query = self._fts_query(query)
            if fts_query:
                try:
                    rows = conn.execute(
                        (
                            "SELECT memory_id AS id, text FROM memory_fts "
                            "WHERE thread_id=? AND memory_fts MATCH ? "
                            "ORDER BY bm25(memory_fts) LIMIT ?"
                        ),
                        (thread_id, fts_query, pool_size),
                    ).fetchall()
                    for r in rows:
                        mid = str(r["id"])
                        bm25_ranking.append(mid)
                        bm25_texts[mid] = str(r["text"])
                except sqlite3.OperationalError:
                    logger.debug("memory_fts query failed", exc_info=True)

        # --- Recency ranking ---
        recent_rows = conn.execute(
            "SELECT id, text, created_at FROM memory_items "
            "WHERE thread_id=? ORDER BY created_at DESC LIMIT ?",
            (thread_id, pool_size),
        ).fetchall()
        recency_ranking: list[str] = []
        recency_texts: dict[str, str] = {}
        for row in recent_rows:
            mid = str(row["id"])
            recency_ranking.append(mid)
            recency_texts[mid] = str(row["text"])

        # If no results from any source, return empty
        if not vector_ranking and not bm25_ranking and not recency_ranking:
            self._emit_memory_event(
                conn,
                "memory.retrieve",
                {"result_count": 0, "query_present": bool(query and query.strip())},
                thread_id=thread_id,
            )
            return []

        # --- Reciprocal Rank Fusion ---
        rrf_scores: dict[str, float] = {}
        all_texts: dict[str, str] = {}
        all_texts.update(recency_texts)
        all_texts.update(bm25_texts)
        all_texts.update(vector_texts)

        for rank, mid in enumerate(vector_ranking):
            rrf_scores[mid] = rrf_scores.get(mid, 0.0) + vector_weight / (rrf_k + rank + 1)

        for rank, mid in enumerate(bm25_ranking):
            rrf_scores[mid] = rrf_scores.get(mid, 0.0) + bm25_weight / (rrf_k + rank + 1)

        for rank, mid in enumerate(recency_ranking):
            rrf_scores[mid] = rrf_scores.get(mid, 0.0) + recency_weight / (rrf_k + rank + 1)

        # Sort by fused score
        ranked = sorted(rrf_scores.items(), key=lambda kv: kv[1], reverse=True)
        results: list[dict[str, object]] = []
        seen: set[str] = set()
        for mid, _ in ranked:
            stitched_id, stitched_text, stitched_metadata = self._materialize_memory_hit(
                conn,
                thread_id=thread_id,
                memory_id=mid,
                fallback_text=all_texts.get(mid, ""),
            )
            if stitched_id in seen:
                continue
            seen.add(stitched_id)
            results.append(
                {"id": stitched_id, "text": stitched_text, "metadata": stitched_metadata}
            )
            if len(results) >= limit:
                break
        self._emit_memory_event(
            conn,
            "memory.retrieve",
            {
                "result_count": len(results),
                "query_present": bool(query and query.strip()),
                "limit": limit,
            },
            thread_id=thread_id,
        )
        return results

    @staticmethod
    def _parse_metadata(metadata_raw: object) -> dict[str, object]:
        if not isinstance(metadata_raw, str) or not metadata_raw:
            return {}
        try:
            parsed = json.loads(metadata_raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _materialize_memory_hit(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        memory_id: str,
        fallback_text: str,
    ) -> tuple[str, str, dict[str, object]]:
        row = conn.execute(
            "SELECT id, text, metadata_json FROM memory_items WHERE id=? LIMIT 1",
            (memory_id,),
        ).fetchone()
        if row is None:
            return memory_id, fallback_text, {}
        metadata = self._parse_metadata(row["metadata_json"])
        group_id = metadata.get("chunk_group_id")
        if not isinstance(group_id, str) or not group_id.strip():
            return str(row["id"]), str(row["text"]), metadata
        try:
            chunk_rows = conn.execute(
                (
                    "SELECT id, text, metadata_json, created_at "
                    "FROM memory_items "
                    "WHERE thread_id=? AND json_extract(metadata_json, '$.chunk_group_id')=? "
                    "ORDER BY CAST(json_extract(metadata_json, '$.chunk_index') AS INTEGER) ASC, "
                    "created_at ASC"
                ),
                (thread_id, group_id),
            ).fetchall()
        except sqlite3.OperationalError:
            return str(row["id"]), str(row["text"]), metadata
        if not chunk_rows:
            return str(row["id"]), str(row["text"]), metadata
        ordered = []
        for chunk_row in chunk_rows:
            chunk_metadata = self._parse_metadata(chunk_row["metadata_json"])
            chunk_index_raw = chunk_metadata.get("chunk_index", 0)
            if isinstance(chunk_index_raw, int | float | str):
                try:
                    chunk_index = int(chunk_index_raw)
                except ValueError:
                    chunk_index = 0
            else:
                chunk_index = 0
            ordered.append(
                (chunk_index, str(chunk_row["id"]), str(chunk_row["text"]), chunk_metadata)
            )
        ordered.sort(key=lambda item: item[0])
        stitched = "".join(item[2] for item in ordered)
        primary = ordered[0]
        return primary[1], stitched, primary[3]

    def _semantic_scored(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        query: str,
        limit: int,
    ) -> dict[str, tuple[float, str]]:
        """Return {memory_id: (cosine_score, text)} for semantic search."""
        query_vec = self._normalize(self._embed_text(query))
        # Try sqlite-vec index first
        sqlite_vec = self._search_memory_vec_index(conn, thread_id, query_vec, limit)
        if sqlite_vec:
            # sqlite-vec doesn't return scores, assign rank-based scores
            result: dict[str, tuple[float, str]] = {}
            for idx, item in enumerate(sqlite_vec):
                score = 1.0 - (idx / max(len(sqlite_vec), 1))
                result[item["id"]] = (score, item["text"])
            return result

        # Fallback: brute-force cosine similarity
        rows = conn.execute(
            (
                "SELECT m.id, m.text, me.vector_json "
                "FROM memory_items m "
                "JOIN memory_embeddings me ON me.memory_id=m.id "
                "WHERE m.thread_id=?"
            ),
            (thread_id,),
        ).fetchall()
        scored: dict[str, tuple[float, str]] = {}
        for row in rows:
            raw_vec = row["vector_json"]
            if not isinstance(raw_vec, str):
                continue
            try:
                decoded = json.loads(raw_vec)
            except json.JSONDecodeError:
                continue
            if not isinstance(decoded, list):
                continue
            vec = [float(item) for item in decoded if isinstance(item, int | float)]
            if not vec:
                continue
            score = self._cosine(query_vec, self._normalize(vec))
            scored[str(row["id"])] = (score, str(row["text"]))
        return scored

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        length = sqrt(sum(item * item for item in vector))
        if length == 0:
            return vector
        return [item / length for item in vector]

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        size = min(len(left), len(right))
        return sum(left[idx] * right[idx] for idx in range(size))

    def _semantic_search(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        query: str,
        limit: int,
    ) -> list[dict[str, str]]:
        query_vec = self._normalize(self._embed_text(query))
        sqlite_vec = self._search_memory_vec_index(conn, thread_id, query_vec, limit)
        if sqlite_vec:
            return sqlite_vec
        rows = conn.execute(
            (
                "SELECT m.id, m.text, me.vector_json "
                "FROM memory_items m "
                "JOIN memory_embeddings me ON me.memory_id=m.id "
                "WHERE m.thread_id=?"
            ),
            (thread_id,),
        ).fetchall()
        scored: list[tuple[float, str, str]] = []
        for row in rows:
            raw_vec = row["vector_json"]
            if not isinstance(raw_vec, str):
                continue
            try:
                decoded = json.loads(raw_vec)
            except json.JSONDecodeError:
                continue
            if not isinstance(decoded, list):
                continue
            vec = [float(item) for item in decoded if isinstance(item, int | float)]
            if not vec:
                continue
            score = self._cosine(query_vec, self._normalize(vec))
            scored.append((score, str(row["id"]), str(row["text"])))
        if not scored:
            return []
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{"id": mid, "text": text} for _, mid, text in scored[:limit]]

    def search_events(
        self,
        conn: sqlite3.Connection,
        query: str,
        limit: int = 20,
        thread_id: str | None = None,
    ) -> list[dict[str, str]]:
        if not query.strip():
            return []
        query_vec = self._normalize(self._embed_text(query))
        sqlite_vec = self._search_event_vec_index(conn, query_vec, limit=limit, thread_id=thread_id)
        if sqlite_vec:
            return sqlite_vec
        if thread_id:
            rows = conn.execute(
                (
                    "SELECT e.id, e.event_type, e.component, e.created_at, et.redacted_text, "
                    "ev.vector_json "
                    "FROM event_vec ev "
                    "JOIN events e ON e.id=ev.id "
                    "JOIN event_text et ON et.event_id=e.id "
                    "WHERE e.thread_id=?"
                ),
                (thread_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT e.id, e.event_type, e.component, e.created_at, et.redacted_text, "
                "ev.vector_json "
                "FROM event_vec ev "
                "JOIN events e ON e.id=ev.id "
                "JOIN event_text et ON et.event_id=e.id"
            ).fetchall()
        scored: list[tuple[float, dict[str, str]]] = []
        for row in rows:
            raw_vec = row["vector_json"]
            if not isinstance(raw_vec, str):
                continue
            try:
                decoded = json.loads(raw_vec)
            except json.JSONDecodeError:
                continue
            if not isinstance(decoded, list):
                continue
            vec = [float(item) for item in decoded if isinstance(item, int | float)]
            if not vec:
                continue
            score = self._cosine(query_vec, self._normalize(vec))
            scored.append(
                (
                    score,
                    {
                        "event_id": str(row["id"]),
                        "event_type": str(row["event_type"]),
                        "component": str(row["component"]),
                        "created_at": str(row["created_at"]),
                        "redacted_text": str(row["redacted_text"]),
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def _search_memory_vec_index(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        query_vec: list[float],
        limit: int,
    ) -> list[dict[str, str]]:
        if not self._ensure_vec_runtime(conn):
            return []
        try:
            rows = conn.execute(
                (
                    f"SELECT m.memory_id AS id, mi.text AS text "
                    f"FROM {self.MEMORY_VEC_INDEX_TABLE} idx "
                    f"JOIN {self.MEMORY_VEC_INDEX_MAP_TABLE} m ON m.vec_rowid=idx.rowid "
                    "JOIN memory_items mi ON mi.id=m.memory_id "
                    "WHERE idx.embedding MATCH ? AND k = ? AND mi.thread_id=?"
                ),
                (json.dumps(query_vec), limit, thread_id),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.debug(
                "memory vector index search failed; falling back to brute force",
                exc_info=True,
            )
            return []
        return [{"id": str(r["id"]), "text": str(r["text"])} for r in rows]

    def _search_event_vec_index(
        self,
        conn: sqlite3.Connection,
        query_vec: list[float],
        limit: int,
        thread_id: str | None = None,
    ) -> list[dict[str, str]]:
        if not self._ensure_vec_runtime(conn):
            return []
        try:
            if thread_id is None:
                rows = conn.execute(
                    (
                        f"SELECT e.id, e.event_type, e.component, e.created_at, et.redacted_text "
                        f"FROM {self.EVENT_VEC_INDEX_TABLE} idx "
                        f"JOIN {self.EVENT_VEC_INDEX_MAP_TABLE} m ON m.vec_rowid=idx.rowid "
                        "JOIN events e ON e.id=m.event_id "
                        "JOIN event_text et ON et.event_id=e.id "
                        "WHERE idx.embedding MATCH ? AND k = ?"
                    ),
                    (json.dumps(query_vec), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    (
                        f"SELECT e.id, e.event_type, e.component, e.created_at, et.redacted_text "
                        f"FROM {self.EVENT_VEC_INDEX_TABLE} idx "
                        f"JOIN {self.EVENT_VEC_INDEX_MAP_TABLE} m ON m.vec_rowid=idx.rowid "
                        "JOIN events e ON e.id=m.event_id "
                        "JOIN event_text et ON et.event_id=e.id "
                        "WHERE idx.embedding MATCH ? AND k = ? AND m.thread_id=?"
                    ),
                    (json.dumps(query_vec), limit, thread_id),
                ).fetchall()
        except sqlite3.OperationalError:
            logger.debug(
                "event vector index search failed; falling back to brute force",
                exc_info=True,
            )
            return []
        return [
            {
                "event_id": str(row["id"]),
                "event_type": str(row["event_type"]),
                "component": str(row["component"]),
                "created_at": str(row["created_at"]),
                "redacted_text": str(row["redacted_text"]),
            }
            for row in rows
        ]

    def _embed_text(self, text: str) -> list[float]:
        settings = get_settings()
        base_url = settings.ollama_base_url.rstrip("/")
        payload = {"model": settings.ollama_embed_model, "prompt": text}
        try:
            with httpx.Client(timeout=8) as client:
                response = client.post(f"{base_url}/api/embeddings", json=payload)
                response.raise_for_status()
            body = response.json()
            embedding = body.get("embedding")
            if isinstance(embedding, list) and embedding:
                parsed = [float(item) for item in embedding if isinstance(item, int | float)]
                return self._fit_dims(parsed, settings.memory_embed_dims)
        except Exception:
            pass
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(settings.memory_sentence_transformers_model)
            output = model.encode([text], normalize_embeddings=False)
            if len(output) > 0:
                first = output[0]
                if hasattr(first, "tolist"):
                    parsed = [float(item) for item in first.tolist()]
                else:
                    parsed = [float(item) for item in first]
                return self._fit_dims(parsed, settings.memory_embed_dims)
        except Exception:
            pass
        return self._deterministic_embedding(text, settings.memory_embed_dims)

    def search_state(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        k: int = 20,
        min_score: float = 0.75,
        actor_id: str = "main",
    ) -> list[dict[str, object]]:
        if not query.strip():
            return []
        store = StateStore()
        max_k = max(1, int(k))
        pool_size = max(max_k * 3, 20)
        rrf_k = 60
        flt = filters or {}
        desired_type = str(flt.get("type_tag") or "decision")
        allowed_tiers = {
            str(item)
            for item in (flt.get("tiers") or [])
            if isinstance(item, str) and item.strip()
        }

        vector_rows = store.search_similar_items(
            conn=conn,
            thread_id=thread_id,
            embedding=self._embed_text_cached(conn, query),
            type_tag=desired_type,
            limit=pool_size,
        )
        vector_rank: list[str] = []
        rows_by_uid: dict[str, dict[str, object]] = {}
        for row in vector_rows:
            uid = str(row.get("uid", ""))
            if not uid:
                continue
            vector_rank.append(uid)
            rows_by_uid[uid] = dict(row)

        lexical_rows = conn.execute(
            (
                "SELECT uid, text, status, type_tag, topic_tags_json, confidence, tier, "
                "importance_score, last_seen_at "
                "FROM state_items WHERE thread_id=? AND status!='superseded' "
                "AND LOWER(text) LIKE ? ORDER BY updated_at DESC LIMIT ?"
            ),
            (thread_id, f"%{query.strip().lower()}%", pool_size),
        ).fetchall()
        lexical_rank: list[str] = []
        for row in lexical_rows:
            uid = str(row["uid"])
            lexical_rank.append(uid)
            rows_by_uid.setdefault(
                uid,
                {
                    "uid": uid,
                    "text": str(row["text"]),
                    "status": str(row["status"]),
                    "type_tag": str(row["type_tag"]),
                    "topic_tags": [],
                    "score": 0.0,
                    "tier": str(row["tier"]),
                    "importance_score": float(row["importance_score"] or 0.0),
                    "last_seen_at": str(row["last_seen_at"]),
                    "confidence": str(row["confidence"]),
                },
            )

        recent_rows = conn.execute(
            (
                "SELECT uid, text, status, type_tag, topic_tags_json, confidence, tier, "
                "importance_score, last_seen_at "
                "FROM state_items WHERE thread_id=? AND status!='superseded' "
                "ORDER BY last_seen_at DESC LIMIT ?"
            ),
            (thread_id, pool_size),
        ).fetchall()
        recency_rank: list[str] = []
        for row in recent_rows:
            uid = str(row["uid"])
            recency_rank.append(uid)
            rows_by_uid.setdefault(
                uid,
                {
                    "uid": uid,
                    "text": str(row["text"]),
                    "status": str(row["status"]),
                    "type_tag": str(row["type_tag"]),
                    "topic_tags": [],
                    "score": 0.0,
                    "tier": str(row["tier"]),
                    "importance_score": float(row["importance_score"] or 0.0),
                    "last_seen_at": str(row["last_seen_at"]),
                    "confidence": str(row["confidence"]),
                },
            )

        if not (vector_rank or lexical_rank or recency_rank):
            return []
        scores: dict[str, float] = {}
        for idx, uid in enumerate(vector_rank):
            scores[uid] = scores.get(uid, 0.0) + 0.50 / (rrf_k + idx + 1)
        for idx, uid in enumerate(lexical_rank):
            scores[uid] = scores.get(uid, 0.0) + 0.30 / (rrf_k + idx + 1)
        for idx, uid in enumerate(recency_rank):
            scores[uid] = scores.get(uid, 0.0) + 0.20 / (rrf_k + idx + 1)

        tier_prior = {
            "working": 0.040,
            "episodic": 0.025,
            "semantic_longterm": 0.010,
            "procedural": 0.010,
        }
        tier_rank = {
            "working": 3,
            "episodic": 2,
            "semantic_longterm": 1,
            "procedural": 1,
        }

        filtered: list[dict[str, object]] = []
        for uid, base_score in scores.items():
            row = dict(rows_by_uid.get(uid, {}))
            if not row:
                continue
            if row.get("type_tag") != desired_type:
                continue
            tier = str(row.get("tier") or "working")
            if allowed_tiers and tier not in allowed_tiers:
                continue
            prior = tier_prior.get(tier, 0.0)
            combined = base_score + prior
            if combined < min_score * 0.05:
                continue
            row["score"] = combined
            row["agent_id"] = actor_id
            filtered.append(row)
        def _recency_sort_value(value: object) -> float:
            try:
                return datetime.fromisoformat(str(value)).timestamp()
            except Exception:
                return 0.0

        def _score_sort_value(value: object) -> float:
            if isinstance(value, int | float):
                return float(value)
            try:
                return float(str(value))
            except Exception:
                return 0.0

        filtered.sort(
            key=lambda row: (
                -_score_sort_value(row.get("score")),
                -tier_rank.get(str(row.get("tier") or "working"), 0),
                -_recency_sort_value(row.get("last_seen_at")),
                str(row.get("uid") or ""),
            )
        )
        filtered = filtered[:max_k]
        self._emit_memory_event(
            conn,
            "memory.search.executed",
            {
                "scope": "state",
                "result_count": len(filtered),
                "query": query[:120],
                "filters": filters or {},
            },
            thread_id=thread_id,
        )
        return filtered

    def get_failures(
        self,
        conn: sqlite3.Connection,
        *,
        similar_to: str,
        k: int = 10,
        actor_id: str = "main",
    ) -> list[dict[str, object]]:
        del actor_id
        text = similar_to.strip().lower()
        if not text:
            rows = conn.execute(
                (
                    "SELECT id, trace_id, phase, error_summary, error_details_json, "
                    "attempt, created_at "
                    "FROM failure_capsules ORDER BY created_at DESC LIMIT ?"
                ),
                (max(1, int(k)),),
            ).fetchall()
        else:
            rows = conn.execute(
                (
                    "SELECT id, trace_id, phase, error_summary, error_details_json, "
                    "attempt, created_at "
                    "FROM failure_capsules WHERE LOWER(error_summary) LIKE ? "
                    "ORDER BY created_at DESC LIMIT ?"
                ),
                (f"%{text}%", max(1, int(k))),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "trace_id": str(row["trace_id"]),
                "phase": str(row["phase"]),
                "summary": str(row["error_summary"]),
                "details_json": str(row["error_details_json"]),
                "attempt": int(row["attempt"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def graph_traverse(
        self,
        conn: sqlite3.Connection,
        *,
        uid: str,
        depth: int = 2,
        relation_types: list[str] | None = None,
        actor_id: str = "main",
    ) -> dict[str, object]:
        del actor_id
        max_depth = max(1, min(5, int(depth)))
        rel_filter = ""
        params: list[object] = [uid, max_depth]
        if relation_types:
            placeholders = ",".join("?" for _ in relation_types)
            rel_filter = f"AND sr.relation_type IN ({placeholders})"
            params.extend(relation_types)
        rows = conn.execute(
            (
                "WITH RECURSIVE walk(source_uid, target_uid, relation_type, depth) AS ("
                "  SELECT sr.source_uid, sr.target_uid, sr.relation_type, 1 "
                "  FROM state_relations sr WHERE sr.source_uid=? "
                "  UNION ALL "
                "  SELECT sr.source_uid, sr.target_uid, sr.relation_type, w.depth + 1 "
                "  FROM state_relations sr JOIN walk w ON sr.source_uid=w.target_uid "
                "  WHERE w.depth < ? "
                f"  {rel_filter}"
                ") "
                "SELECT source_uid, target_uid, relation_type, depth FROM walk"
            ),
            tuple(params),
        ).fetchall()
        edges = [
            {
                "source_uid": str(row["source_uid"]),
                "target_uid": str(row["target_uid"]),
                "relation_type": str(row["relation_type"]),
                "depth": int(row["depth"]),
            }
            for row in rows
        ]
        nodes: set[str] = {uid}
        for edge in edges:
            nodes.add(str(edge["source_uid"]))
            nodes.add(str(edge["target_uid"]))
        return {"root_uid": uid, "nodes": sorted(nodes), "edges": edges}

    def evaluate_consistency(
        self,
        conn: sqlite3.Connection,
        *,
        thread_id: str,
        sample_size: int = 50,
    ) -> dict[str, object]:
        row = conn.execute(
            (
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN conflict=1 THEN 1 ELSE 0 END) AS conflicted "
                "FROM state_items WHERE thread_id=? LIMIT ?"
            ),
            (thread_id, max(1, int(sample_size))),
        ).fetchone()
        total = int(row["total"]) if row is not None else 0
        conflicted = int(row["conflicted"] or 0) if row is not None else 0
        score = 1.0 if total == 0 else max(0.0, 1.0 - (conflicted / total))
        return {
            "thread_id": thread_id,
            "sample_size": max(1, int(sample_size)),
            "total_items": total,
            "conflicted_items": conflicted,
            "consistency_score": score,
        }

    @staticmethod
    def _fit_dims(vector: list[float], dims: int) -> list[float]:
        if dims <= 0:
            return vector
        if len(vector) >= dims:
            return vector[:dims]
        return vector + [0.0] * (dims - len(vector))

    @staticmethod
    def _deterministic_embedding(text: str, dims: int) -> list[float]:
        if dims <= 0:
            return []
        seed = int.from_bytes(sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(dims)]

    @staticmethod
    def _has_vec_module(conn: sqlite3.Connection) -> bool:
        try:
            row = conn.execute(
                "SELECT 1 FROM pragma_module_list WHERE name='vec0' LIMIT 1"
            ).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            return False

    def _ensure_vec_runtime(self, conn: sqlite3.Connection) -> bool:
        settings = get_settings()
        if not self._has_vec_module(conn):
            extension_path = settings.sqlite_vec_extension_path.strip()
            if not extension_path:
                return False
            try:
                conn.enable_load_extension(True)
                conn.load_extension(extension_path)
            except sqlite3.OperationalError:
                logger.debug(
                    "sqlite-vec extension load failed",
                    exc_info=True,
                )
                return False
            finally:
                try:
                    conn.enable_load_extension(False)
                except sqlite3.OperationalError:
                    logger.debug("failed to disable sqlite extension loading", exc_info=True)
            if not self._has_vec_module(conn):
                return False

        dims = max(1, settings.memory_embed_dims)
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {self.MEMORY_VEC_INDEX_TABLE} "
                f"USING vec0(embedding float[{dims}])"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.MEMORY_VEC_INDEX_MAP_TABLE}("
                "vec_rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
                "memory_id TEXT UNIQUE NOT NULL)"
            )
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {self.EVENT_VEC_INDEX_TABLE} "
                f"USING vec0(embedding float[{dims}])"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.EVENT_VEC_INDEX_MAP_TABLE}("
                "vec_rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
                "event_id TEXT UNIQUE NOT NULL, "
                "thread_id TEXT)"
            )
        except sqlite3.OperationalError:
            logger.debug("vector runtime table setup failed", exc_info=True)
            return False
        self._backfill_vec_runtime(conn)
        return True

    def _backfill_vec_runtime(self, conn: sqlite3.Connection) -> None:
        self._backfill_memory_vec_runtime(conn)
        self._backfill_event_vec_runtime(conn)

    def _backfill_memory_vec_runtime(self, conn: sqlite3.Connection) -> None:
        try:
            rows = conn.execute(
                (
                    "SELECT me.memory_id, me.vector_json "
                    "FROM memory_embeddings me "
                    f"LEFT JOIN {self.MEMORY_VEC_INDEX_MAP_TABLE} m "
                    "ON m.memory_id=me.memory_id "
                    "WHERE m.memory_id IS NULL "
                    "ORDER BY me.created_at ASC LIMIT ?"
                ),
                (self.BACKFILL_BATCH_SIZE,),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.debug("memory vector backfill query failed", exc_info=True)
            return
        for row in rows:
            raw = row["vector_json"]
            if not isinstance(raw, str):
                continue
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(decoded, list):
                continue
            embedding = [float(item) for item in decoded if isinstance(item, int | float)]
            if not embedding:
                continue
            self._upsert_memory_vec_index_raw(conn, str(row["memory_id"]), embedding)

    def _backfill_event_vec_runtime(self, conn: sqlite3.Connection) -> None:
        try:
            rows = conn.execute(
                (
                    "SELECT ev.id, ev.thread_id, ev.vector_json "
                    "FROM event_vec ev "
                    f"LEFT JOIN {self.EVENT_VEC_INDEX_MAP_TABLE} m "
                    "ON m.event_id=ev.id "
                    "WHERE m.event_id IS NULL "
                    "ORDER BY ev.created_at ASC LIMIT ?"
                ),
                (self.BACKFILL_BATCH_SIZE,),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.debug("event vector backfill query failed", exc_info=True)
            return
        for row in rows:
            raw = row["vector_json"]
            if not isinstance(raw, str):
                continue
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(decoded, list):
                continue
            embedding = [float(item) for item in decoded if isinstance(item, int | float)]
            if not embedding:
                continue
            thread_id = str(row["thread_id"]) if row["thread_id"] is not None else None
            self._upsert_event_vec_index_raw(conn, str(row["id"]), thread_id, embedding)

    def _upsert_memory_vec_index(
        self, conn: sqlite3.Connection, memory_id: str, embedding: list[float]
    ) -> None:
        if not self._ensure_vec_runtime(conn):
            return
        self._upsert_memory_vec_index_raw(conn, memory_id, embedding)

    def _upsert_memory_vec_index_raw(
        self, conn: sqlite3.Connection, memory_id: str, embedding: list[float]
    ) -> None:
        row = conn.execute(
            f"SELECT vec_rowid FROM {self.MEMORY_VEC_INDEX_MAP_TABLE} WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        if row is None:
            cursor = conn.execute(
                f"INSERT INTO {self.MEMORY_VEC_INDEX_MAP_TABLE}(memory_id) VALUES(?)",
                (memory_id,),
            )
            if cursor.lastrowid is None:
                return
            vec_rowid = int(cursor.lastrowid)
        else:
            vec_rowid = int(row["vec_rowid"])
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO {self.MEMORY_VEC_INDEX_TABLE}(rowid, embedding) "
                "VALUES(?, ?)",
                (vec_rowid, json.dumps(embedding)),
            )
        except sqlite3.OperationalError:
            logger.debug("memory vector upsert failed", exc_info=True)
            return

    def _upsert_event_vec_index(
        self,
        conn: sqlite3.Connection,
        event_id: str,
        thread_id: str | None,
        embedding: list[float],
    ) -> None:
        if not self._ensure_vec_runtime(conn):
            return
        self._upsert_event_vec_index_raw(conn, event_id, thread_id, embedding)

    def _upsert_event_vec_index_raw(
        self,
        conn: sqlite3.Connection,
        event_id: str,
        thread_id: str | None,
        embedding: list[float],
    ) -> None:
        row = conn.execute(
            f"SELECT vec_rowid FROM {self.EVENT_VEC_INDEX_MAP_TABLE} WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            cursor = conn.execute(
                f"INSERT INTO {self.EVENT_VEC_INDEX_MAP_TABLE}(event_id, thread_id) VALUES(?,?)",
                (event_id, thread_id),
            )
            if cursor.lastrowid is None:
                return
            vec_rowid = int(cursor.lastrowid)
        else:
            vec_rowid = int(row["vec_rowid"])
            conn.execute(
                f"UPDATE {self.EVENT_VEC_INDEX_MAP_TABLE} SET thread_id=? WHERE event_id=?",
                (thread_id, event_id),
            )
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO {self.EVENT_VEC_INDEX_TABLE}(rowid, embedding) "
                "VALUES(?, ?)",
                (vec_rowid, json.dumps(embedding)),
            )
        except sqlite3.OperationalError:
            logger.debug("event vector upsert failed", exc_info=True)
            return

    def thread_summary(self, conn: sqlite3.Connection, thread_id: str) -> dict[str, str]:
        row = conn.execute(
            "SELECT short_summary, long_summary FROM thread_summaries WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
        if row is None:
            return {"short": "", "long": ""}
        return {"short": str(row["short_summary"]), "long": str(row["long_summary"])}

    def compact_thread(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        llm_summarize: bool = True,
    ) -> dict[str, str]:
        message_rows = conn.execute(
            (
                "SELECT role, content, created_at FROM messages "
                "WHERE thread_id=? ORDER BY created_at DESC LIMIT 50"
            ),
            (thread_id,),
        ).fetchall()
        recent = [f"{r['role']}: {r['content']}" for r in reversed(message_rows)]

        if llm_summarize:
            short_summary = self._llm_summarize(
                recent, max_sentences=3, label="short"
            )
            long_summary = self._llm_summarize(
                recent, max_sentences=10, label="long"
            )
        else:
            short_summary = "\n".join(recent[-8:])
            long_summary = "\n".join(recent[-25:])

        conn.execute(
            (
                "INSERT INTO thread_summaries(thread_id, short_summary, long_summary, updated_at) "
                "VALUES(?,?,?,?) "
                "ON CONFLICT(thread_id) DO UPDATE SET "
                "short_summary=excluded.short_summary, "
                "long_summary=excluded.long_summary, "
                "updated_at=excluded.updated_at"
            ),
            (thread_id, short_summary, long_summary, datetime.now(UTC).isoformat()),
        )
        self._emit_memory_event(
            conn,
            "memory.compact",
            {"short_chars": len(short_summary), "long_chars": len(long_summary)},
            thread_id=thread_id,
        )
        return {"thread_id": thread_id, "short_chars": str(len(short_summary))}

    def _llm_summarize(
        self,
        messages: list[str],
        max_sentences: int = 5,
        label: str = "summary",
    ) -> str:
        """Use the LLM provider to generate a compressed summary of messages."""
        if not messages:
            return ""
        transcript = "\n".join(messages[-50:])
        prompt = (
            f"Summarize this conversation in at most {max_sentences} sentences. "
            "Preserve key facts, decisions, and action items. "
            "Be concise and factual.\n\n"
            f"{transcript}"
        )
        try:
            settings = get_settings()
            base_url = settings.sglang_base_url.rstrip("/")
            payload = {
                "model": settings.sglang_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.3,
            }
            with httpx.Client(timeout=30) as client:
                response = client.post(f"{base_url}/chat/completions", json=payload)
                response.raise_for_status()
            body = response.json()
            choices = body.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                if content.strip():
                    return str(content.strip())
        except Exception:
            logger.debug("LLM summarization failed for %s; falling back to truncation", label)
        # Fallback: raw message truncation
        limit = 8 if max_sentences <= 3 else 25
        return "\n".join(messages[-limit:])
