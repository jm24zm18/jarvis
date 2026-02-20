CREATE TABLE IF NOT EXISTS failure_state_links (
  failure_capsule_id TEXT NOT NULL,
  state_uid TEXT NOT NULL,
  thread_id TEXT,
  agent_id TEXT NOT NULL DEFAULT 'main',
  created_at TEXT NOT NULL,
  PRIMARY KEY (failure_capsule_id, state_uid)
);

CREATE INDEX IF NOT EXISTS idx_failure_state_links_state
ON failure_state_links(state_uid);
