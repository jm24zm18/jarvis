CREATE TABLE IF NOT EXISTS failure_patterns (
  id TEXT PRIMARY KEY,
  signature TEXT NOT NULL,
  phase TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  latest_reason TEXT NOT NULL,
  latest_trace_id TEXT NOT NULL DEFAULT '',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_failure_patterns_signature_phase
ON failure_patterns(signature, phase);

CREATE TABLE IF NOT EXISTS failure_pattern_remediations (
  id TEXT PRIMARY KEY,
  pattern_id TEXT NOT NULL,
  remediation TEXT NOT NULL,
  verification_test TEXT NOT NULL DEFAULT '',
  confidence TEXT NOT NULL DEFAULT 'medium',
  created_at TEXT NOT NULL,
  FOREIGN KEY(pattern_id) REFERENCES failure_patterns(id)
);

CREATE INDEX IF NOT EXISTS idx_failure_pattern_remediations_pattern
ON failure_pattern_remediations(pattern_id, created_at DESC);
