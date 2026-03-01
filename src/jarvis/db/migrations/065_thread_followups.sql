CREATE TABLE IF NOT EXISTS thread_followups (
    thread_id TEXT PRIMARY KEY REFERENCES threads(id) ON DELETE CASCADE,
    enabled INTEGER NOT NULL DEFAULT 0,
    last_checked_at TEXT,
    last_sent_at TEXT,
    last_result TEXT NOT NULL DEFAULT 'no_reply',
    consecutive_no_reply INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_thread_followups_enabled
    ON thread_followups(enabled);

CREATE INDEX IF NOT EXISTS idx_thread_followups_last_checked
    ON thread_followups(last_checked_at);
