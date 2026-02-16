ALTER TABLE skills ADD COLUMN package_version TEXT;
ALTER TABLE skills ADD COLUMN manifest_json TEXT;
ALTER TABLE skills ADD COLUMN installed_at TEXT;
ALTER TABLE skills ADD COLUMN install_source TEXT;

CREATE TABLE IF NOT EXISTS skill_install_log (
  id TEXT PRIMARY KEY,
  skill_slug TEXT NOT NULL,
  action TEXT NOT NULL,
  from_version TEXT,
  to_version TEXT,
  source TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_install_log_slug
ON skill_install_log(skill_slug, created_at DESC);
