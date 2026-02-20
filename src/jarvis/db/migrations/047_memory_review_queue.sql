CREATE TABLE IF NOT EXISTS memory_review_queue (
  id TEXT PRIMARY KEY,
  uid TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  agent_id TEXT NOT NULL DEFAULT 'main',
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  reviewer_id TEXT,
  resolution_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_review_queue_status_created
ON memory_review_queue(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_review_queue_uid
ON memory_review_queue(uid, thread_id);
