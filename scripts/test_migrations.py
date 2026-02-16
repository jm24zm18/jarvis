#!/usr/bin/env python3
"""Test that all SQL migrations apply cleanly to a fresh SQLite database.

Uses only stdlib modules — no uv sync needed.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "src" / "jarvis" / "db" / "migrations"


def main() -> int:
    if not MIGRATIONS_DIR.exists():
        print(f"migrations directory not found: {MIGRATIONS_DIR}")
        return 2

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print("no migration files found")
        return 2

    print(f"Found {len(migration_files)} migration(s)")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tmp:
        db_path = tmp.name

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )

    applied = 0
    try:
        for sql_file in migration_files:
            sql = sql_file.read_text()
            try:
                conn.executescript(sql)
            except sqlite3.Error as e:
                print(f"FAILED applying {sql_file.name}: {e}")
                conn.close()
                return 1
            conn.execute(
                "INSERT INTO schema_migrations(name, applied_at) VALUES(?, datetime('now'))",
                (sql_file.name,),
            )
            conn.commit()
            applied += 1
            print(f"  Applied: {sql_file.name}")

        # Integrity check
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            print(f"INTEGRITY CHECK FAILED: {result}")
            conn.close()
            return 1

        # List tables
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]

        print(f"\n{applied} migration(s) applied successfully")
        print("Integrity check: OK")
        print(f"Tables ({len(tables)}): {', '.join(tables)}")

    finally:
        conn.close()
        # Clean up temp file
        Path(db_path).unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
