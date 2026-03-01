CREATE TABLE IF NOT EXISTS human_escalations (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  requested_by_actor_id TEXT NOT NULL,
  source_agent_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  channel_type TEXT NOT NULL,
  target_external_id TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'normal',
  dispatched_message_id TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_human_escalations_status_created
  ON human_escalations(status, created_at);

CREATE INDEX IF NOT EXISTS idx_human_escalations_thread_created
  ON human_escalations(thread_id, created_at);
