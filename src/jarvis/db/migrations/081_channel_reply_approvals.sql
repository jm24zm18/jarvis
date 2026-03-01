CREATE TABLE IF NOT EXISTS channel_reply_approval_requests (
  id TEXT PRIMARY KEY,
  source_thread_id TEXT NOT NULL,
  source_message_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  channel_type TEXT NOT NULL,
  recipient TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  decision_mode TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  admin_thread_id TEXT NOT NULL DEFAULT '',
  decided_by TEXT NOT NULL DEFAULT '',
  decided_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_reply_approval_source_message
  ON channel_reply_approval_requests(source_message_id);

CREATE INDEX IF NOT EXISTS idx_channel_reply_approval_status_created
  ON channel_reply_approval_requests(status, created_at);

CREATE INDEX IF NOT EXISTS idx_channel_reply_approval_recipient
  ON channel_reply_approval_requests(channel_type, recipient, status, created_at);

CREATE TABLE IF NOT EXISTS channel_reply_permissions (
  id TEXT PRIMARY KEY,
  channel_type TEXT NOT NULL,
  recipient TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  granted_by TEXT NOT NULL,
  revoked_by TEXT NOT NULL DEFAULT '',
  revoked_reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_channel_reply_permissions_lookup
  ON channel_reply_permissions(channel_type, recipient, status, created_at);
