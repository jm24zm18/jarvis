CREATE TABLE IF NOT EXISTS user_reflection_watermarks (
  user_id TEXT PRIMARY KEY,
  last_reflected_at TEXT,
  source_thread_count INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_reflection_watermarks_last_reflected
ON user_reflection_watermarks(last_reflected_at);
