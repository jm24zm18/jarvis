"""Cross-thread user knowledge graph storage helpers."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from hashlib import sha256


class KnowledgeGraph:
    ALLOWED_PREDICATES = frozenset(
        {
            "prefers",
            "avoids",
            "knows",
            "uses",
            "has_goal",
            "works_on",
            "owns",
            "dislikes",
            "lives_in",
            "works_at",
            "best_practice_for",
            "lesson_learned",
            "should_avoid",
            "skill_for",
        }
    )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _triple_id(
        user_id: str,
        subject: str,
        predicate: str,
        object_: str,
        extraction_type: str,
    ) -> str:
        digest = sha256(
            f"{user_id}\n{subject}\n{predicate}\n{object_}\n{extraction_type}".encode()
        ).hexdigest()[:12]
        return f"kg_{digest}"

    def supersede(
        self,
        conn: sqlite3.Connection,
        *,
        triple_id: str,
        superseded_by: str,
    ) -> None:
        conn.execute(
            (
                "UPDATE knowledge_graph SET superseded_by=?, last_updated=? "
                "WHERE id=?"
            ),
            (superseded_by, self._now_iso(), triple_id),
        )

    def upsert_triple(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        subject: str,
        predicate: str,
        object_: str,
        confidence: float,
        importance: int = 5,
        source_thread_id: str | None = None,
        extraction_type: str = "profile",
        source_trace_id: str | None = None,
    ) -> str | None:
        clean_subject = subject.strip().lower()
        clean_predicate = predicate.strip().lower()
        clean_object = object_.strip()
        clean_extraction_type = extraction_type.strip().lower() or "profile"
        if clean_extraction_type not in {"profile", "task_lesson"}:
            clean_extraction_type = "profile"
        if not clean_subject or not clean_object:
            return None
        if clean_predicate not in self.ALLOWED_PREDICATES:
            return None
        if float(confidence) < 0.75:
            return None

        now = self._now_iso()
        triple_id = self._triple_id(
            user_id,
            clean_subject,
            clean_predicate,
            clean_object,
            clean_extraction_type,
        )

        existing_exact = conn.execute(
            (
                "SELECT id FROM knowledge_graph "
                "WHERE user_id=? AND subject=? AND predicate=? AND object=? "
                "AND extraction_type=? LIMIT 1"
            ),
            (
                user_id,
                clean_subject,
                clean_predicate,
                clean_object,
                clean_extraction_type,
            ),
        ).fetchone()
        if existing_exact is not None:
            existing_id = str(existing_exact["id"])
            conn.execute(
                (
                    "UPDATE knowledge_graph SET confidence=?, importance=?, last_updated=?, "
                    "source_thread_id=?, superseded_by=NULL, extraction_type=?, source_trace_id=? "
                    "WHERE id=?"
                ),
                (
                    float(confidence),
                    max(1, min(10, int(importance))),
                    now,
                    source_thread_id,
                    clean_extraction_type,
                    source_trace_id,
                    existing_id,
                ),
            )
            return existing_id

        conflicts = conn.execute(
            (
                "SELECT id, object, confidence FROM knowledge_graph "
                "WHERE user_id=? AND subject=? AND predicate=? AND extraction_type=? "
                "AND superseded_by IS NULL"
            ),
            (user_id, clean_subject, clean_predicate, clean_extraction_type),
        ).fetchall()

        conn.execute(
            (
                "INSERT INTO knowledge_graph("
                "id, user_id, subject, predicate, object, confidence, importance, "
                "first_seen, last_updated, source_thread_id, superseded_by, extraction_type, "
                "extracted_at, source_trace_id"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,NULL,?,?,?)"
            ),
            (
                triple_id,
                user_id,
                clean_subject,
                clean_predicate,
                clean_object,
                float(confidence),
                max(1, min(10, int(importance))),
                now,
                now,
                source_thread_id,
                clean_extraction_type,
                now,
                source_trace_id,
            ),
        )

        for row in conflicts:
            old_id = str(row["id"])
            old_obj = str(row["object"])
            old_conf = float(row["confidence"] or 0.0)
            if old_obj == clean_object:
                continue
            if float(confidence) > old_conf + 0.1:
                self.supersede(conn, triple_id=old_id, superseded_by=triple_id)
            else:
                conn.execute(
                    "UPDATE knowledge_graph SET confidence=? WHERE id=?",
                    (max(0.0, min(old_conf, float(confidence)) - 0.05), old_id),
                )
                conn.execute(
                    "UPDATE knowledge_graph SET confidence=? WHERE id=?",
                    (max(0.0, float(confidence) - 0.05), triple_id),
                )

        return triple_id

    def query(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        subject: str | None = None,
        predicate: str | None = None,
        extraction_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        params: list[object] = [user_id]
        clauses = ["user_id=?", "superseded_by IS NULL"]
        if subject and subject.strip():
            clauses.append("subject=?")
            params.append(subject.strip().lower())
        if predicate and predicate.strip():
            clauses.append("predicate=?")
            params.append(predicate.strip().lower())
        if extraction_type and extraction_type.strip():
            clauses.append("extraction_type=?")
            params.append(extraction_type.strip().lower())
        params.append(max(1, int(limit)))
        rows = conn.execute(
            (
                "SELECT id, user_id, subject, predicate, object, confidence, importance, "
                "first_seen, last_updated, source_thread_id, superseded_by, extraction_type, "
                "extracted_at, source_trace_id "
                "FROM knowledge_graph "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY importance DESC, confidence DESC, last_updated DESC "
                "LIMIT ?"
            ),
            tuple(params),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "user_id": str(row["user_id"]),
                "subject": str(row["subject"]),
                "predicate": str(row["predicate"]),
                "object": str(row["object"]),
                "confidence": float(row["confidence"] or 0.0),
                "importance": int(row["importance"] or 0),
                "first_seen": str(row["first_seen"]),
                "last_updated": str(row["last_updated"]),
                "source_thread_id": str(row["source_thread_id"])
                if row["source_thread_id"] is not None
                else None,
                "superseded_by": str(row["superseded_by"])
                if row["superseded_by"] is not None
                else None,
                "extraction_type": str(row["extraction_type"])
                if row["extraction_type"] is not None
                else "profile",
                "extracted_at": str(row["extracted_at"])
                if row["extracted_at"] is not None
                else None,
                "source_trace_id": str(row["source_trace_id"])
                if row["source_trace_id"] is not None
                else None,
            }
            for row in rows
        ]

    def get_user_snapshot(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        return self.query(conn, user_id=user_id, limit=limit)
