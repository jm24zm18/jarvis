CREATE TABLE IF NOT EXISTS knowledge_graph (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.5,
  importance INTEGER NOT NULL DEFAULT 5,
  first_seen TEXT NOT NULL,
  last_updated TEXT NOT NULL,
  source_thread_id TEXT,
  superseded_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_kg_user_subject
ON knowledge_graph(user_id, subject);

CREATE INDEX IF NOT EXISTS idx_kg_user_predicate
ON knowledge_graph(user_id, predicate);

CREATE INDEX IF NOT EXISTS idx_kg_user_importance
ON knowledge_graph(user_id, importance DESC);

CREATE INDEX IF NOT EXISTS idx_kg_user_subject_predicate_active
ON knowledge_graph(user_id, subject, predicate, superseded_by);
