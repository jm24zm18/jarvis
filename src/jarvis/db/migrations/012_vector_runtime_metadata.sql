CREATE TABLE IF NOT EXISTS memory_vec_index_map (
  vec_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS event_vec_index_map (
  vec_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT UNIQUE NOT NULL,
  thread_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_event_vec_index_map_thread
  ON event_vec_index_map(thread_id);
