CREATE TABLE IF NOT EXISTS schedules (
  id TEXT PRIMARY KEY,
  thread_id TEXT,
  cron_expr TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_run_at TEXT,
  created_at TEXT NOT NULL
);
