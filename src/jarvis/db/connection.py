"""SQLite connection management."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from jarvis.config import get_settings


def connect() -> sqlite3.Connection:
    settings = get_settings()
    Path(settings.app_db).parent.mkdir(parents=True, exist_ok=True)
    # Autocommit mode keeps write locks short under mixed API/worker access.
    conn = sqlite3.connect(settings.app_db, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA wal_autocheckpoint = 1000")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
