CREATE TABLE IF NOT EXISTS user_profiles (
  user_id TEXT PRIMARY KEY,
  core_beliefs TEXT NOT NULL DEFAULT '{}',
  summary TEXT,
  last_updated TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  source_thread_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_profile_history (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  snapshot TEXT NOT NULL,
  changed_at TEXT NOT NULL,
  change_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_last_updated
ON user_profiles(last_updated);

CREATE INDEX IF NOT EXISTS idx_user_profile_history_user_changed
ON user_profile_history(user_id, changed_at DESC);
