CREATE TABLE IF NOT EXISTS failure_remediation_feedback (
  id TEXT PRIMARY KEY,
  remediation_id TEXT NOT NULL,
  actor_id TEXT NOT NULL DEFAULT '',
  feedback TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(remediation_id) REFERENCES failure_pattern_remediations(id)
);

CREATE INDEX IF NOT EXISTS idx_failure_remediation_feedback_remediation
ON failure_remediation_feedback(remediation_id, created_at DESC);
