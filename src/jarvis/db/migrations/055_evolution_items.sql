CREATE TABLE IF NOT EXISTS evolution_items(
  id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  thread_id TEXT,
  status TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_evolution_items_status_updated
  ON evolution_items(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_evolution_items_trace
  ON evolution_items(trace_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_evolution_items_thread
  ON evolution_items(thread_id, updated_at DESC);
