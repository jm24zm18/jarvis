CREATE TABLE IF NOT EXISTS state_reconciliation_runs (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL DEFAULT 'global',
  stale_before TEXT NOT NULL,
  updated_count INTEGER NOT NULL DEFAULT 0,
  superseded_count INTEGER NOT NULL DEFAULT 0,
  deduped_count INTEGER NOT NULL DEFAULT 0,
  pruned_count INTEGER NOT NULL DEFAULT 0,
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_state_reconciliation_runs_created
ON state_reconciliation_runs(created_at DESC);
