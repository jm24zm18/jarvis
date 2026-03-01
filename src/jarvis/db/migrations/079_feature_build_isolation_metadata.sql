-- Add isolation workspace and validation metadata to feature build runs.
ALTER TABLE feature_request_build_runs
    ADD COLUMN workspace_path TEXT NOT NULL DEFAULT '';
ALTER TABLE feature_request_build_runs
    ADD COLUMN workspace_created_at TEXT NOT NULL DEFAULT '';
ALTER TABLE feature_request_build_runs
    ADD COLUMN workspace_expires_at TEXT NOT NULL DEFAULT '';
ALTER TABLE feature_request_build_runs
    ADD COLUMN dependency_snapshot_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE feature_request_build_runs
    ADD COLUMN validation_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE feature_request_build_runs
    ADD COLUMN validation_log_path TEXT NOT NULL DEFAULT '';
ALTER TABLE feature_request_build_runs
    ADD COLUMN validation_error TEXT NOT NULL DEFAULT '';
