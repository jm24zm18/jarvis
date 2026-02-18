CREATE TABLE IF NOT EXISTS state_items_archive (
  uid TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL,
  type_tag TEXT NOT NULL,
  topic_tags_json TEXT NOT NULL,
  refs_json TEXT NOT NULL,
  confidence TEXT NOT NULL,
  replaced_by TEXT,
  supersession_evidence TEXT,
  conflict INTEGER NOT NULL,
  pinned INTEGER NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  tier TEXT NOT NULL DEFAULT 'working',
  importance_score REAL NOT NULL DEFAULT 0.5,
  access_count INTEGER NOT NULL DEFAULT 0,
  conflict_count INTEGER NOT NULL DEFAULT 0,
  agent_id TEXT NOT NULL DEFAULT 'main',
  last_accessed_at TEXT,
  archived_at TEXT NOT NULL,
  archive_reason TEXT NOT NULL,
  PRIMARY KEY(uid, thread_id, archived_at)
);

CREATE INDEX IF NOT EXISTS idx_state_items_archive_agent_tier_created
ON state_items_archive(agent_id, tier, archived_at DESC);

CREATE TABLE IF NOT EXISTS memory_items_archive (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  text TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  archived_at TEXT NOT NULL,
  archive_reason TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_items_archive_thread_created
ON memory_items_archive(thread_id, archived_at DESC);
