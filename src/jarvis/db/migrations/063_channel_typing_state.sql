CREATE TABLE IF NOT EXISTS channel_typing_state (
    thread_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    set_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, recipient)
);
