CREATE TABLE IF NOT EXISTS memory_items (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  text TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(thread_id) REFERENCES threads(id)
);

CREATE TABLE IF NOT EXISTS memory_embeddings (
  memory_id TEXT PRIMARY KEY,
  model TEXT NOT NULL,
  vector_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memory_items(id)
);

CREATE TABLE IF NOT EXISTS event_text (
  event_id TEXT PRIMARY KEY,
  thread_id TEXT,
  redacted_text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(event_id) REFERENCES events(id)
);
