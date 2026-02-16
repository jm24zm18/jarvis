# PostgreSQL Migration Path

## Why migrate
SQLite with WAL is sufficient for a single API process and light background writes, but it becomes a bottleneck under higher write concurrency and multi-process scaling.
Current tuning in `src/jarvis/db/connection.py`:
- `PRAGMA journal_mode = WAL`
- `PRAGMA synchronous = NORMAL`
- `PRAGMA wal_autocheckpoint = 1000`
- `PRAGMA busy_timeout = 30000`

## Migration prerequisites
- Keep database access behind `get_conn()` so callsites are decoupled from the backend.
- Favor parameterized SQL helpers; avoid dynamic SQL string concatenation for values.
- Isolate storage-specific concerns (pragma statements, SQLite upsert patterns) inside DB-layer helpers.

## Step plan
1. Introduce a DB protocol layer for connection/session access and transaction boundaries.
2. Add a PostgreSQL implementation and wire it behind environment-driven selection.
3. Port migrations to a backend-agnostic migration tool or dual-sql migration strategy.
4. Replace SQLite-specific SQL patterns with portable equivalents.
5. Run dual-write or staged cutover in non-production, then production.

## Worker/runtime impact
- Celery `--pool=prefork` is substantially more viable after SQLite removal, since worker processes no longer contend on a single file-backed DB lock domain.

## Trigger to prioritize migration
Begin migration when single-process API/worker throughput or write-lock contention becomes a recurring production bottleneck.
