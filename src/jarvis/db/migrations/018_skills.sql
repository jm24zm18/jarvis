CREATE TABLE IF NOT EXISTS skills (
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'global',
  owner_id TEXT,
  pinned INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL DEFAULT 'agent',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (source IN ('seed', 'agent')),
  UNIQUE(slug, scope)
);

CREATE INDEX IF NOT EXISTS idx_skills_scope
ON skills(scope);

CREATE INDEX IF NOT EXISTS idx_skills_pinned
ON skills(pinned);

CREATE INDEX IF NOT EXISTS idx_skills_updated_at
ON skills(updated_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
  skill_id UNINDEXED,
  slug,
  title,
  content,
  scope
);
