ALTER TABLE state_items ADD COLUMN tier TEXT NOT NULL DEFAULT 'working';
ALTER TABLE state_items ADD COLUMN importance_score REAL NOT NULL DEFAULT 0.5;
ALTER TABLE state_items ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE state_items ADD COLUMN conflict_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE state_items ADD COLUMN agent_id TEXT NOT NULL DEFAULT 'main';
ALTER TABLE state_items ADD COLUMN last_accessed_at TEXT;

CREATE INDEX IF NOT EXISTS idx_state_items_scope_tier_status_seen
ON state_items(thread_id, agent_id, tier, status, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_state_items_tier_importance_seen
ON state_items(tier, importance_score, last_seen_at DESC);
