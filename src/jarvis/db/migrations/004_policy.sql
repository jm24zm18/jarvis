CREATE TABLE IF NOT EXISTS principals (
  id TEXT PRIMARY KEY,
  principal_type TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_permissions (
  principal_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  effect TEXT NOT NULL,
  PRIMARY KEY(principal_id, tool_name)
);

CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  action TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
