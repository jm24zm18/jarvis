-- Retry metadata for feature request build runs.
ALTER TABLE feature_request_build_runs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE feature_request_build_runs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 5;
ALTER TABLE feature_request_build_runs ADD COLUMN retry_state TEXT NOT NULL DEFAULT 'none';
ALTER TABLE feature_request_build_runs ADD COLUMN next_retry_at TEXT NOT NULL DEFAULT '';
ALTER TABLE feature_request_build_runs ADD COLUMN last_failure_reason TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_frbr_retry_due
    ON feature_request_build_runs(retry_state, next_retry_at);
