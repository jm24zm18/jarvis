"""Token-based session authentication helpers for web UI."""

import hashlib
import secrets
import sqlite3
import time
from datetime import UTC, datetime, timedelta

from jarvis.config import get_settings
from jarvis.ids import new_id

_LOCK_RETRY_ATTEMPTS = 3
_LOCK_RETRY_SLEEP_SECONDS = 0.2


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: str, role: str) -> tuple[str, str]:
    settings = get_settings()
    session_id = new_id("wss")
    raw_token = secrets.token_urlsafe(48)
    created_at = datetime.now(UTC)
    expires_at = created_at + timedelta(hours=max(1, settings.web_auth_token_ttl_hours))
    for attempt in range(1, _LOCK_RETRY_ATTEMPTS + 1):
        try:
            conn.execute(
                (
                    "INSERT INTO web_sessions("
                    "id, user_id, role, token_hash, created_at, expires_at"
                    ") VALUES(?,?,?,?,?,?)"
                ),
                (
                    session_id,
                    user_id,
                    role,
                    _token_hash(raw_token),
                    created_at.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            break
        except sqlite3.OperationalError as exc:
            locked = "database is locked" in str(exc).lower()
            if not locked or attempt >= _LOCK_RETRY_ATTEMPTS:
                raise
            time.sleep(_LOCK_RETRY_SLEEP_SECONDS * attempt)
    return session_id, raw_token


def validate_token(conn: sqlite3.Connection, raw_token: str) -> tuple[str, str] | None:
    hashed = _token_hash(raw_token)
    row = conn.execute(
        "SELECT id, user_id, role, expires_at FROM web_sessions WHERE token_hash=? LIMIT 1",
        (hashed,),
    ).fetchone()
    if row is None:
        return None

    expires_raw = row["expires_at"]
    if not isinstance(expires_raw, str):
        conn.execute("DELETE FROM web_sessions WHERE id=?", (str(row["id"]),))
        return None

    try:
        expires_at = datetime.fromisoformat(expires_raw)
    except ValueError:
        conn.execute("DELETE FROM web_sessions WHERE id=?", (str(row["id"]),))
        return None

    now = datetime.now(UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        conn.execute("DELETE FROM web_sessions WHERE id=?", (str(row["id"]),))
        return None

    return str(row["user_id"]), str(row["role"])


def delete_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM web_sessions WHERE id=?", (session_id,))


def delete_session_by_token(conn: sqlite3.Connection, raw_token: str) -> None:
    conn.execute("DELETE FROM web_sessions WHERE token_hash=?", (_token_hash(raw_token),))


def session_from_token(conn: sqlite3.Connection, raw_token: str) -> tuple[str, str] | None:
    hashed = _token_hash(raw_token)
    row = conn.execute(
        "SELECT id, user_id FROM web_sessions WHERE token_hash=? LIMIT 1",
        (hashed,),
    ).fetchone()
    if row is None:
        return None
    return str(row["id"]), str(row["user_id"])
