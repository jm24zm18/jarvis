ALTER TABLE system_state ADD COLUMN host_exec_fail_streak INTEGER NOT NULL DEFAULT 0;
ALTER TABLE system_state ADD COLUMN last_host_exec_fail_at TEXT;

CREATE TABLE IF NOT EXISTS schema_migration_lock (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  holder TEXT,
  acquired_at TEXT
);
