ALTER TABLE approvals ADD COLUMN target_ref TEXT NOT NULL DEFAULT '';
ALTER TABLE approvals ADD COLUMN expires_at TEXT;
ALTER TABLE approvals ADD COLUMN consumed_by_trace_id TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_approvals_action_status_target
ON approvals(action, status, target_ref, created_at);

