"""Simple SQL migration runner."""

import os
from pathlib import Path

from jarvis.db.connection import get_conn

MIGRATIONS_DIR = Path(__file__).resolve().parent


def run_migrations() -> None:
    with get_conn() as conn:
        holder = f"{os.uname().nodename}:{os.getpid()}"
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations("
                "name TEXT PRIMARY KEY, "
                "applied_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migration_lock("
                "id INTEGER PRIMARY KEY CHECK(id=1), "
                "holder TEXT, acquired_at TEXT)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migration_lock(id, holder, acquired_at) "
                "VALUES(1, NULL, NULL)"
            )
            lock_row = conn.execute(
                "SELECT holder FROM schema_migration_lock WHERE id=1"
            ).fetchone()
            current_holder = str(lock_row[0]) if lock_row and lock_row[0] else ""
            if current_holder and current_holder != holder:
                raise RuntimeError(f"migration lock held by {current_holder}")
            conn.execute(
                "UPDATE schema_migration_lock SET holder=?, acquired_at=datetime('now') "
                "WHERE id=1",
                (holder,),
            )

            applied = {
                row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()
            }
            for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if file.name in applied:
                    continue
                conn.executescript(file.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations(name, applied_at) VALUES(?, datetime('now'))",
                    (file.name,),
                )
            conn.execute(
                "UPDATE schema_migration_lock SET holder=NULL, acquired_at=NULL WHERE id=1"
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


if __name__ == "__main__":
    run_migrations()
