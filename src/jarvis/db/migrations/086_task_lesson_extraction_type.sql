ALTER TABLE knowledge_graph
  ADD COLUMN extraction_type TEXT NOT NULL DEFAULT 'profile'
    CHECK (extraction_type IN ('profile', 'task_lesson'));

ALTER TABLE knowledge_graph
  ADD COLUMN extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE knowledge_graph
  ADD COLUMN source_trace_id TEXT;

CREATE INDEX IF NOT EXISTS idx_kg_user_extraction_type
ON knowledge_graph(user_id, extraction_type);

CREATE INDEX IF NOT EXISTS idx_kg_user_extraction_type_extracted_at
ON knowledge_graph(user_id, extraction_type, extracted_at DESC);
