CREATE TABLE IF NOT EXISTS system_guardrails (
  id TEXT PRIMARY KEY,
  max_patch_attempts_per_day INTEGER NOT NULL DEFAULT 20,
  max_prs_per_day INTEGER NOT NULL DEFAULT 10,
  max_files_per_patch INTEGER NOT NULL DEFAULT 60,
  max_risk_score INTEGER NOT NULL DEFAULT 8,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guardrail_trips (
  id TEXT PRIMARY KEY,
  guardrail_key TEXT NOT NULL,
  actual_value INTEGER NOT NULL,
  threshold_value INTEGER NOT NULL,
  trace_id TEXT NOT NULL DEFAULT '',
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_guardrail_trips_created
ON guardrail_trips(created_at DESC);
