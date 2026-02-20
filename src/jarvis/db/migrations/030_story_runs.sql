CREATE TABLE IF NOT EXISTS story_runs (
  id TEXT PRIMARY KEY,
  pack TEXT NOT NULL,
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  report_json TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT 'system',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_story_runs_pack_created
ON story_runs(pack, created_at DESC);

