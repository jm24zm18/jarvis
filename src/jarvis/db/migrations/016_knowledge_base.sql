CREATE TABLE IF NOT EXISTS knowledge_docs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL UNIQUE,
  content TEXT NOT NULL,
  tags_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_docs_updated_at
ON knowledge_docs(updated_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_docs_fts USING fts5(
  doc_id UNINDEXED,
  title,
  content,
  tags
);
