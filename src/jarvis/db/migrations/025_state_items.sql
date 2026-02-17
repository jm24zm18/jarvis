CREATE TABLE IF NOT EXISTS state_items (
  uid TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  type_tag TEXT NOT NULL,
  topic_tags_json TEXT NOT NULL DEFAULT '[]',
  refs_json TEXT NOT NULL DEFAULT '[]',
  confidence TEXT NOT NULL DEFAULT 'medium',
  replaced_by TEXT,
  supersession_evidence TEXT,
  conflict INTEGER NOT NULL DEFAULT 0,
  pinned INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'extraction',
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (uid, thread_id)
);

CREATE INDEX IF NOT EXISTS idx_state_items_thread_status
ON state_items(thread_id, status);

CREATE INDEX IF NOT EXISTS idx_state_items_thread_type
ON state_items(thread_id, type_tag);

CREATE INDEX IF NOT EXISTS idx_state_items_thread_updated
ON state_items(thread_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_state_items_thread_last_seen
ON state_items(thread_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS state_item_embeddings (
  uid TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  vector_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (uid, thread_id)
);

CREATE TABLE IF NOT EXISTS state_extraction_watermarks (
  thread_id TEXT PRIMARY KEY,
  last_message_created_at TEXT NOT NULL,
  last_message_id TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
