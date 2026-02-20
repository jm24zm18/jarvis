CREATE TABLE IF NOT EXISTS system_fitness_snapshots (
  id TEXT PRIMARY KEY,
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_system_fitness_created
ON system_fitness_snapshots(created_at DESC);
