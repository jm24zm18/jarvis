CREATE TABLE IF NOT EXISTS memory_governance_audit (
  id TEXT PRIMARY KEY,
  thread_id TEXT,
  actor_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  target_kind TEXT NOT NULL,
  target_id TEXT NOT NULL DEFAULT '',
  payload_redacted_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_governance_thread_created
ON memory_governance_audit(thread_id, created_at DESC);

