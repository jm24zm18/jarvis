-- Build run history for feature requests.
-- Status enum (app-enforced): queued|running|succeeded|failed|timed_out|cancelled
CREATE TABLE IF NOT EXISTS feature_request_build_runs (
    id TEXT PRIMARY KEY,
    feature_id TEXT NOT NULL,
    trace_id TEXT NOT NULL DEFAULT '',
    thread_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    summary TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_frbr_feature_created
    ON feature_request_build_runs(feature_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_frbr_trace_id
    ON feature_request_build_runs(trace_id);
