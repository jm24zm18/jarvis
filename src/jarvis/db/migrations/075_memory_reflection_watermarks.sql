-- Migration 075: track background memory reflection runs.
CREATE TABLE IF NOT EXISTS memory_reflection_watermarks (
    thread_id TEXT PRIMARY KEY,
    last_reflected_at TEXT,
    last_insight_count INTEGER DEFAULT 0,
    last_pruned_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_reflection_watermarks_reflected_at
    ON memory_reflection_watermarks (last_reflected_at);
