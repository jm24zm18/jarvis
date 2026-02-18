CREATE TABLE IF NOT EXISTS selfupdate_fitness_gate_config (
  id TEXT PRIMARY KEY,
  max_snapshot_age_minutes INTEGER NOT NULL DEFAULT 180,
  min_build_success_rate REAL NOT NULL DEFAULT 0.80,
  max_regression_frequency REAL NOT NULL DEFAULT 0.40,
  max_rollback_frequency INTEGER NOT NULL DEFAULT 3,
  updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO selfupdate_fitness_gate_config(
  id,
  max_snapshot_age_minutes,
  min_build_success_rate,
  max_regression_frequency,
  max_rollback_frequency,
  updated_at
) VALUES('singleton', 180, 0.80, 0.40, 3, datetime('now'));
