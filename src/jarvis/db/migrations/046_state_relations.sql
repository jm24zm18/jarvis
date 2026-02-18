CREATE TABLE IF NOT EXISTS state_relations (
  id TEXT PRIMARY KEY,
  source_uid TEXT NOT NULL,
  target_uid TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  agent_id TEXT NOT NULL DEFAULT 'main',
  relation_type TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.5,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_state_relations_source_type
ON state_relations(source_uid, relation_type);

CREATE INDEX IF NOT EXISTS idx_state_relations_target_type
ON state_relations(target_uid, relation_type);
