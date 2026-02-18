CREATE TABLE IF NOT EXISTS memory_consistency_reports(
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  sample_size INTEGER NOT NULL,
  total_items INTEGER NOT NULL,
  conflicted_items INTEGER NOT NULL,
  consistency_score REAL NOT NULL,
  details_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_consistency_reports_thread_created
  ON memory_consistency_reports(thread_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_consistency_reports_created
  ON memory_consistency_reports(created_at DESC);
