-- Migration: create user_memory_items table (SQLite-compatible)
CREATE TABLE IF NOT EXISTS user_memory_items (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value_json TEXT NOT NULL,
  tags_json TEXT,
  expires_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes for fast lookup.
CREATE INDEX IF NOT EXISTS idx_user_memory_user_key
ON user_memory_items(user_id, key);

CREATE INDEX IF NOT EXISTS idx_user_memory_expires
ON user_memory_items(expires_at);
