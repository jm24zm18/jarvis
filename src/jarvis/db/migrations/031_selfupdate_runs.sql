CREATE TABLE IF NOT EXISTS selfupdate_runs (
  trace_id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  baseline_ref TEXT NOT NULL,
  repo_path TEXT NOT NULL,
  rationale TEXT NOT NULL,
  changed_files_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS selfupdate_checks (
  id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  check_type TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_selfupdate_checks_trace_created
ON selfupdate_checks(trace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS selfupdate_transitions (
  id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_selfupdate_transitions_trace_created
ON selfupdate_transitions(trace_id, created_at DESC);
