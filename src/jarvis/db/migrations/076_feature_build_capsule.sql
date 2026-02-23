-- Add capsule columns for cross-attempt context carry-over in feature build runs.
ALTER TABLE feature_request_build_runs ADD COLUMN last_capsule_json TEXT;
ALTER TABLE feature_request_build_runs ADD COLUMN last_capsule_hash TEXT;
