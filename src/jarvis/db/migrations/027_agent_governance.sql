CREATE TABLE IF NOT EXISTS agent_governance (
  principal_id TEXT PRIMARY KEY,
  risk_tier TEXT NOT NULL DEFAULT 'low',
  max_actions_per_step INTEGER NOT NULL DEFAULT 4,
  allowed_paths_json TEXT NOT NULL DEFAULT '[]',
  can_request_privileged_change INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

