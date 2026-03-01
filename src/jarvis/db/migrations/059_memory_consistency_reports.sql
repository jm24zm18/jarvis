-- Migration 059: memory_consistency_reports table
-- Stores historical consistency evaluation results per thread.

CREATE TABLE IF NOT EXISTS memory_consistency_reports (
    id               TEXT PRIMARY KEY,
    thread_id        TEXT NOT NULL,
    sample_size      INTEGER NOT NULL DEFAULT 0,
    total_items      INTEGER NOT NULL DEFAULT 0,
    conflicted_items INTEGER NOT NULL DEFAULT 0,
    consistency_score REAL NOT NULL DEFAULT 0.0,
    details_json     TEXT NOT NULL DEFAULT '{}',
    created_at       DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_consistency_reports_thread
    ON memory_consistency_reports(thread_id, created_at DESC);
