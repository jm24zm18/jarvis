-- Child feature support and RLM trajectory logging.
ALTER TABLE bug_reports ADD COLUMN parent_id TEXT REFERENCES bug_reports(id);
CREATE INDEX IF NOT EXISTS idx_bug_reports_parent_id ON bug_reports(parent_id);

CREATE TABLE IF NOT EXISTS rlm_trajectories (
    id TEXT PRIMARY KEY,
    feature_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    run_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_progress',
    prompt_hash TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    context_paths_json TEXT NOT NULL DEFAULT '[]',
    context_reasons_json TEXT NOT NULL DEFAULT '{}',
    results_raw TEXT NOT NULL DEFAULT '',
    validation_errors_json TEXT NOT NULL DEFAULT '[]',
    usage_json TEXT NOT NULL DEFAULT '{}',
    child_ids_json TEXT NOT NULL DEFAULT '[]',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rlm_trajectories_feature_hash
    ON rlm_trajectories(feature_id, run_hash);
CREATE INDEX IF NOT EXISTS idx_rlm_trajectories_run_id ON rlm_trajectories(run_id);
