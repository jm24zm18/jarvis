-- Track source thread intent and execution mode for feature build runs.
ALTER TABLE feature_request_build_runs
    ADD COLUMN source_thread_id TEXT NOT NULL DEFAULT '';

ALTER TABLE feature_request_build_runs
    ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'direct';

CREATE INDEX IF NOT EXISTS idx_feature_build_runs_source_thread
    ON feature_request_build_runs(source_thread_id);

CREATE INDEX IF NOT EXISTS idx_feature_build_runs_execution_mode
    ON feature_request_build_runs(execution_mode);
