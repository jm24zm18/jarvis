CREATE TABLE IF NOT EXISTS memory_vec (
  memory_id TEXT PRIMARY KEY,
  vector_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memory_items(id)
);

CREATE TABLE IF NOT EXISTS event_vec (
  id TEXT PRIMARY KEY,
  thread_id TEXT,
  vector_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_vec_thread ON event_vec(thread_id);
