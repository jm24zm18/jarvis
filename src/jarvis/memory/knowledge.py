"""Project knowledge base storage and retrieval."""

import json
import sqlite3
from datetime import UTC, datetime

from jarvis.ids import new_id


class KnowledgeBaseService:
    @staticmethod
    def _fts_query(text: str) -> str:
        tokens = [token.strip() for token in text.replace('"', " ").split() if token.strip()]
        if not tokens:
            return ""
        return " OR ".join(tokens[:8])

    def put(
        self,
        conn: sqlite3.Connection,
        *,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> dict[str, str]:
        clean_title = title.strip()
        clean_content = content.strip()
        if not clean_title:
            raise ValueError("title is required")
        if not clean_content:
            raise ValueError("content is required")
        clean_tags = [item.strip() for item in (tags or []) if item.strip()]

        now = datetime.now(UTC).isoformat()
        existing = conn.execute(
            "SELECT id FROM knowledge_docs WHERE title=? LIMIT 1",
            (clean_title,),
        ).fetchone()
        if existing is None:
            doc_id = new_id("kb")
            conn.execute(
                (
                    "INSERT INTO knowledge_docs("
                    "id, title, content, tags_json, created_at, updated_at"
                    ") VALUES(?,?,?,?,?,?)"
                ),
                (doc_id, clean_title, clean_content, json.dumps(clean_tags), now, now),
            )
        else:
            doc_id = str(existing["id"])
            conn.execute(
                (
                    "UPDATE knowledge_docs "
                    "SET content=?, tags_json=?, updated_at=? "
                    "WHERE id=?"
                ),
                (clean_content, json.dumps(clean_tags), now, doc_id),
            )
        conn.execute(
            (
                "INSERT OR REPLACE INTO knowledge_docs_fts("
                "doc_id, title, content, tags"
                ") VALUES(?,?,?,?)"
            ),
            (doc_id, clean_title, clean_content, " ".join(clean_tags)),
        )
        return {"id": doc_id, "title": clean_title}

    def list_docs(self, conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, str]]:
        rows = conn.execute(
            (
                "SELECT id, title, updated_at "
                "FROM knowledge_docs "
                "ORDER BY updated_at DESC LIMIT ?"
            ),
            (max(1, min(limit, 100)),),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def get(self, conn: sqlite3.Connection, reference: str) -> dict[str, str] | None:
        ref = reference.strip()
        if not ref:
            return None
        row = conn.execute(
            (
                "SELECT id, title, content, updated_at "
                "FROM knowledge_docs WHERE id=? LIMIT 1"
            ),
            (ref,),
        ).fetchone()
        if row is None:
            row = conn.execute(
                (
                    "SELECT id, title, content, updated_at "
                    "FROM knowledge_docs WHERE title=? LIMIT 1"
                ),
                (ref,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "content": str(row["content"]),
            "updated_at": str(row["updated_at"]),
        }

    def search(
        self,
        conn: sqlite3.Connection,
        *,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, str]]:
        clean_query = query.strip()
        if not clean_query:
            return []
        fts_query = self._fts_query(clean_query)
        if not fts_query:
            return []
        try:
            rows = conn.execute(
                (
                    "SELECT kd.id, kd.title, kd.content, kd.updated_at "
                    "FROM knowledge_docs_fts kf "
                    "JOIN knowledge_docs kd ON kd.id=kf.doc_id "
                    "WHERE knowledge_docs_fts MATCH ? "
                    "ORDER BY bm25(knowledge_docs_fts), kd.updated_at DESC LIMIT ?"
                ),
                (fts_query, max(1, min(limit, 50))),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                (
                    "SELECT id, title, content, updated_at "
                    "FROM knowledge_docs "
                    "WHERE title LIKE ? OR content LIKE ? "
                    "ORDER BY updated_at DESC LIMIT ?"
                ),
                (f"%{clean_query}%", f"%{clean_query}%", max(1, min(limit, 50))),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "content": str(row["content"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]
