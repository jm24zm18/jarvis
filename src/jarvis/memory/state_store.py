"""Persistence and retrieval layer for structured state items."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from math import sqrt

from jarvis.config import get_settings
from jarvis.ids import new_id
from jarvis.memory.state_items import (
    DEFAULT_STATUS,
    TYPE_PRIORITY,
    StateItem,
    resolve_status_merge,
)

logger = logging.getLogger(__name__)


class StateStore:
    STATE_VEC_INDEX_TABLE = "state_vec_index"
    STATE_VEC_INDEX_MAP_TABLE = "state_vec_index_map"
    BACKFILL_BATCH_SIZE = 200

    @staticmethod
    def _emit_state_event(
        conn: sqlite3.Connection,
        thread_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        encoded = json.dumps(payload, sort_keys=True)
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                new_id("evt"),
                new_id("trc"),
                new_id("spn"),
                None,
                thread_id,
                event_type,
                "memory.state",
                "system",
                "state_store",
                encoded,
                encoded,
                StateStore._now_iso(),
            ),
        )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _confidence_rank(confidence: str) -> int:
        return {"low": 0, "medium": 1, "high": 2}.get(confidence, 1)

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

    def _max_ref_timestamp(self, conn: sqlite3.Connection, refs: list[str]) -> str:
        if not refs:
            return self._now_iso()
        placeholders = ",".join("?" for _ in refs)
        row = conn.execute(
            (
                "SELECT MAX(created_at) AS max_created_at FROM messages "
                f"WHERE id IN ({placeholders})"
            ),
            refs,
        ).fetchone()
        if row is None or row["max_created_at"] is None:
            return self._now_iso()
        return str(row["max_created_at"])

    @staticmethod
    def _merge_unique(left: list[str], right: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in left + right:
            clean = value.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            ordered.append(clean)
        return ordered

    def upsert_item(self, conn: sqlite3.Connection, thread_id: str, item: StateItem) -> StateItem:
        now = self._now_iso()
        candidate_last_seen = self._max_ref_timestamp(conn, item.refs)
        row = conn.execute(
            (
                "SELECT uid, text, status, type_tag, topic_tags_json, refs_json, confidence, "
                "replaced_by, supersession_evidence, conflict, pinned, source, created_at, "
                "last_seen_at FROM state_items WHERE thread_id=? AND uid=?"
            ),
            (thread_id, item.uid),
        ).fetchone()
        if row is None:
            created_at = item.created_at or now
            conn.execute(
                (
                    "INSERT INTO state_items("
                    "uid, thread_id, text, status, type_tag, topic_tags_json, refs_json, "
                    "confidence, replaced_by, supersession_evidence, conflict, pinned, source, "
                    "created_at, last_seen_at, updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                ),
                (
                    item.uid,
                    thread_id,
                    item.text,
                    item.status or DEFAULT_STATUS.get(item.type_tag, "active"),
                    item.type_tag,
                    json.dumps(item.topic_tags),
                    json.dumps(item.refs),
                    item.confidence,
                    item.replaced_by,
                    json.dumps(item.supersession_evidence) if item.supersession_evidence else None,
                    1 if item.conflict else 0,
                    1 if item.pinned else 0,
                    item.source or "extraction",
                    created_at,
                    item.last_seen_at or candidate_last_seen,
                    now,
                ),
            )
            item.created_at = created_at
            item.last_seen_at = item.last_seen_at or candidate_last_seen
            self._emit_state_event(
                conn,
                thread_id,
                "memory.reconcile",
                {"uid": item.uid, "action": "insert", "type_tag": item.type_tag},
            )
            return item

        old_topic_tags = json.loads(str(row["topic_tags_json"]) or "[]")
        old_refs = json.loads(str(row["refs_json"]) or "[]")
        old_confidence = str(row["confidence"])
        merged_topic_tags = self._merge_unique(
            [str(v) for v in old_topic_tags if isinstance(v, str)],
            item.topic_tags,
        )
        merged_refs = self._merge_unique(
            [str(v) for v in old_refs if isinstance(v, str)],
            item.refs,
        )
        merged_status = resolve_status_merge(
            str(row["type_tag"]),
            str(row["status"]),
            item.status or DEFAULT_STATUS.get(str(row["type_tag"]), "active"),
        )
        merged_confidence = (
            item.confidence
            if self._confidence_rank(item.confidence) >= self._confidence_rank(old_confidence)
            else old_confidence
        )
        merged_last_seen = max(str(row["last_seen_at"]), candidate_last_seen)
        merged_replaced_by = item.replaced_by or row["replaced_by"]
        merged_evidence = (
            item.supersession_evidence
            if item.supersession_evidence is not None
            else (
                json.loads(str(row["supersession_evidence"]))
                if row["supersession_evidence"] is not None
                else None
            )
        )
        conn.execute(
            (
                "UPDATE state_items SET text=?, status=?, topic_tags_json=?, refs_json=?, "
                "confidence=?, replaced_by=?, supersession_evidence=?, conflict=?, pinned=?, "
                "source=?, last_seen_at=?, updated_at=? "
                "WHERE uid=? AND thread_id=?"
            ),
            (
                item.text or str(row["text"]),
                merged_status,
                json.dumps(merged_topic_tags),
                json.dumps(merged_refs),
                merged_confidence,
                merged_replaced_by,
                json.dumps(merged_evidence) if merged_evidence is not None else None,
                1 if (bool(int(row["conflict"])) or item.conflict) else 0,
                1 if (bool(int(row["pinned"])) or item.pinned) else 0,
                item.source or str(row["source"]) or "extraction",
                merged_last_seen,
                now,
                item.uid,
                thread_id,
            ),
        )
        self._emit_state_event(
            conn,
            thread_id,
            "memory.reconcile",
            {"uid": item.uid, "action": "update", "type_tag": item.type_tag},
        )
        return StateItem(
            uid=item.uid,
            text=item.text or str(row["text"]),
            status=merged_status,
            type_tag=str(row["type_tag"]),
            topic_tags=merged_topic_tags,
            refs=merged_refs,
            confidence=merged_confidence,
            replaced_by=str(merged_replaced_by) if merged_replaced_by is not None else None,
            supersession_evidence=merged_evidence if isinstance(merged_evidence, dict) else None,
            conflict=bool(int(row["conflict"])) or item.conflict,
            pinned=bool(int(row["pinned"])) or item.pinned,
            source=item.source or str(row["source"]) or "extraction",
            created_at=str(row["created_at"]),
            last_seen_at=merged_last_seen,
        )

    def get_active_items(
        self, conn: sqlite3.Connection, thread_id: str, limit: int = 50
    ) -> list[StateItem]:
        rows = conn.execute(
            (
                "SELECT uid, text, status, type_tag, topic_tags_json, refs_json, confidence, "
                "replaced_by, supersession_evidence, conflict, pinned, source, created_at, "
                "last_seen_at "
                "FROM state_items "
                "WHERE thread_id=? AND status!='superseded' "
                "ORDER BY pinned DESC, "
                "CASE type_tag "
                "WHEN 'decision' THEN 0 "
                "WHEN 'constraint' THEN 1 "
                "WHEN 'action' THEN 2 "
                "WHEN 'risk' THEN 3 "
                "WHEN 'question' THEN 4 "
                "ELSE 5 END ASC, "
                "CASE confidence "
                "WHEN 'high' THEN 2 "
                "WHEN 'medium' THEN 1 "
                "ELSE 0 END DESC, "
                "last_seen_at DESC "
                "LIMIT ?"
            ),
            (thread_id, max(0, int(limit))),
        ).fetchall()
        return [self._row_to_state_item(row) for row in rows]

    def get_items_by_uids(
        self, conn: sqlite3.Connection, uids: list[str], thread_id: str | None = None
    ) -> list[StateItem]:
        if not uids:
            return []
        placeholders = ",".join("?" for _ in uids)
        if thread_id is None:
            rows = conn.execute(
                (
                    "SELECT uid, text, status, type_tag, topic_tags_json, refs_json, confidence, "
                    "replaced_by, supersession_evidence, conflict, pinned, source, created_at, "
                    "last_seen_at "
                    f"FROM state_items WHERE uid IN ({placeholders})"
                ),
                uids,
            ).fetchall()
        else:
            rows = conn.execute(
                (
                    "SELECT uid, text, status, type_tag, topic_tags_json, refs_json, confidence, "
                    "replaced_by, supersession_evidence, conflict, pinned, source, created_at, "
                    "last_seen_at "
                    f"FROM state_items WHERE thread_id=? AND uid IN ({placeholders})"
                ),
                [thread_id, *uids],
            ).fetchall()
        return [self._row_to_state_item(row) for row in rows]

    def mark_superseded(
        self,
        conn: sqlite3.Connection,
        uid: str,
        thread_id: str,
        replaced_by: str,
        evidence: dict[str, str],
    ) -> None:
        conn.execute(
            (
                "UPDATE state_items SET status='superseded', replaced_by=?, "
                "supersession_evidence=?, updated_at=? "
                "WHERE uid=? AND thread_id=?"
            ),
            (replaced_by, json.dumps(evidence), self._now_iso(), uid, thread_id),
        )

    def get_extraction_watermark(
        self, conn: sqlite3.Connection, thread_id: str
    ) -> tuple[str, str] | None:
        row = conn.execute(
            (
                "SELECT last_message_created_at, last_message_id "
                "FROM state_extraction_watermarks WHERE thread_id=?"
            ),
            (thread_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row["last_message_created_at"]), str(row["last_message_id"])

    def set_extraction_watermark(
        self, conn: sqlite3.Connection, thread_id: str, created_at: str, message_id: str
    ) -> None:
        now = self._now_iso()
        conn.execute(
            (
                "INSERT INTO state_extraction_watermarks("
                "thread_id, last_message_created_at, last_message_id, updated_at"
                ") VALUES(?,?,?,?) "
                "ON CONFLICT(thread_id) DO UPDATE SET "
                "last_message_created_at=excluded.last_message_created_at, "
                "last_message_id=excluded.last_message_id, "
                "updated_at=excluded.updated_at"
            ),
            (thread_id, created_at, message_id, now),
        )

    def get_new_messages_since(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        watermark: tuple[str, str] | None,
        limit: int,
    ) -> list[dict[str, str]]:
        if watermark is None:
            rows = conn.execute(
                (
                    "SELECT id, role, content, created_at FROM messages "
                    "WHERE thread_id=? ORDER BY created_at, id LIMIT ?"
                ),
                (thread_id, max(1, int(limit))),
            ).fetchall()
        else:
            created_at, message_id = watermark
            rows = conn.execute(
                (
                    "SELECT id, role, content, created_at FROM messages "
                    "WHERE thread_id=? AND ((created_at > ?) OR (created_at = ? AND id > ?)) "
                    "ORDER BY created_at, id LIMIT ?"
                ),
                (thread_id, created_at, created_at, message_id, max(1, int(limit))),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def search_similar_items(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        embedding: list[float],
        type_tag: str,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        normalized = self._normalize(embedding)
        sqlite_vec = self._search_state_vec_index(
            conn=conn,
            thread_id=thread_id,
            query_vec=normalized,
            type_tag=type_tag,
            limit=limit,
        )
        if sqlite_vec:
            return sqlite_vec

        rows = conn.execute(
            (
                "SELECT si.uid, si.text, si.status, si.type_tag, si.topic_tags_json, "
                "sie.vector_json "
                "FROM state_item_embeddings sie "
                "JOIN state_items si ON si.uid=sie.uid AND si.thread_id=sie.thread_id "
                "WHERE si.thread_id=? AND si.type_tag=? AND si.status!='superseded'"
            ),
            (thread_id, type_tag),
        ).fetchall()
        scored: list[tuple[float, dict[str, object]]] = []
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
            score = self._cosine(normalized, self._normalize(vec))
            topics_raw = json.loads(str(row["topic_tags_json"]) or "[]")
            topics = [str(tag) for tag in topics_raw if isinstance(tag, str)]
            scored.append(
                (
                    score,
                    {
                        "uid": str(row["uid"]),
                        "text": str(row["text"]),
                        "status": str(row["status"]),
                        "type_tag": str(row["type_tag"]),
                        "topic_tags": topics,
                        "score": score,
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored[: max(1, int(limit))]]

    def upsert_item_embedding(
        self, conn: sqlite3.Connection, uid: str, thread_id: str, embedding: list[float]
    ) -> None:
        now = self._now_iso()
        encoded = json.dumps(embedding)
        conn.execute(
            (
                "INSERT OR REPLACE INTO state_item_embeddings("
                "uid, thread_id, vector_json, created_at"
                ") VALUES(?,?,?,?)"
            ),
            (uid, thread_id, encoded, now),
        )
        self._upsert_state_vec_index(conn, uid=uid, thread_id=thread_id, embedding=embedding)

    def get_refs_content(
        self, conn: sqlite3.Connection, message_ids: list[str]
    ) -> list[dict[str, str]]:
        if not message_ids:
            return []
        placeholders = ",".join("?" for _ in message_ids)
        rows = conn.execute(
            (
                "SELECT id, role, content, created_at FROM messages "
                f"WHERE id IN ({placeholders}) ORDER BY created_at, id"
            ),
            message_ids,
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

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
                logger.debug("sqlite-vec extension load failed for state store", exc_info=True)
                return False
            finally:
                try:
                    conn.enable_load_extension(False)
                except sqlite3.OperationalError:
                    logger.debug("failed to disable sqlite extension loading", exc_info=True)
            if not self._has_vec_module(conn):
                return False

        dims = max(1, get_settings().memory_embed_dims)
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {self.STATE_VEC_INDEX_TABLE} "
                f"USING vec0(embedding float[{dims}])"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.STATE_VEC_INDEX_MAP_TABLE}("
                "vec_rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
                "uid TEXT NOT NULL, "
                "thread_id TEXT NOT NULL, "
                "UNIQUE(uid, thread_id))"
            )
        except sqlite3.OperationalError:
            logger.debug("state vector runtime setup failed", exc_info=True)
            return False
        self._backfill_state_vec_runtime(conn)
        return True

    def _backfill_state_vec_runtime(self, conn: sqlite3.Connection) -> None:
        try:
            rows = conn.execute(
                (
                    "SELECT sie.uid, sie.thread_id, sie.vector_json "
                    "FROM state_item_embeddings sie "
                    f"LEFT JOIN {self.STATE_VEC_INDEX_MAP_TABLE} sm "
                    "ON sm.uid=sie.uid AND sm.thread_id=sie.thread_id "
                    "WHERE sm.uid IS NULL ORDER BY sie.created_at ASC LIMIT ?"
                ),
                (self.BACKFILL_BATCH_SIZE,),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.debug("state vector backfill query failed", exc_info=True)
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
            self._upsert_state_vec_index_raw(
                conn=conn,
                uid=str(row["uid"]),
                thread_id=str(row["thread_id"]),
                embedding=embedding,
            )

    def _upsert_state_vec_index(
        self, conn: sqlite3.Connection, uid: str, thread_id: str, embedding: list[float]
    ) -> None:
        if not self._ensure_vec_runtime(conn):
            return
        self._upsert_state_vec_index_raw(conn, uid=uid, thread_id=thread_id, embedding=embedding)

    def _upsert_state_vec_index_raw(
        self, conn: sqlite3.Connection, uid: str, thread_id: str, embedding: list[float]
    ) -> None:
        row = conn.execute(
            (
                f"SELECT vec_rowid FROM {self.STATE_VEC_INDEX_MAP_TABLE} "
                "WHERE uid=? AND thread_id=?"
            ),
            (uid, thread_id),
        ).fetchone()
        if row is None:
            cursor = conn.execute(
                f"INSERT INTO {self.STATE_VEC_INDEX_MAP_TABLE}(uid, thread_id) VALUES(?, ?)",
                (uid, thread_id),
            )
            if cursor.lastrowid is None:
                return
            vec_rowid = int(cursor.lastrowid)
        else:
            vec_rowid = int(row["vec_rowid"])
        try:
            conn.execute(
                (
                    f"INSERT OR REPLACE INTO {self.STATE_VEC_INDEX_TABLE}(rowid, embedding) "
                    "VALUES(?, ?)"
                ),
                (vec_rowid, json.dumps(embedding)),
            )
        except sqlite3.OperationalError:
            logger.debug("state vector upsert failed", exc_info=True)

    def _search_state_vec_index(
        self,
        conn: sqlite3.Connection,
        thread_id: str,
        query_vec: list[float],
        type_tag: str,
        limit: int,
    ) -> list[dict[str, object]]:
        if not self._ensure_vec_runtime(conn):
            return []
        try:
            rows = conn.execute(
                (
                    f"SELECT sm.uid, si.text, si.status, si.type_tag, si.topic_tags_json, "
                    "sie.vector_json "
                    f"FROM {self.STATE_VEC_INDEX_TABLE} idx "
                    f"JOIN {self.STATE_VEC_INDEX_MAP_TABLE} sm ON sm.vec_rowid=idx.rowid "
                    "JOIN state_items si ON si.uid=sm.uid AND si.thread_id=sm.thread_id "
                    "JOIN state_item_embeddings sie "
                    "ON sie.uid=si.uid AND sie.thread_id=si.thread_id "
                    "WHERE idx.embedding MATCH ? AND k = ? "
                    "AND sm.thread_id=? AND si.type_tag=? AND si.status!='superseded'"
                ),
                (json.dumps(query_vec), max(1, int(limit)), thread_id, type_tag),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.debug("state vector index search failed", exc_info=True)
            return []
        result: list[dict[str, object]] = []
        for idx, row in enumerate(rows):
            topics_raw = json.loads(str(row["topic_tags_json"]) or "[]")
            topics = [str(tag) for tag in topics_raw if isinstance(tag, str)]
            score = 1.0 - (idx / max(len(rows), 1))
            raw_vec = row["vector_json"]
            if isinstance(raw_vec, str):
                try:
                    decoded = json.loads(raw_vec)
                    if isinstance(decoded, list):
                        candidate_vec = [
                            float(item) for item in decoded if isinstance(item, int | float)
                        ]
                        if candidate_vec:
                            score = self._cosine(query_vec, self._normalize(candidate_vec))
                except json.JSONDecodeError:
                    pass
            result.append(
                {
                    "uid": str(row["uid"]),
                    "text": str(row["text"]),
                    "status": str(row["status"]),
                    "type_tag": str(row["type_tag"]),
                    "topic_tags": topics,
                    "score": score,
                }
            )
        return result

    @staticmethod
    def _row_to_state_item(row: sqlite3.Row) -> StateItem:
        topic_tags_raw = json.loads(str(row["topic_tags_json"]) or "[]")
        refs_raw = json.loads(str(row["refs_json"]) or "[]")
        evidence_raw = row["supersession_evidence"]
        evidence: dict[str, object] | None = None
        if isinstance(evidence_raw, str) and evidence_raw:
            try:
                parsed = json.loads(evidence_raw)
                if isinstance(parsed, dict):
                    evidence = parsed
            except json.JSONDecodeError:
                evidence = None
        return StateItem(
            uid=str(row["uid"]),
            text=str(row["text"]),
            status=str(row["status"]),
            type_tag=str(row["type_tag"]),
            topic_tags=[str(v) for v in topic_tags_raw if isinstance(v, str)],
            refs=[str(v) for v in refs_raw if isinstance(v, str)],
            confidence=str(row["confidence"]),
            replaced_by=str(row["replaced_by"]) if row["replaced_by"] is not None else None,
            supersession_evidence=evidence,
            conflict=bool(int(row["conflict"])),
            pinned=bool(int(row["pinned"])),
            source=str(row["source"]),
            created_at=str(row["created_at"]),
            last_seen_at=str(row["last_seen_at"]),
        )


def state_type_sort_key(type_tag: str) -> int:
    return TYPE_PRIORITY.get(type_tag, 99)
