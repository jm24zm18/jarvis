-- Webhook automation triggers table
CREATE TABLE IF NOT EXISTS webhook_triggers(
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT 'main',
    prompt_template TEXT NOT NULL DEFAULT '{{payload}}',
    hmac_secret TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES threads(id)
);
CREATE INDEX IF NOT EXISTS idx_webhook_triggers_enabled ON webhook_triggers(enabled);
