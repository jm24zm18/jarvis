ALTER TABLE feature_request_build_runs ADD COLUMN active_attempt INTEGER NOT NULL DEFAULT 1;
ALTER TABLE feature_request_build_runs ADD COLUMN last_progress_at TEXT NOT NULL DEFAULT '';
ALTER TABLE feature_request_build_runs ADD COLUMN last_event_type TEXT NOT NULL DEFAULT '';
ALTER TABLE feature_request_build_runs ADD COLUMN last_trace_id TEXT NOT NULL DEFAULT '';
ALTER TABLE feature_request_build_runs ADD COLUMN terminal_reason TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_feature_build_runs_progress
    ON feature_request_build_runs(status, active_attempt, updated_at);
