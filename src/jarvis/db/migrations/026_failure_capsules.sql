CREATE TABLE IF NOT EXISTS failure_capsules (
  id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  phase TEXT NOT NULL,
  error_summary TEXT NOT NULL,
  error_details_json TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_failure_capsules_trace
ON failure_capsules(trace_id);

CREATE INDEX IF NOT EXISTS idx_failure_capsules_phase_created
ON failure_capsules(phase, created_at DESC);
